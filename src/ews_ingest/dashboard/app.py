"""Streamlit entrypoint: ``streamlit run src/ews_ingest/dashboard/app.py``.

Renders the portfolio-risk dashboard. The borrower universe is a dynamic JSON
store (see :mod:`ews_ingest.dashboard.company_store`) — users add companies by
ticker from the dashboard; the store resolves CIK/name/sector from SEC EDGAR
(landed ``universe.sec_company_tickers`` records first, then live lookup). The
legacy ``config/entities.yaml`` is migrated into the JSON store the first time
the dashboard boots. Indicator bindings come from ``config/indicators.yaml``.
A portfolio-level overview panel aggregates cross-borrower risk (concentration,
exposure, distribution), then each company renders as a collapsible card with a
vertical list of risk indicators supplied by auto-discovered
:class:`SignalProvider` modules. The portfolio is cross-region as a whole —
one binding map applies to every borrower.

Adding a ticker or clicking a per-card "Refresh" button schedules a
:class:`PortfolioOnboarding` task via ``loop.create_task`` (the
`asyncio-in-Streamlit pattern <https://sehmi-conscious.medium.com/got-that-asyncio-feeling-f1a7c37cab8b>`_);
the task lifecycle is tracked in ``st.session_state["onboarding_tasks"]`` and
polled via an :func:`st.fragment` with ``run_every=1s`` so the rest of the
page doesn't rerun on every tick.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.company_store import CompanyStore, TickerResolutionError
from ews_ingest.dashboard.compute import (
    CompanyResult,
    compute_company,
    portfolio_stats,
)
from ews_ingest.dashboard.compute import (
    composite_status as _composite_status,
)
from ews_ingest.dashboard.onboarding import (
    OnboardingTask,
    PortfolioOnboarding,
)
from ews_ingest.dashboard.services import (
    CONFIG_DIR,
    bust_inputs_cache,
    get_bindings,
    get_inputs,
    make_services_from_env,
    make_signal_ctx,
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


# ---------------------------------------------------------------------------
# Async onboarding (loop.create_task + st.session_state registry)
# ---------------------------------------------------------------------------


_SESSION_TASKS_KEY = "ews_onboarding_tasks"
_SESSION_TICKER = "ews_onboarding_ticker"
# Cap concurrent in-flight tasks (LRU). 32 is well above what a single
# dashboard session can reasonably queue; protects against unbounded growth
# if the user spam-clicks Add.
_MAX_IN_FLIGHT = 32

# How often the onboarding-status fragment polls the asyncio task state.
_POLL_INTERVAL = "1s"


def _ensure_session_tasks() -> dict[str, OnboardingTask]:
    """Return the per-session in-flight task registry (lazy-initialized)."""
    return st.session_state.setdefault(_SESSION_TASKS_KEY, {})  # type: ignore[return-value]


def _running_loop() -> asyncio.AbstractEventLoop:
    """Return a running asyncio event loop, creating one if absent.

    Streamlit's Tornado server already has a loop; we reuse it via
    ``asyncio.get_running_loop``. Outside Streamlit (tests) the
    :func:`asyncio.new_event_loop` fallback is used so the dashboard
    module remains importable without a running loop.
    """
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _on_refresh_clicked(identifiers: Identifiers) -> None:
    """``on_click`` callback for the per-card Refresh button.

    Schedules a background fetch and registers the task in
    ``st.session_state``. The button's own click event already triggers a
    rerun — no explicit ``st.rerun()`` needed here.
    """
    _schedule_onboarding(identifiers)


def _schedule_onboarding(identifier: Identifiers) -> OnboardingTask:
    """Schedule a background fetch for ``identifier`` and register it.

    Returns the :class:`OnboardingTask` immediately. The task runs in
    the background on the running event loop; the dashboard polls its
    status via :func:`_render_onboarding_panels_fragment` on every fragment tick.
    """
    services = make_services_from_env()
    onboarding = PortfolioOnboarding(services, http=services.http)

    task = OnboardingTask(
        task_id=uuid.uuid4().hex[:12],
        ticker=identifier.ticker or "?",
        sector=identifier.extra_ids.get("sector", ""),
        started_at=datetime.now(UTC),
    )

    async def _runner() -> None:
        completed = await onboarding.refresh_async(identifier)
        # Copy the completed-state fields onto the registered task so the
        # progress panel updates without a session_state re-key.
        task.sources_total = completed.sources_total
        task.sources_done = completed.sources_done
        task.sources_failed = completed.sources_failed
        task.sources_written = completed.sources_written
        task.status = completed.status
        task.error = completed.error
        task.sources_attempted = completed.sources_attempted
        task.sources_succeeded = completed.sources_succeeded
        task.sources_errored = completed.sources_errored
        task.finished_at = completed.finished_at
        # Force the next render to re-read the JSON store + landing zone.
        bust_inputs_cache()

    loop = _running_loop()
    loop.create_task(_runner())

    state = _ensure_session_tasks()
    ticker = (identifier.ticker or "").upper()
    # Keep the most recent task for this ticker. The earlier one's records
    # may still be landing; we don't cancel it explicitly (its coroutine
    # will complete and write to the landing zone idempotently).
    state[ticker] = task
    # LRU eviction: keep at most _MAX_IN_FLIGHT entries.
    if len(state) > _MAX_IN_FLIGHT:
        oldest = sorted(state.items(), key=lambda kv: kv[1].started_at)[0][0]
        del state[oldest]
    return task


@st.fragment(run_every=_POLL_INTERVAL)
def _render_onboarding_panels_fragment() -> None:
    """Render a status panel for every in-flight onboarding task.

    Runs inside an :func:`st.fragment` with ``run_every=1s`` so the rest
    of the page (header, KPIs, company list) doesn't rerun on every tick.
    The fragment is the only place that polls task state.
    """
    state = _ensure_session_tasks()
    for ticker, task in list(state.items()):
        progress = f"{task.sources_done + task.sources_failed}/{task.sources_total}"
        with st.status(
            f"Fetching {ticker} data ({progress})",
            state=("running" if task.status == "running" else "complete"),
            expanded=task.status == "running",
        ):
            st.progress(min(1.0, task.progress_fraction()))
            st.caption(
                f"elapsed: {task.elapsed_seconds():.1f}s · "
                f"ok: {task.sources_done} · failed: {task.sources_failed} · "
                f"records: {task.sources_written}"
            )
            if task.sources_attempted:
                st.caption("sources: " + ", ".join(task.sources_attempted))
            if task.status != "running":
                st.session_state[_SESSION_TICKER] = ticker


def _bust_onboarding_session() -> None:
    """Drop the per-session in-flight task registry (used on Remove)."""
    st.session_state.pop(_SESSION_TASKS_KEY, None)


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
# Legacy-entities bootstrap
# ---------------------------------------------------------------------------


def _ensure_company_store_bootstrap(store: CompanyStore) -> None:
    """One-time backfill: if the JSON store is empty, port the legacy
    ``entities.yaml`` seed into it. Idempotent."""
    legacy = CONFIG_DIR / "entities.yaml"
    if not legacy.exists():
        return
    if store.load():
        return
    seeded = store.seed_from_yaml(legacy)
    if seeded:
        st.toast(f"Seeded {seeded} companies from legacy entities.yaml.", icon="📥")


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
    _ensure_company_store_bootstrap(store)

    # --- Onboarding status panels (auto-polling fragment) ---
    _render_onboarding_panels_fragment()

    providers = list_providers()
    if not providers:
        st.error("No signal providers registered.")
        return

    ctx = make_signal_ctx(landing, env)
    _ = get_bindings()  # bindings are preloaded by ``make_signal_ctx``

    # --- Single centered column: no sidebar, no right rail ---
    render_topbar(len(companies))

    # --- Compute for every company once ---
    computed: list[CompanyResult] = [
        (company, *compute_company(company, providers, ctx)) for company in companies
    ]

    if not computed:
        st.info(
            "No companies yet. Add one above by ticker (e.g. `AAPL`, `MSFT`, "
            "`UPS`) — its CIK, name, and sector are resolved from SEC EDGAR."
        )
        return

    # --- Portfolio overview panel ---
    stats = portfolio_stats(computed)

    # --- Company correlation graph (placeholder hardcoded data) ---
    _render_correlation_graph(computed)

    render_portfolio_overview(stats)
    st.divider()

    # --- Add-company form (search bar at top of companies section) ---
    st.markdown(
        '<div class="pb-section-title">Companies'
        '<span class="pb-section-sub">add a ticker to monitor</span></div>',
        unsafe_allow_html=True,
    )
    _render_add_company_form(store, suggest)

    # --- Company cards, sorted by composite risk descending ---
    _render_company_cards(computed)


def _render_company_cards(computed: list[CompanyResult]) -> None:
    """Render the sorted list of company cards, each with a per-card Refresh button."""
    from ews_ingest.dashboard.ui import (
        render_company_card,  # local import: keep main() import-light
    )

    sorted_results = sorted(computed, key=lambda x: -x[2])
    in_flight = _ensure_session_tasks()
    for company, results, composite, _flags in sorted_results:
        comp_status = _composite_status(composite)
        ticker = (company.ticker or "").upper()
        is_refreshing = in_flight.get(ticker) is not None and (
            in_flight[ticker].status == "running"
        )
        st.markdown('<div class="pb-company">', unsafe_allow_html=True)
        card_col, btn_col = st.columns([1, 0.05], gap="small", vertical_alignment="top")
        with card_col:
            render_company_card(
                company.name,
                company.sector,
                company.ticker,
                composite,
                comp_status,
                ((p.indicator_id, p.label, p.description, r) for p, r in results),
                _collect_sources(results),
                anchor_id=ticker,
            )
        with btn_col:
            # ``on_click`` fires before the rerun — no explicit ``st.rerun()`` needed.
            st.button(
                "↻",
                key=f"ews_refresh_{ticker}",
                disabled=is_refreshing,
                help=(
                    "Re-fetch every eligible source for this company."
                    if not is_refreshing
                    else "A refresh is already in progress."
                ),
                on_click=_on_refresh_clicked,
                args=(company.identifiers,),
            )
        st.markdown("</div>", unsafe_allow_html=True)


def _render_add_company_form(store: CompanyStore, suggest: TickerSuggest) -> None:
    """Top-band form: ticker in -> resolved + persisted + cache busted.

    Autocomplete: as the user types, the top 5 matches from ``suggest``
    (live SEC lookup, cached in-memory) are rendered beneath the input
    field as a caption. Clicking a match (via the ``st_autocomplete``-style
    selectbox below the input) fills the field. The Add / Remove buttons
    are unchanged.

    Note: the form intentionally stays outside :func:`st.form` so the
    autocomplete selectbox can update on every keystroke (a form would
    batch the text input and freeze the suggestions until submit).
    """
    cols = st.columns([4, 1, 1, 6])
    with cols[0]:
        new_ticker = st.text_input(
            "Add company",
            placeholder="Ticker or company (e.g. AAPL, Apple, …)",
            label_visibility="collapsed",
            key="ews_add_company_ticker",
        )
    with cols[1]:
        submitted = st.button(
            "Add",
            type="primary",
            width="stretch",
            key="ews_add_company_submit",
        )
    with cols[2]:
        removed = st.button(
            "Remove",
            type="secondary",
            width="stretch",
            key="ews_remove_company_btn",
            help="Remove the currently-typed ticker from the portfolio.",
        )

    # Autocomplete: surface the top 5 matches as a selectbox that
    # pre-fills the text input. We catch and ignore any
    # failure from the live SEC lookup so the form keeps working offline.
    matches: list[Identifiers] = []
    if new_ticker and new_ticker.strip():
        try:
            matches = suggest.suggest(new_ticker, limit=5)
        except Exception as exc:
            st.caption(f"Autocomplete unavailable: {exc}")
            matches = []
        if matches:
            options = [f"{m.ticker} — {m.name}" if m.name else (m.ticker or "?") for m in matches]
            sel = st.selectbox(
                "Select suggestion to fill",
                options,
                index=None,
                placeholder="Select to auto-fill ticker field",
                label_visibility="collapsed",
                key="ticker_suggestion",
            )
            if sel:
                tkr = sel.split(" — ")[0].strip()
                if st.session_state.get("ews_add_company_ticker") != tkr:
                    st.session_state["ews_add_company_ticker"] = tkr
                    st.rerun()

    if submitted:
        ticker = (new_ticker or "").strip()
        if not ticker:
            st.warning("Enter a ticker to add.")
        else:
            try:
                added = store.add_ticker(ticker)
            except TickerResolutionError as exc:
                st.error(f"Could not resolve {ticker!r}: {exc}")
            else:
                bust_inputs_cache()
                # Kick off the per-ticker onboarding fetch in the
                # background. The status panel renders via
                # :func:`_render_onboarding_panels_fragment` from :func:`main`.
                _schedule_onboarding(added)
                sector_label = added.extra_ids.get("sector", "") or "(unknown)"
                st.success(
                    f"Added {added.ticker} ({added.name}) — "
                    f"CIK={added.cik}, sector={sector_label}. "
                    "Auto-fetching data in the background…"
                )
                st.rerun()

    if removed:
        ticker = (new_ticker or "").strip()
        if not ticker:
            st.warning("Enter a ticker to remove.")
        elif store.remove_ticker(ticker):
            bust_inputs_cache()
            _bust_onboarding_session()
            st.toast(f"Removed {ticker.upper()} from the portfolio.", icon="🗑️")
            st.rerun()
        else:
            st.warning(f"{ticker.upper()} is not in the portfolio.")


if __name__ == "__main__":
    if __package__ in ("", None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
