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
from collections.abc import Iterable
from pathlib import Path

import streamlit as st

from ews_ingest.dashboard.companies import Company
from ews_ingest.dashboard.company_store import CompanyStore, TickerResolutionError
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
from ews_ingest.dashboard.signals.protocol import SignalProvider, SignalResult
from ews_ingest.dashboard.ticker_suggest import TickerSuggest

__all__ = [
    "main",
    "portfolio_stats",
]

# Back-compat re-export: the test suite imports ``_portfolio_stats`` from
# this module. The implementation now lives in :mod:`ews_ingest.dashboard.compute`.
_portfolio_stats = portfolio_stats


def _collect_sources(
    results: Iterable[tuple[SignalProvider, SignalResult]],
) -> list[str]:
    """Deduplicate and sort the ``source_ids`` across a company's results."""
    seen: set[str] = set()
    for _provider, result in results:
        for sid in result.source_ids:
            if sid and sid not in seen:
                seen.add(sid)
    return sorted(seen)


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


# Per-entity source IDs that are needed for the dashboard's per-company
# signals (everything else is global/macro). If a company has zero landing
# records from any of these, its signals will all be demo.
_PER_ENTITY_SOURCE_IDS = (
    "news.hackernews",
    "news.gdelt",
    "credit_market.sec_form4_13f",
    "credit_market.yahoo",
    "company_financials.submissions",
    "company_financials.company_facts",
    "sanctions.opensanctions",
    "identity.wikidata",
    "universe.sec_sic_codes",
    "labor.state_warn_ny",
)


def _ensure_data_for_new_companies(companies: list[Company], landing: LandingReader) -> None:
    """Kick off a background fetch for any company that has no landing data.

    If a user adds a company to the store (via the UI, by editing the JSON
    file, or by some other path) without the per-entity sources being re-run,
    every per-company signal on that card falls back to "demo". This helper
    detects those companies and triggers a non-blocking refresh, so the next
    render shows real numbers.

    We mark the ticker in ``st.session_state["pending_refreshes"]`` so the
    existing "background refresh running" caption picks it up, and the
    existing fingerprint cache key includes ``last_update`` so the next
    render recomputes once the data lands.
    """
    pending = st.session_state.setdefault("pending_refreshes", {})
    newly_fetched: list[str] = []
    for company in companies:
        tkr = (company.identifiers.ticker or "").upper()
        if not tkr or tkr in pending:
            continue
        # Cheap check: does this ticker have *any* per-entity record landed?
        has_data = False
        for sid in _PER_ENTITY_SOURCE_IDS:
            try:
                if landing.read(sid).records:
                    has_data = True
                    break
            except Exception as exc:
                logging.getLogger(__name__).debug("landing.read(%s) failed: %s", sid, exc)
                continue
        if has_data:
            continue
        # No data for this company — kick off a background refresh.
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

    companies, landing, env, store, suggest = get_inputs()
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
    # If a company was added to the store (manually or via the UI) but the
    # per-entity sources were never re-run, its landing zone is empty and
    # every signal falls back to "demo". Detect those companies and kick
    # off a background refresh so the next render shows real numbers.
    _ensure_data_for_new_companies(companies, landing)

    pending = st.session_state.setdefault("pending_refreshes", {})
    if pending:
        # auto-clear any that now have DB records
        for tkr in list(pending):
            if tkr != "global" and hist.get_last_update(tkr):
                pending.pop(tkr, None)
        if pending:
            st.caption(
                "⏳ Background DB refresh(s) running for: " + ", ".join(sorted(pending.keys()))
            )

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

    # --- Add-company form (search bar at top of companies section) ---
    st.markdown('<div class="pb-section-title">Companies</div>', unsafe_allow_html=True)

    current_tickers = {(c.ticker or "").upper() for c in companies if c.ticker}

    # Narrow left-aligned search box (small width in left corner)
    add_col, _ = st.columns([0.38, 0.62])
    with add_col:
        _render_add_company_form(store, suggest, current_tickers)

    if not computed:
        st.info(
            "No companies yet. Add one above by ticker (e.g. `AAPL`, `MSFT`, "
            "`UPS`) — its CIK, name, and sector are resolved from SEC EDGAR."
        )
    else:
        # --- Company cards, sorted by composite risk descending ---
        _render_company_cards(computed, hist, landing)


def _render_company_cards(
    computed: list[CompanyResult],
    hist: HistoricalStore | None = None,
    landing: LandingReader | None = None,
) -> None:
    from ews_ingest.dashboard.ui import render_company_card

    sorted_results = sorted(computed, key=lambda x: -x[2])
    focus_ticker = st.session_state.pop("focus_company", None)
    scroll_key = f"scroll_done_{focus_ticker}" if focus_ticker else None
    if focus_ticker and scroll_key:
        st.session_state.setdefault(scroll_key, False)

    for company, results, composite, _flags in sorted_results:
        comp_status = _composite_status(composite)
        ticker = (company.ticker or "").upper()
        last = hist.get_last_update(ticker) if hist else None
        if not last and landing:
            last = landing.latest_fetched_at(
                ticker,
                name=company.identifiers.name if hasattr(company, "identifiers") else None,
                cik=company.identifiers.cik if hasattr(company, "identifiers") else None,
            )

        st.markdown('<div class="pb-company-row">', unsafe_allow_html=True)
        left, right = st.columns([0.98, 0.02], gap="small")
        with left:
            render_company_card(
                company.name,
                company.sector,
                company.ticker,
                composite,
                comp_status,
                ((p.indicator_id, p.label, p.description, r) for p, r in results),
                _collect_sources(results),
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
            ):
                with st.spinner(f"Refetching latest data for {ticker}..."):
                    st.session_state.setdefault("pending_refreshes", {})[ticker] = True
                    trigger_refresh(ticker, blocking=True)
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

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
    store: CompanyStore, suggest: TickerSuggest, current_tickers: set[str] | None = None
) -> None:
    """Add/remove widget using native Streamlit st.selectbox with filter_mode.

    Search is narrow (left corner). After selecting a ticker, shows either
    "Add to portfolio" or "Remove from portfolio" (single contextual button).
    Follows HSBC-inspired sizing (compact 14px/compact padding).
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
        "Add company",
        options=options,
        index=None,
        placeholder="Type ticker or name (fuzzy search)",
        filter_mode="fuzzy",
        label_visibility="collapsed",
        key="company_native_select",
        width=260,
    )

    ticker: str | None = None
    if selected:
        ticker = selected.split(" — ")[0].strip().upper()

    if ticker:
        is_present = ticker in current_tickers
        label = "- Remove" if is_present else "+ Add"
        btn_type = "secondary" if is_present else "primary"
        help_text = f"{'Remove' if is_present else 'Add'} {ticker} from portfolio"

        if st.button(
            label,
            type=btn_type,
            key="action_btn",
            use_container_width=False,
            help=help_text,
            width="content",
        ):
            if is_present:
                if store.remove_ticker(ticker):
                    bust_inputs_cache()
                    st.toast(f"Removed {ticker}", icon="🗑️")
                    st.rerun()
            else:
                try:
                    added = store.add_ticker(ticker)
                except TickerResolutionError as exc:
                    st.error(f"Could not resolve {ticker!r}: {exc}")
                else:
                    bust_inputs_cache()
                    st.session_state.setdefault("pending_refreshes", {})[added.ticker] = True
                    with st.spinner(f"Fetching data for {added.ticker} so it renders..."):
                        trigger_refresh(added.ticker, blocking=True)
                    sector_label = added.extra_ids.get("sector", "") or "(unknown)"
                    st.success(
                        f"Added {added.ticker} ({added.name}) — "
                        f"CIK={added.cik}, sector={sector_label}"
                    )
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    if __package__ in ("", None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
