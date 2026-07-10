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
the task lifecycle is tracked in ``st.session_state["onboarding_tasks"]``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import streamlit as st

from ews_ingest.config import Services, load_sources, make_services
from ews_ingest.core.http import HttpClient
from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.bindings import IndicatorBindings, load_bindings
from ews_ingest.dashboard.companies import Company, load_companies
from ews_ingest.dashboard.company_store import CompanyStore, TickerResolutionError
from ews_ingest.dashboard.env import EnvResolver
from ews_ingest.dashboard.landing import LandingReader
from ews_ingest.dashboard.onboarding import (
    OnboardingTask,
    PortfolioOnboarding,
)
from ews_ingest.dashboard.signals import SignalContext, list_providers
from ews_ingest.dashboard.signals.protocol import SignalProvider, SignalResult
from ews_ingest.dashboard.stats import PortfolioStats, SectorStat
from ews_ingest.dashboard.ticker_suggest import SecLiveTickerSuggest, TickerSuggest
from ews_ingest.dashboard.yahoo_sector import (
    SecLiveYahooSector,
    SectorLookup,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
LEGACY_ENTITIES_YAML = CONFIG_DIR / "entities.yaml"

_THR_GOOD = 35.0
_THR_BAD = 65.0
# Scores that count toward the composite. `demo` is a deterministic estimate
# (worth counting when no real data has landed); only `unavailable` is excluded.
_SCORED_STATUSES = {"good", "warning", "bad", "demo"}
# Tiles backed by landed data (used for the coverage KPI only).
_REAL_STATUSES = {"good", "warning", "bad"}
_HHI_HIGH = 2500.0
_HHI_MODERATE = 1500.0


def _composite_status(score: float) -> str:
    if score < _THR_GOOD:
        return "good"
    if score < _THR_BAD:
        return "warning"
    return "bad"


def _compute_company(
    company: Company,
    providers: list[SignalProvider],
    ctx: SignalContext,
) -> tuple[list[tuple[SignalProvider, SignalResult]], float, int]:
    results: list[tuple[SignalProvider, SignalResult]] = []
    scores: list[float] = []
    flags = 0
    for provider in providers:
        result = provider.compute(company.identifiers, ctx)
        results.append((provider, result))
        if result.status in _SCORED_STATUSES:
            scores.append(result.score)
        if provider.indicator_id == "geopolitical" and result.status in _SCORED_STATUSES:
            try:
                flags = int(str(result.value).split()[0])
            except ValueError, IndexError:
                flags = 0
    composite = sum(scores) / len(scores) if scores else 0.0
    return results, composite, flags


def _portfolio_stats(
    computed: list[tuple[Company, list[tuple[SignalProvider, SignalResult]], float, int]],
) -> PortfolioStats:
    """Aggregate per-company results into cross-portfolio risk metrics."""
    n = len(computed) or 1
    all_scores = [sc for _co, _res, sc, _fl in computed]
    mean_risk = sum(all_scores) / n

    n_good = sum(1 for sc in all_scores if sc < _THR_GOOD)
    n_warning = sum(1 for sc in all_scores if _THR_GOOD <= sc < _THR_BAD)
    n_bad = sum(1 for sc in all_scores if sc >= _THR_BAD)

    # sector aggregation + HHI. Sectors are free-form strings from
    # ``extra_ids["sector"]`` (Yahoo), so the set is open-ended. We
    # show the top 10 individually and roll the rest into an
    # "Other" bucket.
    sec_counts: dict[str, int] = {}
    sec_scores: dict[str, list[float]] = {}
    for co, _res, sc, _fl in computed:
        sec_label = co.sector or "(unknown)"
        sec_counts[sec_label] = sec_counts.get(sec_label, 0) + 1
        sec_scores.setdefault(sec_label, []).append(sc)
    # HHI uses the full open set so the concentration metric is accurate.
    hhi = sum((c / n * 100) ** 2 for c in sec_counts.values())
    hhi_label = "high" if hhi > _HHI_HIGH else "moderate" if hhi > _HHI_MODERATE else "low"

    # Display bucketing: top 10 by count, rest rolled into "Other".
    top = sorted(sec_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    other_count = sum(c for _, c in sec_counts.items()) - sum(c for _, c in top)
    sectors: list[SectorStat] = []
    for sec_label, count in top:
        sectors.append(
            SectorStat(
                sector=sec_label,
                count=count,
                share_pct=count / n * 100,
                mean_risk=sum(sec_scores[sec_label]) / len(sec_scores[sec_label]),
            )
        )
    if other_count > 0:
        # Mean risk across the rolled-up bucket (still in the unrolled
        # ``sec_scores`` map — sum the contributions from non-top sectors).
        other_scores: list[float] = []
        for sec_label, _count in sec_counts.items():
            if sec_label not in {s for s, _ in top}:
                other_scores.extend(sec_scores[sec_label])
        mean_risk_other = sum(other_scores) / len(other_scores) if other_scores else 0.0
        sectors.append(
            SectorStat(
                sector="Other",
                count=other_count,
                share_pct=other_count / n * 100,
                mean_risk=mean_risk_other,
            )
        )

    # country concentration
    countries: dict[str, int] = {}
    for co, _res, _sc, _fl in computed:
        ctry = str(co.identifiers.extra_ids.get("country", "Unknown"))
        countries[ctry] = countries.get(ctry, 0) + 1
    n_distinct = len(countries)
    top_country_share = max(countries.values()) / n * 100 if countries else 0.0

    # top 3 risk borrowers
    top_risk = sorted(
        ((co.name, sc, co.sector) for co, _res, sc, _fl in computed),
        key=lambda x: -x[1],
    )[:3]

    # worst indicator (highest mean score across portfolio)
    ind_scores: dict[str, list[float]] = {}
    ind_labels: dict[str, str] = {}
    for _co, res, _sc, _fl in computed:
        for p, r in res:
            if r.status in _SCORED_STATUSES:
                ind_scores.setdefault(p.indicator_id, []).append(r.score)
                ind_labels[p.indicator_id] = p.label
    worst_id = ""
    worst_mean = 0.0
    for iid, scs in ind_scores.items():
        m = sum(scs) / len(scs)
        if m > worst_mean:
            worst_mean = m
            worst_id = iid

    # sanctions flags
    total_flags = sum(fl for *_, fl in computed)

    # mean sentiment
    sent_vals: list[float] = []
    for _co, res, _sc, _fl in computed:
        for p, r in res:
            if p.indicator_id == "news_sentiment" and r.status in _SCORED_STATUSES:
                with contextlib.suppress(ValueError):
                    sent_vals.append(float(str(r.value).lstrip("+-")))
    mean_sentiment = sum(sent_vals) / len(sent_vals) if sent_vals else None

    # data coverage
    total_real = sum(
        1 for _co, res, _s, _f in computed for _p, r in res if r.status in _REAL_STATUSES
    )
    total_tiles = sum(len(res) for _co, res, _s, _f in computed) or 1
    coverage = total_real / total_tiles * 100

    return PortfolioStats(
        n_companies=len(computed),
        mean_risk=mean_risk,
        n_good=n_good,
        n_warning=n_warning,
        n_bad=n_bad,
        sectors=sectors,
        sector_other_count=other_count,
        hhi=hhi,
        hhi_label=hhi_label,
        countries=countries,
        country_concentration_pct=top_country_share,
        n_distinct_countries=n_distinct,
        top_risk=top_risk,
        worst_indicator_id=worst_id,
        worst_indicator_label=ind_labels.get(worst_id, ""),
        worst_indicator_mean=worst_mean,
        total_sanctions_flags=total_flags,
        mean_sentiment=mean_sentiment,
        data_coverage_pct=coverage,
    )


# ---------------------------------------------------------------------------
# Service wiring
# ---------------------------------------------------------------------------


def _make_env_resolver() -> EnvResolver:
    sources = load_sources(CONFIG_DIR / "sources.yaml")
    required = {sid: tuple(cfg.env_required) for sid, cfg in sources.items()}
    return EnvResolver.from_required_map(required)


def _companies_path() -> Path:
    """Resolve the dynamic JSON company-store path (env-overridable)."""
    return Path(
        os.environ.get(
            "EWS_COMPANIES_PATH",
            Path(os.environ.get("EWS_COMPANIES_DIR", "./data/companies")) / "companies.json",
        )
    )


def _landing_lookup_factory(landing: LandingReader) -> Callable[[str], list[dict[str, object]]]:
    """Adapter: ``source_id -> list[{"payload":..., "entities":[...]}]``.

    Lets :class:`CompanyStore` resolve tickers/SICs from landed JSONL without
    taking a direct dependency on :mod:`ews_ingest.dashboard.landing`.
    """

    def _lookup(source_id: str) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for rec in landing.read(source_id).records:
            out.append(
                {
                    **dict(rec.payload),
                    "entities": [e.model_dump(mode="json") for e in rec.entities],
                }
            )
        return out

    return _lookup


def _ensure_company_store_bootstrap(store: CompanyStore) -> None:
    """One-time backfill: if the JSON store is empty, port the legacy
    ``entities.yaml`` seed into it. Idempotent."""
    if not LEGACY_ENTITIES_YAML.exists():
        return
    if store.load():
        return
    seeded = store.seed_from_yaml(LEGACY_ENTITIES_YAML)
    if seeded:
        st.toast(f"Seeded {seeded} companies from legacy entities.yaml.", icon="📥")


def _new_http_client() -> HttpClient:
    return HttpClient(sec_user_agent=os.environ.get("SEC_USER_AGENT"))


def _new_company_store(
    landing: LandingReader,
    http: HttpClient | None = None,
    sector_lookup: SectorLookup | None = None,
) -> CompanyStore:
    # An HttpClient is only needed for live SEC ticker/SIC enrichment fallback.
    # We construct one lazily so the dashboard still boots if SEC_USER_AGENT is
    # unset (resolution then falls back to landed data + final SEC lookup uses
    # the client's default agent).
    if http is None:
        http = _new_http_client()
    return CompanyStore(
        _companies_path(),
        http=http,
        landing_lookup=_landing_lookup_factory(landing),
        sector_lookup=sector_lookup,
    )


def _new_ticker_suggest(http: HttpClient | None = None) -> TickerSuggest:
    if http is None:
        http = _new_http_client()
    return SecLiveTickerSuggest(http)


def _new_sector_lookup(http: HttpClient | None = None) -> SectorLookup:
    if http is None:
        http = _new_http_client()
    return SecLiveYahooSector(http)


def _new_services(landing_dir: Path) -> Services:
    """Build a :class:`Services` bundle rooted at ``landing_dir``.

    Used by the onboarding orchestrator — the rest of the dashboard uses
    the smaller DI pair (``_new_http_client`` etc.) because the
    :class:`CompanyStore` and ticker suggester don't need the full bundle.
    """
    from ews_ingest.cli import _default_entities_path

    return make_services(
        landing_dir=landing_dir,
        entities_path=_default_entities_path(),
        sources_path=CONFIG_DIR / "sources.yaml",
        sec_user_agent=os.environ.get("SEC_USER_AGENT"),
    )


@lru_cache(maxsize=1)
def _cached_inputs() -> tuple[
    list[Company], LandingReader, EnvResolver, CompanyStore, TickerSuggest
]:
    landing_dir = Path(os.environ.get("EWS_LANDING_DIR", "./data/landing"))
    landing = LandingReader(landing_dir)
    http = _new_http_client()
    sector_lookup = _new_sector_lookup(http=http)
    store = _new_company_store(landing, http=http, sector_lookup=sector_lookup)
    _ensure_company_store_bootstrap(store)
    suggest = _new_ticker_suggest(http=http)
    companies = load_companies(store.path)
    return companies, landing, _make_env_resolver(), store, suggest


def _bust_inputs_cache() -> None:
    """Force :func:`_cached_inputs` to re-read the JSON store on next render."""
    _cached_inputs.cache_clear()


@lru_cache(maxsize=1)
def _cached_bindings() -> IndicatorBindings:
    return load_bindings(CONFIG_DIR / "indicators.yaml")


def _signal_ctx(landing: LandingReader, env: EnvResolver) -> SignalContext:
    is_present: Callable[[str], bool] = env.is_present
    missing: Callable[[str], list[str]] = env.missing_for
    return SignalContext(
        bindings=_cached_bindings(),
        landing=landing,
        env_present=is_present,
        missing_env=missing,
    )


def _collect_sources(
    results: list[tuple[SignalProvider, SignalResult]],
) -> list[str]:
    seen: set[str] = set()
    for _provider, result in results:
        for sid in result.source_ids:
            if sid and sid not in seen:
                seen.add(sid)
    return sorted(seen)


# ---------------------------------------------------------------------------
# Async onboarding (loop.create_task + st.session_state registry)
# ---------------------------------------------------------------------------


_SESSION_TASKS_KEY = "ews_onboarding_tasks"
_SESSION_TICKER = "ews_onboarding_ticker"
# Cap concurrent in-flight tasks (LRU). 32 is well above what a single
# dashboard session can reasonably queue; protects against unbounded growth
# if the user spam-clicks Add.
_MAX_IN_FLIGHT = 32


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


def _schedule_onboarding(identifier: Identifiers) -> OnboardingTask:
    """Schedule a background fetch for ``identifier`` and register it.

    Returns the :class:`OnboardingTask` immediately. The task runs in
    the background on the running event loop; the dashboard polls its
    status via :func:`_render_onboarding_panels` on every rerun.
    """
    landing_dir = Path(os.environ.get("EWS_LANDING_DIR", "./data/landing"))
    services = _new_services(landing_dir)
    onboarding = PortfolioOnboarding(services, http=services.http)

    task = OnboardingTask(
        task_id=__import__("uuid").uuid4().hex[:12],
        ticker=identifier.ticker or "?",
        sector=identifier.extra_ids.get("sector", ""),
        started_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
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
        _bust_inputs_cache()

    loop = _running_loop()
    loop.create_task(_runner())

    state = _ensure_session_tasks()
    ticker = (identifier.ticker or "").upper()
    if ticker in state:
        # A previous in-flight task for the same ticker — keep the most
        # recent. The earlier one's records may still be landing; we don't
        # cancel it explicitly (its coroutine will complete and write to
        # the landing zone idempotently).
        pass
    state[ticker] = task
    # LRU eviction: keep at most _MAX_IN_FLIGHT entries.
    if len(state) > _MAX_IN_FLIGHT:
        oldest = sorted(state.items(), key=lambda kv: kv[1].started_at)[0][0]
        del state[oldest]
    return task


def _render_onboarding_panels() -> bool:
    """Render a status panel for every in-flight onboarding task.

    Returns True if any task is still running (the caller should
    ``st.rerun()`` to keep polling); False when the queue is empty or
    every task is in a terminal state (the caller can stop polling).
    """
    state = _ensure_session_tasks()
    if not state:
        return False
    any_running = False
    for ticker, task in list(state.items()):
        progress = f"{task.sources_done + task.sources_failed}/{task.sources_total}"
        with st.status(
            f"Fetching {ticker} data ({progress})",
            state=("running" if task.status == "running" else "complete"),
            expanded=task.status == "running",
        ):
            bar_value = task.progress_fraction()
            st.progress(min(1.0, bar_value))
            st.caption(
                f"elapsed: {task.elapsed_seconds():.1f}s · "
                f"ok: {task.sources_done} · failed: {task.sources_failed} · "
                f"records: {task.sources_written}"
            )
            if task.sources_attempted:
                st.caption("sources: " + ", ".join(task.sources_attempted))
            if task.status == "running":
                any_running = True
            else:
                st.session_state[_SESSION_TICKER] = ticker
    return any_running


def _bust_onboarding_session() -> None:
    """Drop the per-session in-flight task registry (used on Remove)."""
    st.session_state.pop(_SESSION_TASKS_KEY, None)


def _render_correlation_graph(
    computed: list[tuple[Company, list[tuple[SignalProvider, SignalResult]], float, int]],
) -> None:
    """Build placeholder company-correlation data and render the graph.

    Companies become nodes (colored by risk status). Correlation edges are
    derived from shared sector (strong) and proximity of composite score
    (moderate). This is a placeholder — swap with real causality data later.
    """
    companies_graph: list[tuple[str, float, str, str]] = []
    for co, _res, composite, _flags in computed:
        status = _composite_status(composite)
        companies_graph.append((co.name, composite, co.sector or "Unknown", status))

    # Placeholder correlations: same-sector pairs get high strength,
    # score-proximity (< 10 apart) gets moderate. Cap at ~30 edges.
    correlations: list[tuple[str, str, float]] = []
    n = len(companies_graph)
    for i in range(n):
        for j in range(i + 1, n):
            name_i, score_i, sec_i, _ = companies_graph[i]
            name_j, score_j, sec_j, _ = companies_graph[j]
            if sec_i == sec_j and sec_i != "Unknown":
                correlations.append((name_i, name_j, 0.75))
            elif abs(score_i - score_j) < 10:
                correlations.append((name_i, name_j, 0.35))
    correlations = correlations[:30]

    from ews_ingest.dashboard.ui import render_correlation_graph

    render_correlation_graph(companies_graph, correlations)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    from ews_ingest.dashboard.ui import (
        inject_theme,
        render_company_card,
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

    companies, landing, env, store, suggest = _cached_inputs()

    # --- Single centered column: no sidebar, no right rail ---
    render_topbar(len(companies))

    # --- Onboarding status panels (one per in-flight task) ---
    any_running = _render_onboarding_panels()

    providers = list_providers()
    if not providers:
        st.error("No signal providers registered.")
        return

    ctx = _signal_ctx(landing, env)

    # --- Compute for every company once ---
    computed: list[tuple[Company, list[tuple[SignalProvider, SignalResult]], float, int]] = []
    for company in companies:
        results, composite, flags = _compute_company(company, providers, ctx)
        computed.append((company, results, composite, flags))

    if not computed:
        st.info(
            "No companies yet. Add one above by ticker (e.g. `AAPL`, `MSFT`, "
            "`UPS`) — its CIK, name, and sector are resolved from SEC EDGAR."
        )
        return

    # --- Portfolio overview panel ---
    stats = _portfolio_stats(computed)

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
    computed.sort(key=lambda x: -x[2])
    in_flight = _ensure_session_tasks()
    for company, results, composite, _flags in computed:
        comp_status = _composite_status(composite)
        ticker = (company.ticker or "").upper()
        is_refreshing = in_flight.get(ticker) is not None and (
            in_flight[ticker].status == "running"
        )
        st.markdown('<div class="pb-company">', unsafe_allow_html=True)
        if st.button(
            "↻",
            key=f"ews_refresh_{ticker}",
            disabled=is_refreshing,
            help=(
                "Re-fetch every eligible source for this company."
                if not is_refreshing
                else "A refresh is already in progress."
            ),
        ):
            _schedule_onboarding(company.identifiers)
            st.rerun()
        render_company_card(
            company.name,
            company.sector,
            company.ticker,
            composite,
            comp_status,
            ((p.indicator_id, p.label, p.description, r) for p, r in results),
            _collect_sources(results),
        )
        st.markdown("</div>", unsafe_allow_html=True)

    # --- Methodology ---
    with st.expander("Methodology", expanded=False):
        st.markdown(
            """
**Indicators** are pluggable `SignalProvider` modules (auto-discovered under
`src/ews_ingest/dashboard/signals/`). Each declares *roles*, not source_ids.

**Role -> source_id** is bound portfolio-wide in `config/indicators.yaml`:

* swap a source for a category → re-point the role;
* add a new indicator → drop a file in `signals/` and add its role.

**Companies** are stored in `data/companies/companies.json` (editable from
this dashboard). Add one by ticker; CIK + legal name + sector are resolved
live from SEC EDGAR and persisted.

**Data** comes from the ingestion-layer landing zone (`data/landing/`),
keyed by `source_id`. When a source has not landed data yet, indicators show
a clearly-labeled deterministic demo value (seeded from the company name),
replaced automatically once you run ingestion.

**Sentiment** uses GDELT's precomputed `tone` field — no NLP dependency.

**Policy & regulation stability** is a proxy: count of GDELT distress
articles for the company whose titles match regulation/policy keywords.
No source literally tracks regulatory changes; this is the closest
existing-source proxy.

**Supply chain** blends the NY Fed GSCPI (z-score) with ISM New Orders &
Supplier Deliveries sub-indices parsed out of the landed PMI page text.

**Volatility** is the annualized realized volatility of daily log returns
from Yahoo Finance OHLCV (trailing 60 trading days).
"""
        )

    # Keep polling while tasks are in flight.
    if any_running:
        import time

        time.sleep(1.0)
        st.rerun()


def _render_add_company_form(store: CompanyStore, suggest: TickerSuggest) -> None:
    """Top-band form: ticker in -> resolved + persisted + cache busted.

    Autocomplete: as the user types, the top 5 matches from ``suggest``
    (live SEC lookup, cached in-memory) are rendered beneath the input
    field as a caption. Clicking a match (via the ``st_autocomplete``-style
    selectbox below the input) fills the field. The Add / Remove buttons
    are unchanged.
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
            use_container_width=True,
            key="ews_add_company_submit",
        )
    with cols[2]:
        removed = st.button(
            "Remove",
            type="secondary",
            use_container_width=True,
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
                _bust_inputs_cache()
                # Kick off the per-ticker onboarding fetch in the
                # background. The status panel renders via
                # :func:`_render_onboarding_panels` from :func:`main`.
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
            _bust_inputs_cache()
            _bust_onboarding_session()
            st.toast(f"Removed {ticker.upper()} from the portfolio.", icon="🗑️")
            st.rerun()
        else:
            st.warning(f"{ticker.upper()} is not in the portfolio.")


if __name__ == "__main__":
    if __package__ in ("", None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
