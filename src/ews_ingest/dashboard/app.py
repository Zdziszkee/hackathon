"""Streamlit entrypoint: ``streamlit run src/ews_ingest/dashboard/app.py``.

Renders the portfolio-risk dashboard as a thin live viewer of the SQLite
historical store (see :mod:`ews_ingest.dashboard.db`). Companies are stored
in a dynamic JSON file (see :mod:`ews_ingest.dashboard.company_store`); no
hardcoded entities.yaml. Indicator bindings come from ``config/indicators.yaml``.

Data sources (ingestion CLI or scheduled) write historical records to SQLite
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
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

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

__all__ = [
    "main",
    "portfolio_stats",
]

# Back-compat re-export: the test suite imports ``_portfolio_stats`` from
# this module. The implementation now lives in :mod:`ews_ingest.dashboard.compute`.
_portfolio_stats = portfolio_stats


# ---------------------------------------------------------------------------
# Correlation graph (placeholder hardcoded data)
# ---------------------------------------------------------------------------


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
    import pandas as pd
    import yfinance as yf

    returns: dict[str, pd.Series] = {}
    tickers = [c.ticker for c in companies_graph]
    if tickers:
        try:
            hist = yf.download(tickers, period="10y", progress=False, auto_adjust=True)["Close"]
            if isinstance(hist, pd.Series):
                hist = hist.to_frame()
            rets = hist.pct_change().dropna(how="all")
            for t in tickers:
                if t in rets.columns:
                    s = rets[t].dropna()
                    if len(s) > 60:
                        returns[t] = s
        except Exception as exc:
            logging.getLogger(__name__).warning("yfinance fetch failed: %s", exc)

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

    If a user adds a company (via UI or by editing companies.json) without
    running its per-entity sources, signals fall back to demo values. This
    detects tickers missing from the historical store and fires a non-blocking
    refresh. The pending state + fingerprint cache ensure the next render
    picks up real data when it lands.
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
        try:
            trigger_refresh(tkr, blocking=False)
        except Exception as exc:
            logging.getLogger(__name__).warning("auto-refresh failed for %s: %s", tkr, exc)
            continue
        pending[tkr] = True
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


def _start_company_refresh(ticker: str) -> None:
    """Mark a company for background refresh and trigger it.
    Used from refresh buttons so we can show loading state without full page white flash.
    Toast via flag (displayed in fragment body).
    """
    start = datetime.now(UTC).isoformat()
    st.session_state.setdefault("pending_refreshes", {})[ticker] = start
    logger.info("starting refresh for ticker=%s via button", ticker)
    trigger_refresh(ticker, blocking=False)
    st.session_state["_toast"] = (f"Refreshing {ticker}…", "⏳")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    from ews_ingest.dashboard.ui import (
        inject_theme,
        render_portfolio_overview,
        render_topbar,
    )

    st.set_page_config(
        page_title="Premier Bank",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_theme()

    # Legacy queued processing (kept for backward compat with any stale flags).
    _process_queued_mutation()

    companies, landing, env, _store, suggest = get_inputs()
    hist = make_historical_store()

    providers = list_providers()
    if not providers:
        st.error("No signal providers registered.")
        return

    ctx = make_signal_ctx(landing, env, historical=hist)
    _ = get_bindings()  # bindings are preloaded by ``make_signal_ctx``

    # --- Compute indicators from DB state (cached for instant loads) ---
    # Fingerprint uses last_update timestamps from SQLite so that when a
    # background refresh lands new data the cache key changes and we recompute.
    # All other renders (interactions, navigation) are instant from cache.
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
        # fp_key only for invalidation; actual data comes from current landing
        # (populated by the same sources that feed the DB).
        return [(company, *compute_company(company, providers, ctx)) for company in companies]

    computed: list[CompanyResult] = _compute(fp)

    # --- Auto-fetch for companies added without data ---
    # If a company was added without its per-entity sources ever being run,
    # hist has no records for it and all its signals will be demo. Detect
    # and trigger a background refresh.
    _ensure_data_for_new_companies(companies, hist)

    # --- Single centered column: no sidebar, no right rail ---
    render_topbar(len(companies))

    # --- Portfolio overview panel (empty state ok) ---
    stats = portfolio_stats(computed)

    render_portfolio_overview(stats)

    # --- Company correlation graph (always expanded) ---
    if computed:
        with st.expander("Correlation graph", expanded=True):
            _render_correlation_graph(computed)
    st.caption(
        "Historical data served from SQLite DB (data/ews.db). "
        "Indicators from landed records fed by sources."
    )
    st.divider()

    run_every = 5  # poll companies section (smooth loading resolution + live updates)

    @st.fragment(run_every=run_every)
    def _companies_section(suggest: TickerSuggest) -> None:
        """Companies add/search + cards list in a single fragment.

        Live selectbox (picking does nothing).
        Conditional button (+ Add / - Remove) appears only after selection.
        Action only on button click; then full rerun so graph + overview + topbar
        update with the new company set.
        """
        # Fresh companies from persisted JSON (instant on open/restart).
        # Use outer computed for indicators; new ones show basic card until full update.
        fresh_companies, landing_f, _env_f, _store_f, _ = get_inputs()
        hist_f = make_historical_store()

        # Build lookup from outer (stable) computed
        results_lookup: dict[str, tuple[list[Any], float, int]] = {}
        for c, res, comp, fl in computed:
            results_lookup[(c.ticker or "").upper()] = (res, comp, fl)

        current_tickers = {(c.ticker or "").upper() for c in fresh_companies if c.ticker}

        st.markdown('<div class="pb-section-title">Companies</div>', unsafe_allow_html=True)

        add_col, _ = st.columns([0.38, 0.62])
        with add_col:
            _render_add_company_form(suggest, current_tickers)

        # Re-fetch companies (lightweight) so the cards section always sees the
        # latest persisted list (add/remove now also does full rerun for graph etc.).
        fresh_companies, landing_f, _env_f, _store_f, _ = get_inputs()
        hist_f = make_historical_store()
        current_tickers = {(c.ticker or "").upper() for c in fresh_companies if c.ticker}

        # pending for this render (clear after so this render can show loading states)
        pending = st.session_state.setdefault("pending_refreshes", {})
        logger.debug(
            "rendering companies section; fresh=%d pending=%s",
            len(fresh_companies),
            list(pending.keys()),
        )

        if not fresh_companies:
            st.info(
                "No companies yet. Add one above by ticker (e.g. `AAPL`, `MSFT`, "
                "`UPS`) — its CIK, name, and sector are resolved from SEC EDGAR."
            )
        else:
            _render_company_cards(
                fresh_companies,
                hist_f,
                landing_f,
                pending,
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
                    logger.info(
                        "clearing pending for %s (complete at %s > start %s)",
                        tkr,
                        last_complete,
                        start,
                    )
                    pending.pop(tkr, None)
        if pending:
            st.caption(
                "⏳ Background DB refresh(s) running for: " + ", ".join(sorted(pending.keys()))
            )

        # Display any toast scheduled during this run (from add/remove or refresh buttons).
        # Must be in fragment body.
        if "_toast" in st.session_state:
            msg, icon = st.session_state.pop("_toast")
            st.toast(msg, icon=icon)

    _companies_section(suggest)


def _render_company_cards(
    companies: list[Company],
    hist: HistoricalStore | None = None,
    landing: LandingReader | None = None,
    pending: dict[str, str] | None = None,
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
    )

    pending = pending or {}
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

        # include demo/"no data" rows so newly added companies show full indicator list
        real_results = list(results)

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

        left, right = st.columns([0.94, 0.06], gap="small")
        with left:
            render_company_card(
                company.name,
                company.sector,
                company.ticker,
                composite,
                comp_status,
                ((p.indicator_id, p.label, p.description, r) for p, r in real_results),
                last_update=last,
                anchor_id=ticker,
            )
        with right:
            if st.button(
                "↻",
                key=f"ews_refresh_{ticker}",
                help="Refresh this company",
                use_container_width=False,
                width="content",
                on_click=_start_company_refresh,
                args=(ticker,),
            ):
                pass  # on_click handles marking + triggering

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

    # Build full list of options (cached by suggest).
    options: list[str] = []
    try:
        matches = suggest.suggest("", limit=99999)
        for m in matches:
            if m.ticker:
                label = f"{m.ticker} — {m.name}" if m.name else m.ticker
                options.append(label)
    except Exception as exc:
        st.caption(f"Autocomplete list unavailable: {exc}")
        options = []

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

    if selected:
        ticker = selected.split(" — ")[0].strip().upper()
        is_present = ticker in current_tickers
        action = "Remove" if is_present else "Add"
        label = f"{'-' if is_present else '+'} {action} {ticker}"
        help_text = f"{'Remove' if is_present else 'Add'} {ticker} from the dashboard"

        st.caption(f"Press the button to {action.lower()} {ticker}")

        if st.button(
            label,
            key="company_action_btn",
            help=help_text,
            type="primary" if not is_present else "secondary",
            width="content",
        ):
            if is_present:
                try:
                    _, _, _, temp_store, _ = get_inputs()
                    if temp_store.remove_ticker(ticker):
                        bust_inputs_cache()
                        st.session_state["_toast"] = (f"Removed {ticker}", "🗑️")
                except Exception as exc:
                    st.error(f"Remove failed: {exc}")
            else:
                try:
                    _, _, _, temp_store, _ = get_inputs()
                    added = temp_store.add_ticker(ticker)
                    bust_inputs_cache()
                    start = datetime.now(UTC).isoformat()
                    st.session_state.setdefault("pending_refreshes", {})[added.ticker] = start
                    trigger_refresh(added.ticker, blocking=False)
                    st.session_state["_toast"] = (f"Added {added.ticker}. Fetching...", "⏳")
                except TickerResolutionError as exc:
                    st.error(f"Could not resolve {ticker!r}: {exc}")
                except Exception as exc:
                    st.error(f"Action failed: {exc}")

            # Clear the select so it resets for next use
            if "company_native_select" in st.session_state:
                st.session_state.pop("company_native_select", None)

            # Structural change: force full rerun so that topbar count, portfolio overview,
            # and especially the correlation graph (which is built from the outer `computed`)
            # pick up the new/removed company immediately.
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    if __package__ in ("", None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
