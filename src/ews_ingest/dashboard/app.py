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
from datetime import UTC, datetime, timedelta
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

# Save our logs to file (data/dashboard.log) + stderr (terminal) for visibility.
# We use stderr (not stdout) so the messages always reach the terminal even when
# Streamlit captures stdout. Also add a high-signal [DASH] prefix so the lines
# are easy to grep from a running `uv run streamlit run …` terminal.
_log_dir = Path("data")
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "dashboard.log"

_dash_log = logging.getLogger("ews_ingest.dashboard")
_dash_log.setLevel(logging.INFO)

# Add handlers only once (module-level code can run multiple times on reruns/imports)
if not any(isinstance(h, logging.FileHandler) for h in _dash_log.handlers):
    _file_handler = logging.FileHandler(_log_file, mode="a")
    _file_handler.setLevel(logging.INFO)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _dash_log.addHandler(_file_handler)

if not any(isinstance(h, logging.StreamHandler) for h in _dash_log.handlers):
    _console_handler = logging.StreamHandler(sys.stderr)
    _console_handler.setLevel(logging.INFO)
    fmt = "[DASH] %(asctime)s %(levelname)s %(name)s: %(message)s"
    _console_handler.setFormatter(logging.Formatter(fmt))
    _dash_log.addHandler(_console_handler)

_dash_log.propagate = False

# Also re-emit a single line on stdout at import time so the user sees
# immediately (in the terminal) that the dashboard module loaded and where
# logs will go.
print(
    f"[DASH] {datetime.now(UTC).isoformat(timespec='seconds')} "
    f"dashboard app loaded — file: {_log_file}",
    file=sys.stderr,
)


def _dash(msg: str) -> None:
    """Print a timestamped [DASH] line to stderr. Cheap, always visible."""
    print(
        f"[DASH] {datetime.now(UTC).isoformat(timespec='seconds')} {msg}",
        file=sys.stderr,
    )


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

# A ticker is considered "stuck" in pending if its background fetch hasn't
# produced a _refresh_complete marker within this window. This guards against
# interrupted fetches (e.g. process restart) that would otherwise leave the
# card in loading state forever. Kept short so a hung fetch self-heals within
# ~90s instead of staying in the loading state indefinitely.
_STUCK_PENDING_TIMEOUT = timedelta(seconds=90)


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

    Also clears *stuck* pending entries (e.g. left over from a previous process
    that was killed mid-fetch, or a fetch that hung): if a ticker has been
    pending for longer than ``_STUCK_PENDING_TIMEOUT`` we drop it so the next
    render re-triggers the fetch instead of leaving the card in loading limbo.
    """
    pending = st.session_state.setdefault("pending_refreshes", {})
    now = datetime.now(UTC)
    stuck_cleared: list[str] = []
    for tkr in list(pending.keys()):
        start_str = pending[tkr]
        start_dt: datetime | None = None
        if isinstance(start_str, str):
            try:
                start_dt = datetime.fromisoformat(start_str)
            except ValueError:
                start_dt = None
        if start_dt is None or (now - start_dt) > _STUCK_PENDING_TIMEOUT:
            stuck_cleared.append(tkr)
            pending.pop(tkr, None)
    if stuck_cleared:
        st.toast(
            "Cleared stuck data fetch (will retry): " + ", ".join(stuck_cleared),
            icon="⚠️",
        )
        _dash(f"cleared stuck pending for: {stuck_cleared}")

    newly_fetched: list[str] = []
    for company in companies:
        tkr = (company.identifiers.ticker or "").upper()
        if not tkr or tkr in pending:
            if tkr and tkr in pending:
                _dash(f"ENSURE_DATA: {tkr} already in pending, skipping kickoff")
            continue
        if hist.get_last_update(tkr):
            _dash(f"ENSURE_DATA: {tkr} already has data, skipping kickoff")
            continue
        # No data for this ticker in the DB yet — trigger background fetch.
        start = datetime.now(UTC).isoformat()
        try:
            trigger_refresh(tkr, blocking=False)
        except Exception as exc:
            logging.getLogger(__name__).warning("auto-refresh failed for %s: %s", tkr, exc)
            _dash(f"auto-refresh failed for {tkr}: {exc}")
            continue
        pending[tkr] = start
        newly_fetched.append(tkr)
        _dash(f"kicked off background refresh for {tkr} (start={start})")

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
    action = "REMOVE" if is_remove else "ADD"
    _dash(f"UI CLICK: {action} button pressed for {tkr}")
    if is_remove:
        logger.info("starting threaded mutation for REMOVE ticker=%s", tkr)
    else:
        logger.info("starting threaded mutation for ADD ticker=%s", tkr)

    def _worker() -> None:
        _dash(f"WORKER THREAD START: {action} {tkr} (thread id={threading.get_ident()})")
        try:
            _dash(f"WORKER: getting inputs for {tkr}…")
            _, _, _, store, _ = get_inputs()
            _dash(f"WORKER: got inputs for {tkr}")
            if is_remove:
                _dash(f"WORKER: calling store.remove_ticker({tkr})…")
                removed = store.remove_ticker(tkr)
                _dash(f"WORKER: remove_ticker returned {removed!r}")
                bust_inputs_cache()
                with _mutation_lock:
                    _completed_mutations[tkr] = {
                        "action": "remove",
                        "ticker": tkr,
                        "success": bool(removed),
                    }
            else:
                _dash(f"WORKER: calling store.add_ticker({tkr}) (may hit network)…")
                added = store.add_ticker(tkr)
                sector = (added.extra_ids or {}).get("sector", "?")
                _dash(
                    f"WORKER: add_ticker returned name={added.name!r} "
                    f"cik={added.cik} sector={sector!r}"
                )
                logger.info("add_ticker succeeded for %s, busting cache", tkr)
                bust_inputs_cache()
                start = datetime.now(UTC).isoformat()
                _dash(f"WORKER: calling trigger_refresh({added.ticker}, blocking=False)…")
                trigger_refresh(added.ticker, blocking=False)
                _dash(f"WORKER: trigger_refresh dispatched (start={start})")
                with _mutation_lock:
                    _completed_mutations[tkr] = {
                        "action": "add",
                        "ticker": added.ticker,
                        "start": start,
                        "success": True,
                    }
            label = "REMOVE" if is_remove else "ADD"
            logger.info("worker enqueued completion for %s %s", label, tkr)
            _dash(f"MUTATION COMPLETED: {label} {tkr} success=True")
        except TickerResolutionError as exc:
            logger.info("resolution error for %s: %s", tkr, exc)
            _dash(f"MUTATION FAILED: {tkr} resolution error: {exc}")
            with _mutation_lock:
                _completed_mutations[tkr] = {
                    "action": "add" if not is_remove else "remove",
                    "ticker": tkr,
                    "success": False,
                    "error": f"Could not resolve {tkr!r}: {exc}",
                }
        except Exception as exc:
            logger.exception("mutation worker failed for %s", tkr)
            _dash(f"MUTATION FAILED: {tkr} {type(exc).__name__}: {exc}")
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
        _dash(f"MAIN: spawned REMOVE worker thread for {tkr}")
    else:
        resolving = st.session_state.setdefault("resolving_tickers", set())
        resolving.add(tkr)
        logger.info("spawned worker thread for ADD %s, resolving set (main thread)", tkr)
        _dash(f"MAIN: spawned ADD worker thread for {tkr}")
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    _dash(f"MAIN: thread started for {tkr} (alive={thread.is_alive()})")


def _extract_text_from_response(data: dict[str, Any]) -> str:
    """Pull assistant text out of an OpenAI-compatible chat response.

    Handles plain content, tool_calls, and the case where the model emits a
    reasoning-style message with content in an unusual place. Returns "" if
    no text could be extracted.
    """
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = (choices[0] or {}).get("message") or {}
    content = (msg.get("content") or "").strip()
    if content:
        return content
    # Fall back to tool_calls text if model chose to call a tool.
    tool_calls = msg.get("tool_calls") or []
    parts: list[str] = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        arg = fn.get("arguments")
        if isinstance(arg, str) and arg.strip():
            parts.append(arg.strip())
    return "\n".join(parts).strip()


def _do_opencode_request(
    url: str, headers: dict[str, str], payload: dict[str, Any], timeout_s: float
) -> str:
    """Single HTTP call to OpenCode Zen. Returns content text or raises."""
    import httpx

    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout_s)
    if resp.status_code >= 500:
        msg = f"opencode zen http {resp.status_code}"
        raise RuntimeError(msg)
    if resp.status_code >= 400:
        msg = f"opencode zen http {resp.status_code}: {resp.text[:200]}"
        raise RuntimeError(msg)
    data = resp.json()
    text = _extract_text_from_response(data)
    if not text:
        # Log full response so the cause (finish_reason, refusal, etc.) is
        # visible in the dashboard log instead of silently dropping.
        choices = data.get("choices") or []
        first = choices[0] if choices else {}
        logger.warning(
            "opencode zen returned no text. keys=%s finish_reason=%s first_choice=%s",
            list(data.keys()),
            first.get("finish_reason") if isinstance(first, dict) else None,
            str(first)[:400],
        )
    return text


def _call_opencode_zen(
    api_key: str,
    model: str,
    base_url: str,
    messages: list[dict[str, str]],
    *,
    timeout_s: float = 60.0,
    max_retries: int = 2,
) -> str:
    """Call OpenCode Zen OpenAI-compatible /chat/completions. Returns content text.

    Retries on empty responses and 5xx / network errors. First call may hit a
    cold-start on the upstream side, so we give it a generous timeout and a
    couple of retries.
    """
    import time as _t

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 10000,
        "messages": messages,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            text = _do_opencode_request(url, headers, payload, timeout_s)
            if text:
                return text
            last_exc = RuntimeError("empty response from model")
        except Exception as exc:
            last_exc = exc
        if attempt < max_retries:
            _t.sleep(0.8 * (attempt + 1))
    msg = f"opencode zen gave up after {max_retries + 1} attempts: {last_exc}"
    raise RuntimeError(msg)


# Cheap fallback model used when the configured model returns empty.
_FALLBACK_MODEL = "gpt-5.4-nano"


def _call_opencode_zen_with_fallback(
    api_key: str,
    model: str,
    base_url: str,
    messages: list[dict[str, str]],
) -> str:
    """Try the configured model, fall back to a cheap one if it returns empty."""
    try:
        return _call_opencode_zen(api_key, model, base_url, messages)
    except RuntimeError as exc:
        if "empty response" not in str(exc) or model == _FALLBACK_MODEL:
            raise
        logger.info("primary model %s returned empty, falling back to %s", model, _FALLBACK_MODEL)
        return _call_opencode_zen(api_key, _FALLBACK_MODEL, base_url, messages)


def _build_snapshot_context() -> str:
    """Build COMPLETE live context (real data only) from current snapshot.

    Includes every company with every indicator + score + status + weight, plus
    cross-company correlations. The LLM has full visibility.
    """
    stats = st.session_state.get("latest_stats")
    computed = st.session_state.get("latest_computed", [])
    if not stats or not computed:
        return ""
    lines: list[str] = [
        f"Portfolio: {stats.n_companies} cos | mean risk {stats.mean_risk:.0f}"
        f" | {stats.n_bad} bad | {stats.n_warning} warn | {stats.n_good} good",
    ]
    if stats.indicator_contributions:
        drivers = ", ".join(f"{name} ({val:.1f})" for _, val, name in stats.indicator_contributions)
        lines.append(f"All indicator contributions (sorted): {drivers}")
    if stats.correlated_pairs:
        pairs = ", ".join(f"{a}↔{b} ({c:.2f})" for a, b, c in stats.correlated_pairs)
        lines.append(f"High-risk correlations: {pairs}")

    # Per-company block: ticker, status, composite, and EVERY indicator.
    lines.append("Companies (each shows composite, status, and ALL indicators):")
    for co, results, comp, _ in computed:
        tkr = (getattr(co, "ticker", "") or co.name or "?").upper()
        status = _composite_status(comp)
        if not results:
            lines.append(f"- {tkr}: {status} (composite {comp:.0f}, loading)")
            continue
        lines.append(f"- {tkr}: {status} (composite {comp:.0f})")
        # All indicators, sorted by score desc, formatted as label=score(status, w=weight)
        for p, r in sorted(results, key=lambda pr: pr[1].score, reverse=True):
            w = getattr(p, "weight", 0)
            lines.append(f"    {p.label} = {r.score:.0f} ({r.status}, w={w:.2f})")

    return "\n".join(lines)


_EARLY_WARNING_SYSTEM_PROMPT = (
    "You are the Early Warning Trigger Export agent for a wholesale credit "
    "portfolio risk dashboard.\n\n"
    "LIVE PORTFOLIO SNAPSHOT (real data, refreshed every render — this is the "
    "ground truth, you DO have access to it, NEVER ask the user to provide it, "
    "and the snapshot contains EVERY company with EVERY indicator value):\n"
    "<<<SNAPSHOT>>>\n"
    "{snapshot}\n"
    "<<<END SNAPSHOT>>>\n\n"
    "REPLY FORMAT:\n"
    "- Default: 1-3 short bullets, each one sentence max, concrete numbers.\n"
    "- 'summary of pain points' / 'how to fix': 2-4 short bullets, each 'pain' "
    "+ 'action' (e.g. 'Reduce X: ...').\n"
    "- 'what companies' / 'list all' / 'show indicators for X': answer directly "
    "from the snapshot — it IS complete.\n"
    "- Greetings / capability questions: 1-2 sentences.\n"
    "- No disclaimers, no hedging, no boilerplate. Direct, professional, compact."
)


_MAX_HISTORY_MESSAGES = 12  # keep recent turns only; snapshot carries the rest


def _trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the most recent N messages so we don't blow the context window."""
    if len(history) <= _MAX_HISTORY_MESSAGES:
        return history
    return history[-_MAX_HISTORY_MESSAGES:]


def _try_llm_response(history: list[dict[str, str]], snapshot_ctx: str) -> str:
    """Call the configured LLM (OpenCode Zen) and return its response.

    Caller must have already verified ``OPENCODE_API_KEY`` is set. Raises on
    any error (network, HTTP, empty response after retries + fallback model).
    """
    api_key = os.getenv("OPENCODE_API_KEY") or ""
    base_url = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
    model = os.getenv("OPENCODE_LLM_MODEL", "minimax-m3")
    system_prompt = _EARLY_WARNING_SYSTEM_PROMPT.format(snapshot=snapshot_ctx)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        *_trim_history(history),
    ]
    text = _call_opencode_zen_with_fallback(api_key, model, base_url, messages)
    if not text:
        msg = "LLM returned no content (empty response after retries)"
        raise RuntimeError(msg)
    return text


def _early_warning_agent(history: list[dict[str, str]]) -> str:
    """Early Warning Trigger Export agent.

    `history` is the full chat history (list of {role, content}); the latest
    message must be the user turn. The system prompt (with embedded live
    snapshot) is prepended automatically. Uses OpenCode Zen when
    OPENCODE_API_KEY is set; otherwise falls back to deterministic synthesis.
    """
    stats = st.session_state.get("latest_stats")
    computed = st.session_state.get("latest_computed", [])

    if not stats or not computed:
        return "No live portfolio snapshot available yet."

    snapshot_ctx = _build_snapshot_context()
    last_user = history[-1]["content"] if history and history[-1].get("role") == "user" else ""
    _dash(f"EW agent: user_msg={last_user[:60]!r} snapshot_chars={len(snapshot_ctx)}")

    # Try real LLM via OpenCode Zen (Anomaly gateway) if key present.
    # If the key is set but the call fails, return a clear error instead of
    # silently dropping to the deterministic fallback (which is misleading
    # because it ignores the user's question and just dumps a fixed insight).
    if os.getenv("OPENCODE_API_KEY"):

        def _logged_llm() -> str:
            _dash(
                f"EW agent: calling OpenCode Zen "
                f"model={os.getenv('OPENCODE_LLM_MODEL', 'minimax-m3')}"
            )
            text = _try_llm_response(history, snapshot_ctx)
            _dash(f"EW agent: LLM response chars={len(text)} preview={text[:80]!r}")
            return text

        try:
            return _logged_llm()
        except Exception as exc:
            logger.warning("OpenCode Zen call failed: %s", exc)
            _dash(f"EW agent: LLM call FAILED: {exc}")
            return f"LLM call failed: {exc}. Check key / network and try again."
    _dash("EW agent: no OPENCODE_API_KEY — using deterministic fallback")

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
    if "bad" in query or "high weight" in query:
        if "Key bad high-weight:" in snapshot_ctx:
            insights.append("Top bad high-weight signals listed in snapshot.")
        else:
            insights.append("No high-weight bad signals in current snapshot.")
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
            completed_now = list(_completed_mutations.keys())
            if completed_now:
                _dash(f"MAIN: processing {len(completed_now)} completion(s): {completed_now}")
            for orig_tkr in list(_completed_mutations.keys()):
                info = _completed_mutations.pop(orig_tkr, {})
                logger.info("processing completed mutation: %s", info)
                _dash(
                    f"MAIN: completion for {orig_tkr}: "
                    f"action={info.get('action')} success={info.get('success')}"
                )
                tkr_raw = info.get("ticker", orig_tkr)
                tkr = tkr_raw if isinstance(tkr_raw, str) else str(tkr_raw or orig_tkr)
                if info.get("success"):
                    if info.get("action") == "add":
                        start_raw = info.get("start")
                        start = (
                            start_raw
                            if isinstance(start_raw, str)
                            else datetime.now(UTC).isoformat()
                        )
                        # Race / stale-data guard: the background fetch may
                        # have ALREADY completed and written data before the
                        # main thread processes this completion (or the data
                        # is leftover from a previous run). In either case,
                        # the ticker has real DB data — show the real card
                        # immediately, don't trap the UI in loading state.
                        hist_store: HistoricalStore = make_historical_store()
                        last_data: str | None = hist_store.get_last_update(tkr)
                        already_done = last_data is not None
                        if already_done:
                            _dash(
                                f"MAIN: ADD {tkr} — data already in DB "
                                f"(data={last_data}), NOT setting pending"
                            )
                        else:
                            st.session_state.setdefault("pending_refreshes", {})[tkr] = start
                            _dash(
                                f"MAIN: applied ADD completion for {tkr} "
                                f"(pending set, force_rerun, provisional dropped)"
                            )
                        st.session_state["_toast"] = (f"Added {tkr}.", "✅")
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
                        _dash(f"MAIN: applied REMOVE completion for {tkr}")
                else:
                    err = info.get("error", f"Unknown error for {tkr}")
                    st.session_state["_last_error"] = err
                    _dash(f"MAIN: mutation ERROR for {tkr}: {err}")
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

        if pending:
            st.caption(
                "⏳ Background DB refresh(s) running for: " + ", ".join(sorted(pending.keys()))
            )

        # Clear pending once the background refresh has written the _refresh_complete
        # marker, OR the ticker has any fresh data, OR it has been pending for
        # too long (stuck fetch from a previous process, a hung source, etc.).
        now_dt = datetime.now(UTC)
        for tkr in list(pending):
            if tkr == "global":
                continue
            start = pending[tkr]
            if not isinstance(start, str):
                start = "0"  # legacy bool/float
            last_complete = hist_f.get_last_update(tkr, "_refresh_complete")
            last_data = hist_f.get_last_update(tkr)
            if last_complete and last_complete > start:
                logger.debug(
                    "clearing pending for %s (complete at %s > start %s)",
                    tkr,
                    last_complete,
                    start,
                )
                pending.pop(tkr, None)
                (st.session_state.get("_last_results_lookup") or {}).pop(tkr, None)
                continue
            if last_data and last_data > start:
                logger.debug(
                    "clearing pending for %s (data at %s > start %s)",
                    tkr,
                    last_data,
                    start,
                )
                pending.pop(tkr, None)
                (st.session_state.get("_last_results_lookup") or {}).pop(tkr, None)
                continue
            # Stuck: too long without completion → drop so next render re-fetches.
            try:
                start_dt = datetime.fromisoformat(start)
            except ValueError:
                start_dt = now_dt - _STUCK_PENDING_TIMEOUT - timedelta(seconds=1)
            if (now_dt - start_dt) > _STUCK_PENDING_TIMEOUT:
                logger.info(
                    "dropping stuck pending for %s (start=%s, no _refresh_complete)",
                    tkr,
                    start,
                )
                pending.pop(tkr, None)
                (st.session_state.get("_last_results_lookup") or {}).pop(tkr, None)
        if not pending and had_pending:
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
                # Stuck detection: if pending has been sitting too long
                # (e.g. fetch hung or was killed by a prior restart), fall
                # through to the real card instead of staying in loading
                # limbo. The next render's _ensure_data_for_new_companies
                # will re-trigger the fetch.
                try:
                    start_dt = datetime.fromisoformat(start)
                except ValueError:
                    start_dt = datetime.now(UTC) - _STUCK_PENDING_TIMEOUT - timedelta(seconds=1)
                if (datetime.now(UTC) - start_dt) > _STUCK_PENDING_TIMEOUT:
                    logger.info(
                        "card for %s: pending stuck (start=%s), falling through to real card",
                        ticker,
                        start,
                    )
                    pending.pop(ticker, None)
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
                _dash(
                    f"BUTTON CLICK: {ticker} is_present={is_present} "
                    f"action={'REMOVE' if is_present else 'ADD'}"
                )
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
                    _dash(f"BUTTON: REMOVE dispatched for {ticker}; rerunning fragment")
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
                    _dash(f"BUTTON: provisional_adds set for {ticker} (name={name!r})")
                    _start_company_mutation(ticker, is_remove=False)
                    logger.info("*** ADD started, about to rerun ***")
                    st.rerun(scope="fragment")

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    if __package__ in ("", None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
