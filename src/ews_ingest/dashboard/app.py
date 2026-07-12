"""Streamlit entrypoint: ``streamlit run src/ews_ingest/dashboard/app.py``.

Renders the portfolio-risk dashboard as a thin live viewer of the SQLite
historical store (see :mod:`ews_ingest.dashboard.db`). Companies are stored
in a dynamic JSON file (see :mod:`ews_ingest.dashboard.company_store`); no
hardcoded entities.yaml. Indicator bindings come from ``config/indicators.yaml``.

    Data sources write historical records to SQLite (via onboarding or external fetchers)
independently. The UI computes indicators from the DB on each render and supports
global + per-company force-refresh triggers that mark pending then run the
fetch in a background thread (writing fresh records to DB).

A portfolio-level overview aggregates risk; each company shows a card with
risk indicators from auto-discovered :class:`SignalProvider` modules. Live
updates via fragments; no blocking; last-update timestamps from DB.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.companies import Company
from ews_ingest.dashboard.company_store import TickerResolutionError
from ews_ingest.dashboard.compute import (
    CompanyResult,
    compute_company,
    portfolio_stats,
)
from ews_ingest.dashboard.compute import (
    composite_status as _composite_status,
)
from ews_ingest.dashboard.db import HistoricalStore, make_historical_store
from ews_ingest.dashboard.landing import LandingReader
from ews_ingest.dashboard.services import (
    bust_inputs_cache,
    get_bindings,
    get_inputs,
    make_signal_ctx,
    trigger_refresh,
)
from ews_ingest.dashboard.signals import list_providers
from ews_ingest.dashboard.ticker_suggest import TickerSuggest

logger = logging.getLogger(__name__)

# Configure early (at import time) so INFO logs from fragments/selects/buttons always appear
# even on fragment-only reruns.
logging.getLogger("ews_ingest.dashboard").setLevel(logging.INFO)
logging.getLogger("streamlit").setLevel(logging.WARNING)

# Save our logs to file (data/dashboard.log) + stdout for visibility
# This follows Streamlit logging docs: use standard logging + config.toml for internals.
_log_dir = Path("data")
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "dashboard.log"

_dash_log = logging.getLogger("ews_ingest.dashboard")

# Add handlers only once (module-level code can run multiple times on reruns/imports)
if not any(isinstance(h, logging.FileHandler) for h in _dash_log.handlers):
    _file_handler = logging.FileHandler(_log_file, mode="a")
    _file_handler.setLevel(logging.INFO)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _dash_log.addHandler(_file_handler)

if not any(isinstance(h, logging.StreamHandler) for h in _dash_log.handlers):
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setLevel(logging.INFO)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    _console_handler.setFormatter(logging.Formatter(fmt))
    _dash_log.addHandler(_console_handler)

_dash_log.propagate = False

# Thread-safe communication from background workers to main script thread.
# Workers must NEVER touch st.session_state or any st.* (causes "missing ScriptRunContext").
_mutation_lock = threading.Lock()
_completed_mutations: dict[str, dict[str, object]] = {}

__all__ = [
    "main",
    "portfolio_stats",
]

# Back-compat re-export: the test suite imports ``_portfolio_stats`` from
# this module. The implementation now lives in :mod:`ews_ingest.dashboard.compute`.
_portfolio_stats = portfolio_stats


# ---------------------------------------------------------------------------
# Correlation graph (uses real yfinance returns + computed scores; falls back
# to sector/score heuristic only if no returns data)
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_graph_returns(tickers: tuple[str, ...]) -> dict[str, Any]:
    """Cached yfinance 10y close returns for the correlation graph."""
    import pandas as pd
    import yfinance as yf

    if not tickers:
        return {}
    try:
        hist = yf.download(list(tickers), period="10y", progress=False, auto_adjust=True)["Close"]
        if isinstance(hist, pd.Series):
            hist = hist.to_frame()
        rets = hist.pct_change().dropna(how="all")
        out: dict[str, pd.Series] = {}
        for t in tickers:
            if t in rets.columns:
                s = rets[t].dropna()
                if len(s) > 60:
                    out[t] = s
    except Exception as exc:
        logging.getLogger(__name__).warning("yfinance fetch failed: %s", exc)
        return {}
    else:
        return out


def _render_correlation_graph(computed: list[CompanyResult]) -> None:
    from ews_ingest.dashboard.graph import CompanyGraph, build_correlation_edges
    from ews_ingest.dashboard.ui import (
        render_correlation_graph,
        render_graph_jump_button,
    )

    companies_graph: list[CompanyGraph] = [
        CompanyGraph(
            name=co.name,
            score=composite,
            sector=co.sector or "Unknown",
            status=_composite_status(composite),
            ticker=(co.ticker or co.name).upper(),
        )
        for co, _res, composite, _flags in computed
    ]

    # Fetch historical returns for Granger causality (MVP: yfinance; replace
    # with your landed price/earnings surprise series in production).
    # (heavy fetch is now @st.cache_data inside _fetch_graph_returns)

    returns: dict[str, Any] = {}
    tickers = [c.ticker for c in companies_graph]
    if tickers:
        returns = _fetch_graph_returns(tuple(tickers))

    # Try Granger causality first; fall back to sector/score heuristic
    # if no returns data or no significant edges were found.
    edges = build_correlation_edges(companies_graph, returns or None)
    if not edges and companies_graph:
        edges = build_correlation_edges(companies_graph)

    returned = render_correlation_graph(companies_graph, edges)
    st.session_state["graph_selected"] = (
        returned[0][0].get("id") if returned and returned[0] else None
    )
    focus = render_graph_jump_button(st.session_state.get("graph_selected"))
    if focus:
        st.session_state["focus_company"] = focus
        st.rerun()


# ---------------------------------------------------------------------------
# Auto-fetch helper
# ---------------------------------------------------------------------------


def _ensure_data_for_new_companies(companies: list[Company], hist: HistoricalStore) -> None:
    """Kick off a background fetch for any company that has no DB records yet.

    If a user adds a company without running its per-entity sources, signals
    fall back to demo values. This detects tickers missing from the historical
    store and fires a non-blocking refresh.
    """
    pending = st.session_state.setdefault("pending_refreshes", {})
    newly_fetched: list[str] = []
    for company in companies:
        tkr = (company.identifiers.ticker or "").upper()
        if not tkr or tkr in pending:
            continue
        if hist.get_last_update(tkr):
            continue
        # No data for this ticker in the DB yet — trigger background fetch.
        start = datetime.now(UTC).isoformat()
        try:
            trigger_refresh(tkr, blocking=False)
        except Exception as exc:
            logging.getLogger(__name__).warning("auto-refresh failed for %s: %s", tkr, exc)
            continue
        pending[tkr] = start
        newly_fetched.append(tkr)

    if newly_fetched:
        st.toast(
            f"Fetching data for {', '.join(newly_fetched)}…",
            icon="⏳",
        )


def _process_queued_mutation() -> None:
    """Legacy support for any remaining _pending_mutation flags.
    Current add/remove uses direct select handling inside the companies fragment.
    """
    mutation = st.session_state.pop("_pending_mutation", None)
    if mutation:
        action = mutation.get("action")
        tkr = mutation.get("ticker")
        if tkr and action == "add":
            try:
                _, _, _, temp_store, _ = get_inputs()
                added = temp_store.add_ticker(tkr)
                bust_inputs_cache()
                start = datetime.now(UTC).isoformat()
                st.session_state.setdefault("pending_refreshes", {})[added.ticker] = start
                trigger_refresh(added.ticker, blocking=False)
                st.toast(f"Added {added.ticker}. Fetching data in background…", icon="⏳")
            except TickerResolutionError as exc:
                st.error(f"Could not resolve {tkr!r}: {exc}")
            except Exception as exc:
                st.error(f"Action failed: {exc}")


def _start_company_mutation(ticker: str, *, is_remove: bool) -> None:
    tkr = ticker.strip().upper()
    if is_remove:
        logger.info("starting threaded mutation for REMOVE ticker=%s", tkr)
    else:
        logger.info("starting threaded mutation for ADD ticker=%s", tkr)

    def _worker() -> None:
        logger.info("worker thread starting for %s", tkr)
        try:
            _, _, _, store, _ = get_inputs()
            if is_remove:
                removed = store.remove_ticker(tkr)
                bust_inputs_cache()
                with _mutation_lock:
                    _completed_mutations[tkr] = {
                        "action": "remove",
                        "ticker": tkr,
                        "success": bool(removed),
                    }
            else:
                added = store.add_ticker(tkr)
                logger.info("add_ticker succeeded for %s, busting cache", tkr)
                bust_inputs_cache()
                start = datetime.now(UTC).isoformat()
                trigger_refresh(added.ticker, blocking=False)
                with _mutation_lock:
                    _completed_mutations[tkr] = {
                        "action": "add",
                        "ticker": added.ticker,
                        "start": start,
                        "success": True,
                    }
            label = "REMOVE" if is_remove else "ADD"
            logger.info("worker enqueued completion for %s %s", label, tkr)
        except TickerResolutionError as exc:
            logger.info("resolution error for %s: %s", tkr, exc)
            with _mutation_lock:
                _completed_mutations[tkr] = {
                    "action": "add" if not is_remove else "remove",
                    "ticker": tkr,
                    "success": False,
                    "error": f"Could not resolve {tkr!r}: {exc}",
                }
        except Exception as exc:
            logger.exception("mutation worker failed for %s", tkr)
            with _mutation_lock:
                _completed_mutations[tkr] = {
                    "action": "add" if not is_remove else "remove",
                    "ticker": tkr,
                    "success": False,
                    "error": f"Action failed for {tkr}: {exc}",
                }
        logger.info("worker finished for %s", tkr)

    if is_remove:
        removing = st.session_state.setdefault("removing_tickers", set())
        removing.add(tkr)
        logger.info("spawned worker thread for REMOVE %s, removing set (main thread)", tkr)
    else:
        resolving = st.session_state.setdefault("resolving_tickers", set())
        resolving.add(tkr)
        logger.info("spawned worker thread for ADD %s, resolving set (main thread)", tkr)
    threading.Thread(target=_worker, daemon=True).start()


def _call_opencode_zen(
    api_key: str, model: str, base_url: str, messages: list[dict[str, str]]
) -> str:
    """Call OpenCode Zen OpenAI-compatible /chat/completions. Returns content text."""
    import httpx

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 220,
        "messages": messages,
    }
    resp = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30.0,
    )
    if resp.status_code >= 400:
        msg = f"opencode zen http {resp.status_code}: {resp.text[:200]}"
        raise RuntimeError(msg)
    data = resp.json()
    return ((data.get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()


def _build_snapshot_context() -> str:
    """Build minimal live context (real data only) from current snapshot."""
    stats = st.session_state.get("latest_stats")
    computed = st.session_state.get("latest_computed", [])
    if not stats or not computed:
        return ""
    context_lines = [
        f"Portfolio: {stats.n_companies} cos | mean risk {stats.mean_risk:.0f} | {stats.n_bad} bad",
    ]
    if stats.indicator_contributions:
        drivers = ", ".join(
            f"{name} ({val:.1f})" for _, val, name in stats.indicator_contributions[:4]
        )
        context_lines.append(f"Top weighted drivers: {drivers}")
    if stats.correlated_pairs:
        pairs = ", ".join(f"{a}↔{b} ({c:.2f})" for a, b, c in stats.correlated_pairs[:3])
        context_lines.append(f"High-risk correlations: {pairs}")
    bad_high_w: list[str] = []
    for co, results, _, _ in computed:
        for p, r in results:
            if r.status == "bad" and getattr(p, "weight", 0) >= 0.08:
                bad_high_w.append(
                    f"{co.ticker or co.name} {p.label}={r.score} (w={getattr(p, 'weight', 0):.2f})"
                )
                break
    if bad_high_w:
        context_lines.append("Key bad high-weight: " + " | ".join(bad_high_w[:3]))
    return "\n".join(context_lines)


_EARLY_WARNING_SYSTEM_PROMPT = (
    "You are the Early Warning Trigger Export agent for a wholesale credit "
    "portfolio risk dashboard. You are given:\n"
    "  1. A live, real-data-only snapshot of the current portfolio (mean risk, "
    "bad counts, top weighted drivers, high-risk correlations, key bad high-weight "
    "signals).\n"
    "  2. The running chat history between you and the user.\n\n"
    "Your job: reply with 1-3 ultra-short, professional insights per turn. "
    "Focus on early-warning triggers using factor models, network contagion, tail "
    "clustering, and leading-indicator logic. For greetings or capability questions, "
    "reply conversationally in 1-2 sentences. Never use disclaimers, hedging, or "
    "boilerplate. Be direct and compact. One sentence max per point."
)


def _early_warning_agent(history: list[dict[str, str]]) -> str:
    """Early Warning Trigger Export agent.

    `history` is the full chat history (list of {role, content}); the latest
    message must be the user turn. The system prompt + live snapshot are
    prepended automatically. Uses OpenCode Zen when OPENCODE_API_KEY is set;
    otherwise falls back to deterministic synthesis.
    """
    stats = st.session_state.get("latest_stats")
    computed = st.session_state.get("latest_computed", [])

    if not stats or not computed:
        return "No live portfolio snapshot available yet."

    snapshot_ctx = _build_snapshot_context()
    last_user = history[-1]["content"] if history and history[-1].get("role") == "user" else ""

    # Try real LLM via OpenCode Zen (Anomaly gateway) if key present
    api_key = os.getenv("OPENCODE_API_KEY")
    if api_key:
        try:
            base_url = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
            model = os.getenv("OPENCODE_LLM_MODEL", "minimax-m3")
            messages: list[dict[str, str]] = [
                {"role": "system", "content": _EARLY_WARNING_SYSTEM_PROMPT},
                {
                    "role": "system",
                    "content": (f"Current portfolio snapshot (live, real data):\n{snapshot_ctx}"),
                },
                *history,
            ]
            text = _call_opencode_zen(api_key, model, base_url, messages)
            if text:
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                return " ".join(lines[:3]) if lines else text[:280]
        except Exception as exc:
            logger.info("OpenCode Zen call failed, falling back to deterministic: %s", exc)

    # Deterministic fallback (no key or LLM error)
    query = last_user.lower().strip()
    tokens = {t.strip(".,!?") for t in query.split() if t.strip(".,!?")}
    greeting_tokens = {"hi", "hello", "hey", "yo", "sup", "hola"}
    capability_phrases = (
        "what can you do",
        "what do you do",
        "who are you",
        "help me",
        "how do you work",
        "capabilities",
        "what are you",
    )
    is_greeting = bool(tokens & greeting_tokens) and len(tokens) <= 4
    is_capability = any(p in query for p in capability_phrases) and not is_greeting
    is_empty = len(tokens) == 0

    if is_greeting or is_empty:
        return (
            f"Hi — I'm watching {stats.n_companies} cos "
            f"(mean risk {stats.mean_risk:.0f}, {stats.n_bad} bad). "
            "Ask about drivers, correlations, bad high-weight signals, or contagion risk."
        )
    if is_capability:
        return (
            "I read the live portfolio snapshot (mean risk, bad counts, top drivers, "
            "correlations) and reply with 1-3 ultra-short insights. Try: "
            "'main risk driver', 'any bad signals?', 'correlation clusters?', "
            "'why is X bad?'."
        )

    insights: list[str] = []
    if stats.mean_risk >= 55:
        insights.append(f"Mean risk {stats.mean_risk:.0f} — monitor factor exposures.")
    if stats.indicator_contributions:
        top = stats.indicator_contributions[0]
        insights.append(
            f"Dominant driver: {top[2]} (contrib {top[1]:.1f}). Key EWI per factor models."
        )
    if stats.correlated_pairs:
        insights.append("Correlation clusters active — contagion risk (network models).")
    if ("bad" in query or "high weight" in query) and "Key bad high-weight:" in snapshot_ctx:
        insights.append("High-weight bad signals already listed above.")
    if not insights:
        insights.append("No acute EWI triggers in current snapshot.")
    return " ".join(insights[:3])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    from ews_ingest.dashboard.ui import (
        inject_theme,
        render_portfolio_overview,
        render_topbar,
    )

    logger.info("main() entry — full script run starting (this is what can feel like freeze)")

    # Ensure our info logs are emitted when streamlit is started with --logger.level=info
    logging.getLogger("ews_ingest.dashboard").setLevel(logging.INFO)
    # Suppress noisy streamlit internals so our INFO logs are easier to see
    logging.getLogger("streamlit").setLevel(logging.WARNING)

    st.set_page_config(
        page_title="Premier Bank",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_theme()

    # Legacy queued processing (kept for backward compat with any stale flags).
    _process_queued_mutation()

    logger.info("main: before get_inputs")
    companies, _landing, _env, _store, suggest = get_inputs()
    logger.info("main: got %d companies from get_inputs", len(companies))

    _providers = list_providers()
    if not _providers:
        st.error("No signal providers registered.")
        return

    _ = get_bindings()  # bindings are preloaded by ``make_signal_ctx``

    render_topbar(len(companies))

    @st.fragment
    def _portfolio_and_graph() -> None:
        companies, landing, env, _store, _ = get_inputs()
        hist = make_historical_store()
        providers = list_providers()
        if not providers:
            return
        ctx = make_signal_ctx(landing, env, historical=hist)

        def _fp() -> str:
            parts: list[str] = []
            for company in companies:
                t = (company.ticker or "").upper()
                last = hist.get_last_update(t) or "never"
                parts.append(f"{t}={last}")
            blob = "|".join(sorted(parts))
            return hashlib.md5(blob.encode("utf-8")).hexdigest()[:12]  # noqa: S324

        fp = _fp()

        @st.cache_data(show_spinner=False)
        def _compute(fp_key: str) -> list[CompanyResult]:  # noqa: ARG001
            return [(company, *compute_company(company, providers, ctx)) for company in companies]

        computed: list[CompanyResult] = _compute(fp)
        _ensure_data_for_new_companies(companies, hist)
        stats = portfolio_stats(computed)

        # Store latest snapshot for AI agent chat
        st.session_state["latest_stats"] = stats
        st.session_state["latest_computed"] = computed

        # Compute correlated high-risk pairs for the overview widget.
        # Uses the same graph logic (yfinance returns when available).
        try:
            from dataclasses import replace

            from ews_ingest.dashboard.graph import CompanyGraph, build_correlation_edges

            companies_graph: list[CompanyGraph] = [
                CompanyGraph(
                    name=co.name,
                    score=composite,
                    sector=co.sector or "Unknown",
                    status=_composite_status(composite),
                    ticker=(co.ticker or co.name).upper(),
                )
                for co, _res, composite, _flags in computed
            ]
            returns: dict[str, Any] = {}
            tickers = [c.ticker for c in companies_graph]
            if tickers:
                returns = _fetch_graph_returns(tuple(tickers))
            edges = build_correlation_edges(companies_graph, returns or None)
            if not edges and companies_graph:
                edges = build_correlation_edges(companies_graph)
            high_risk = {
                c.ticker
                for c in companies_graph
                if c.status in ("warning", "bad") or c.score >= 60.0
            }
            corr_pairs: list[tuple[str, str, float]] = []
            for a, b, corr in edges:
                if a in high_risk and b in high_risk and abs(corr) >= 0.55:
                    corr_pairs.append((a, b, round(float(corr), 2)))
            corr_pairs = sorted(corr_pairs, key=lambda x: -abs(x[2]))[:5]
            if corr_pairs:
                stats = replace(stats, correlated_pairs=corr_pairs)
        except Exception:  # noqa: S110 - non-fatal for widget
            pass

        render_portfolio_overview(stats, computed=computed)
        try:
            if computed:
                with st.expander("Correlation graph", expanded=True):
                    _render_correlation_graph(computed)
        except Exception as exc:
            logger.info("correlation graph rendering failed (non-fatal): %s", exc)
            st.caption("⚠️ Correlation graph unavailable")
        st.caption(
            "Historical data served from SQLite DB (data/ews.db). "
            "Indicators from landed records fed by sources."
        )
        st.divider()

    _portfolio_and_graph()

    pending_now = st.session_state.get("pending_refreshes", {}) or {}
    run_every = 5 if pending_now else None

    @st.fragment(run_every=run_every)
    def _companies_section(suggest: TickerSuggest) -> None:
        """Companies add/search + cards list in a single fragment.

        Add/remove (and associated background data refreshes) are handled via
        background threads + fragment-scoped updates where possible so only
        the concerned company card is affected during the operation. Full rerun
        only to (de)activate polling or after structural list changes for the
        graph/overview.
        """
        logger.info("_companies_section ENTER (fragment body running)")
        # Fresh companies from SQLite DB (instant on open/restart).
        fresh_companies, landing_f, _env_f, _store_f, _ = get_inputs()
        logger.info("_companies_section after first get_inputs: %d companies", len(fresh_companies))
        st.caption(f"🔧 DEBUG fragment: after first fetch | companies={len(fresh_companies)}")
        hist_f = make_historical_store()

        current_tickers = {(c.ticker or "").upper() for c in fresh_companies if c.ticker}

        st.markdown('<div class="pb-section-title">Companies</div>', unsafe_allow_html=True)

        add_col, _ = st.columns([0.38, 0.62])
        with add_col:
            _render_add_company_form(suggest, current_tickers)

        # Re-fetch companies (lightweight) so the cards section always sees the
        # latest persisted list from DB. Compute indicators *inside the fragment*
        # so refreshes for one ticker update only the concerned card (light
        # fragment rerun) without forcing outer graph/stats recompute.
        fresh_companies, landing_f, _env_f, _store_f, _ = get_inputs()
        hist_f = make_historical_store()
        current_tickers = {(c.ticker or "").upper() for c in fresh_companies if c.ticker}
        for key in ("resolving_tickers", "removing_tickers"):
            ss_set = st.session_state.get(key) or set()
            if ss_set:
                st.session_state[key] = ss_set & current_tickers

        # Handle provisional adds (from select label) so add shows a card *instantly*
        # with known name/ticker while real resolution + data fetch happens in bg.
        provisional_adds: dict[str, dict[str, str]] = (
            st.session_state.get("provisional_adds", {}) or {}
        )
        for t in list(provisional_adds):
            if t in current_tickers:
                provisional_adds.pop(t, None)
        if provisional_adds:
            st.session_state["provisional_adds"] = provisional_adds
        else:
            st.session_state.pop("provisional_adds", None)

        # Augment display list with any provisionals not yet in DB
        display_companies = list(fresh_companies)
        for tkr, pinfo in provisional_adds.items():
            if tkr not in current_tickers:
                ident = Identifiers(
                    ticker=tkr,
                    name=pinfo.get("name", tkr),
                    extra_ids={"sector": pinfo.get("sector", "")},
                )
                display_companies.append(Company(identifiers=ident))

        update_ts = time.time()
        tickers = [c.ticker for c in fresh_companies]
        logger.info(
            "DASHBOARD ACTUALLY UPDATED: companies=%d %s at ts=%.3f",
            len(fresh_companies),
            tickers,
            update_ts,
        )

        pending = st.session_state.setdefault("pending_refreshes", {})
        resolving = st.session_state.get("resolving_tickers", set()) or set()
        removing = st.session_state.get("removing_tickers", set()) or set()
        had_pending = bool(pending)

        # Process any completions from background workers (SAFE: this is main thread)
        with _mutation_lock:
            for orig_tkr in list(_completed_mutations.keys()):
                info = _completed_mutations.pop(orig_tkr, {})
                logger.info("processing completed mutation: %s", info)
                tkr = info.get("ticker", orig_tkr)
                if info.get("success"):
                    if info.get("action") == "add":
                        start = info.get("start") or datetime.now(UTC).isoformat()
                        st.session_state.setdefault("pending_refreshes", {})[tkr] = start
                        st.session_state["_toast"] = (f"Added {tkr}. Fetching data…", "⏳")
                        st.session_state["_force_full_rerun"] = True
                        # real one now in DB; drop provisional
                        prov = st.session_state.get("provisional_adds") or {}
                        prov.pop(tkr, None)
                        if not prov:
                            st.session_state.pop("provisional_adds", None)
                        logger.info(
                            "applied add completion for %s "
                            "(set pending + toast + force) *** will reflect on next update ***",
                            tkr,
                        )
                    elif info.get("action") == "remove":
                        st.session_state["_toast"] = (f"Removed {tkr}", "🗑️")
                        st.session_state["_force_full_rerun"] = True
                else:
                    st.session_state["_last_error"] = info.get("error", f"Unknown error for {tkr}")
                    logger.info("applied error from mutation for %s", tkr)
                # always clear any provisional for this ticker on completion
                if info.get("action") == "add":
                    prov = st.session_state.get("provisional_adds") or {}
                    prov.pop(tkr, None)
                    if not prov:
                        st.session_state.pop("provisional_adds", None)
                resolving.discard(orig_tkr)
                resolving.discard(tkr)
                removing = st.session_state.get("removing_tickers", set()) or set()
                removing.discard(orig_tkr)
                removing.discard(tkr)
                st.session_state["removing_tickers"] = removing
                if "company_native_select" in st.session_state:
                    st.session_state.pop("company_native_select", None)
                logger.info("*** MUTATION PROCESSED in main, next render shows updated list ***")

        if st.session_state.pop("_force_full_rerun", False):
            logger.info("force flag — frag rerun (cos); overview later")
            st.rerun(scope="fragment")

        # refresh sets after possible process clears
        pending = st.session_state.setdefault("pending_refreshes", {})
        resolving = st.session_state.get("resolving_tickers", set()) or set()
        removing = st.session_state.get("removing_tickers", set()) or set()
        provisional_adds = st.session_state.get("provisional_adds", {}) or {}
        had_pending = bool(pending) or had_pending

        last_res = st.session_state.get("_last_results_lookup") or {}
        results_lookup: dict[str, tuple[list[Any], float, int]] = last_res.copy()
        active_mut = set(pending.keys()) | resolving | removing | set(provisional_adds.keys())
        for t in provisional_adds:
            results_lookup.setdefault(t, ([], 0.0, 0))
        to_compute: list[Any] = []
        for company in fresh_companies:
            t = (company.ticker or "").upper()
            if t in active_mut:
                if t not in results_lookup:
                    results_lookup[t] = ([], 0.0, 0)
                continue
            if t in results_lookup:
                continue
            to_compute.append(company)
        if to_compute:
            providers_f = list_providers()
            ctx_f = make_signal_ctx(landing_f, _env_f, historical=hist_f)
            logger.info("computing indicators inside fragment (on demand) for %d", len(to_compute))
            for company in to_compute:
                t = (company.ticker or "").upper()
                try:
                    res, comp, fl = compute_company(company, providers_f, ctx_f)
                except Exception:
                    res, comp, fl = [], 0.0, 0
                results_lookup[t] = (res, comp, fl)
            logger.info("finished inside-fragment indicator compute (partial)")
        else:
            logger.info("reused cached indicator results for fragment render")
        st.session_state["_last_results_lookup"] = {
            k: v for k, v in results_lookup.items() if k in current_tickers
        }

        logger.info(
            "companies fragment render start: n=%d pending=%s resolving=%s removing=%s",
            len(fresh_companies),
            list(pending.keys()),
            list(resolving),
            list(removing),
        )

        # Surface any background error from threaded mutation (non-fatal).
        if "_last_error" in st.session_state:
            err = st.session_state.pop("_last_error")
            logger.info("showing last_error: %s", err)
            st.error(err)

        if not display_companies:
            st.info(
                "No companies yet. Add one above by ticker (e.g. `AAPL`, `MSFT`, "
                "`UPS`) — its CIK, name, and sector are resolved from SEC EDGAR."
            )
        else:
            _render_company_cards(
                display_companies,
                hist_f,
                landing_f,
                pending,
                removing,
                provisional=provisional_adds,
                results_lookup=results_lookup,
            )

        # Clear pending only once the background refresh has written the _refresh_complete
        # marker (i.e. all per-entity sources have finished, whether they produced data,
        # "no data found", or rate-limited markers). This guarantees the card shows the
        # full indicator list instead of a partially populated one.
        for tkr in list(pending):
            if tkr != "global":
                start = pending[tkr]
                if not isinstance(start, str):
                    start = "0"  # legacy bool/float
                last_complete = hist_f.get_last_update(tkr, "_refresh_complete")
                if last_complete and last_complete > start:
                    logger.debug(
                        "clearing pending for %s (complete at %s > start %s)",
                        tkr,
                        last_complete,
                        start,
                    )
                    pending.pop(tkr, None)
                    (st.session_state.get("_last_results_lookup") or {}).pop(tkr, None)
        if pending:
            st.caption(
                "⏳ Background DB refresh(s) running for: " + ", ".join(sorted(pending.keys()))
            )
        elif had_pending:
            # We just cleared the final pending entry (either in cards or here).
            # Force a full app rerun so outer code re-defines @st.fragment
            # with run_every=None (stopping the background polling).
            st.rerun(scope="app")

        # Display any toast scheduled during this run (from add/remove).
        # Must be in fragment body.
        if "_toast" in st.session_state:
            msg, icon = st.session_state.pop("_toast")
            st.toast(msg, icon=icon)

    _companies_section(suggest)

    # ---------------------------------------------------------------------------
    # Early Warning Trigger Agent Chat (bottom of app)
    # ---------------------------------------------------------------------------
    st.divider()

    st.markdown("### 🤖 Early Warning Trigger Agent")
    st.caption("Compact EWI insights (portfolio + indicators + corr). SOTA lens.")

    # Chat history
    if "ew_messages" not in st.session_state:
        st.session_state.ew_messages = []

    # Display chat history
    for message in st.session_state.ew_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input pinned at bottom (idiomatic Streamlit)
    if prompt := st.bottom.chat_input("Ask about early warning triggers..."):
        # Add user message
        st.session_state.ew_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        response = _early_warning_agent(st.session_state.ew_messages)
        st.session_state.ew_messages.append({"role": "assistant", "content": response})
        with st.chat_message("assistant"):
            st.markdown(response)


def _render_company_cards(
    companies: list[Company],
    hist: HistoricalStore | None = None,
    landing: LandingReader | None = None,
    pending: dict[str, str] | None = None,
    removing: set[str] | None = None,
    provisional: dict[str, dict[str, str]] | None = None,
    *,
    results_lookup: dict[str, tuple[list[object], float, int]] | None = None,
) -> None:
    """Render the list of company cards (or loading states).

    Accepts a list of companies (fresh) + optional results_lookup for the details.
    Tickers in pending (value = ISO start time) show the loading card until
    _refresh_complete marker timestamp > start.
    """
    from ews_ingest.dashboard.ui import (
        render_company_card,
        render_loading_company_card,
        render_removing_company_card,
    )

    pending = pending or {}
    removing = removing or set()
    provisional = provisional or {}
    results_lookup = results_lookup or {}

    focus_ticker = st.session_state.pop("focus_company", None)
    scroll_key = f"scroll_done_{focus_ticker}" if focus_ticker else None
    if focus_ticker and scroll_key:
        st.session_state.setdefault(scroll_key, False)

    # Build display items from fresh companies (new ones use lookup fallback)
    items: list[tuple[Company, list[Any], float, int]] = []
    for company in companies:
        t = (company.ticker or "").upper()
        if t in results_lookup:
            res, comp, fl = results_lookup[t]
        else:
            res, comp, fl = [], 0.0, 0
        items.append((company, res, comp, fl))

    sorted_results = sorted(items, key=lambda x: -x[2])

    for company, results, composite, _flags in sorted_results:
        comp_status = _composite_status(composite)
        ticker = (company.ticker or "").upper()

        logger.debug(
            "card for %s: indicators=%d composite=%.1f pending=%s",
            ticker,
            len(results),
            composite,
            ticker in pending,
        )

        real_results = list(results)

        if ticker in removing:
            render_removing_company_card(company.name, ticker)
            continue

        if ticker in provisional:
            render_loading_company_card(company.name, company.sector, ticker)
            continue

        if ticker in pending:
            # Show loading until the _refresh_complete marker (written after ALL
            # per-entity sources for this ticker have run) is present and newer
            # than the start time we recorded. This ensures the real card shows
            # the complete indicator set (data + no-data + rate-limited) at once.
            start = pending[ticker]
            if not isinstance(start, str):
                start = "0"
            last_complete = hist.get_last_update(ticker, "_refresh_complete") if hist else None
            if last_complete and last_complete > start:
                pending.pop(ticker, None)
                (st.session_state.get("_last_results_lookup") or {}).pop(ticker, None)
                logger.debug("switching %s from loading to real card (complete marker)", ticker)
            else:
                render_loading_company_card(
                    company.name,
                    company.sector,
                    ticker,
                )
                continue

        last = hist.get_last_update(ticker) if hist else None
        if not last and landing:
            last = landing.latest_fetched_at(
                ticker,
                name=company.identifiers.name if hasattr(company, "identifiers") else None,
                cik=company.identifiers.cik if hasattr(company, "identifiers") else None,
            )

        render_company_card(
            company.name,
            company.sector,
            company.ticker,
            composite,
            comp_status,
            (
                (p.indicator_id, p.label, p.description, getattr(p, "weight", 1.0), r)
                for p, r in real_results
            ),
            last_update=last,
            anchor_id=ticker,
        )

    if focus_ticker and scroll_key and not st.session_state.get(scroll_key):
        import streamlit.components.v1 as _st_v1

        _st_v1.html(_focus_scroll_js(focus_ticker), height=0)
        st.session_state[scroll_key] = True


def _focus_scroll_js(ticker: str) -> str:
    safe = ticker.replace('"', "").replace("'", "")
    return (
        "<script>(function(){"
        f"const el=document.getElementById('pb-co-{safe}');"
        "if(el){el.open=true;el.scrollIntoView({behavior:'smooth',block:'start'});}"
        "})();</script>"
    )


def _render_add_company_form(
    suggest: TickerSuggest, current_tickers: set[str] | None = None
) -> None:
    """Add/remove widget: live fuzzy selectbox + button that appears only after picking.

    Picking from the list does nothing by itself (no auto action).
    When something is selected, a caption + button appears with clear info
    ("+ Add TICKER" or "- Remove TICKER").
    Action happens only on explicit button click.
    This is the simple idiomatic Streamlit pattern (per docs: selectbox changes
    are live; use button for the actual mutation to avoid accidental triggers).
    """
    current_tickers = current_tickers or set()
    logger.info("_render_add_company_form ENTER: current_tickers=%s", sorted(current_tickers))

    # Build full list of options (cached by suggest + st.cache for widget perf).
    # Huge option list (10k+) rebuilt on every fragment interaction was a source
    # of lag in add/remove.
    @st.cache_data(show_spinner=False, ttl=300)
    def _build_options() -> list[str]:
        try:
            matches = suggest.suggest("", limit=99999)
            opts: list[str] = []
            for m in matches:
                if m.ticker:
                    label = f"{m.ticker} — {m.name}" if m.name else m.ticker
                    opts.append(label)
        except Exception:
            return []
        else:
            return opts

    options: list[str] = _build_options()
    logger.info("using %d options for selectbox (from cache)", len(options))

    st.markdown('<div class="pb-add-widget">', unsafe_allow_html=True)

    selected = st.selectbox(
        "Add or remove company",
        options=options,
        index=None,
        placeholder="Type ticker or name (fuzzy search)",
        filter_mode="fuzzy",
        label_visibility="collapsed",
        key="company_native_select",
        width=260,
    )
    logger.info("selectbox value after render: %r", selected)

    if selected:
        ticker = selected.split(" — ")[0].strip().upper()
        is_present = ticker in current_tickers
        resolving = st.session_state.get("resolving_tickers", set()) or set()
        removing = st.session_state.get("removing_tickers", set()) or set()
        is_busy = ticker in resolving or ticker in removing

        logger.info(
            "selectbox selected ticker=%s is_present=%s is_busy=%s",
            ticker,
            is_present,
            is_busy,
        )

        action = "Remove" if is_present else "Add"
        label = f"{'-' if is_present else '+'} {action} {ticker}"
        help_text = f"{'Remove' if is_present else 'Add'} {ticker} from the dashboard"

        if is_busy:
            verb = "Resolving / updating" if ticker in resolving else "Removing"
            st.caption(f"⏳ {verb} {ticker}… (non-blocking)")
            logger.info("showing busy state for %s", ticker)
        else:
            st.caption(f"Press the button to {action.lower()} {ticker}")

            if st.button(
                label,
                key=f"company_action_btn_{ticker}",
                help=help_text,
                type="primary" if not is_present else "secondary",
                width="content",
                disabled=is_busy,
            ):
                click_ts = time.time()
                logger.info(
                    "*** BUTTON CLICK: ticker=%s present=%s (remove=%s) ts=%.3f ***",
                    ticker,
                    is_present,
                    is_present,
                    click_ts,
                )
                if is_present:
                    logger.info("*** EXECUTING REMOVE for %s (threaded) ***", ticker)
                    _start_company_mutation(ticker, is_remove=True)
                    logger.info("*** REMOVE started, about to rerun ***")
                    st.rerun(scope="fragment")
                else:
                    logger.info("*** EXECUTING ADD for %s (threaded) ***", ticker)
                    # Stash provisional info from the select label for instant UI card
                    name = ticker
                    if " — " in selected:
                        parts = selected.split(" — ", 1)
                        if len(parts) > 1:
                            name = parts[1].strip()
                    st.session_state.setdefault("provisional_adds", {})[ticker] = {
                        "name": name,
                        "sector": "",
                    }
                    _start_company_mutation(ticker, is_remove=False)
                    logger.info("*** ADD started, about to rerun ***")
                    st.rerun(scope="fragment")

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    if __package__ in ("", None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
