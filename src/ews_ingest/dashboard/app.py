"""Streamlit entrypoint: ``streamlit run src/ews_ingest/dashboard/app.py``.

Renders the portfolio-risk dashboard. Reads the borrower universe from
``config/entities.yaml`` and the indicator bindings from
``config/indicators.yaml``. A portfolio-level overview panel aggregates
cross-borrower risk (concentration, exposure, distribution), then each company
renders as a collapsible card with a vertical list of risk indicators supplied
by auto-discovered :class:`SignalProvider` modules. The portfolio is
cross-region as a whole — one binding map applies to every borrower.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import streamlit as st

from ews_ingest.config import load_sources
from ews_ingest.dashboard.bindings import IndicatorBindings, load_bindings
from ews_ingest.dashboard.companies import Company, load_companies
from ews_ingest.dashboard.env import EnvResolver
from ews_ingest.dashboard.landing import LandingReader
from ews_ingest.dashboard.signals import SignalContext, list_providers
from ews_ingest.dashboard.signals.protocol import SignalProvider, SignalResult
from ews_ingest.dashboard.stats import PortfolioStats, SectorStat

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

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

    # sector aggregation + HHI
    sec_counts: dict[str, int] = {}
    sec_scores: dict[str, list[float]] = {}
    for co, _res, sc, _fl in computed:
        sec_counts[co.sector] = sec_counts.get(co.sector, 0) + 1
        sec_scores.setdefault(co.sector, []).append(sc)
    sectors = sorted(
        (
            SectorStat(
                sector=s,
                count=c,
                share_pct=c / n * 100,
                mean_risk=sum(sec_scores[s]) / len(sec_scores[s]),
            )
            for s, c in sec_counts.items()
        ),
        key=lambda x: -x.count,
    )
    hhi = sum((c / n * 100) ** 2 for c in sec_counts.values())
    hhi_label = "high" if hhi > _HHI_HIGH else "moderate" if hhi > _HHI_MODERATE else "low"

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


@lru_cache(maxsize=1)
def _cached_inputs() -> tuple[list[Company], LandingReader, EnvResolver]:
    companies = load_companies(CONFIG_DIR / "entities.yaml")
    landing_dir = Path(os.environ.get("EWS_LANDING_DIR", "./data/landing"))
    return companies, LandingReader(landing_dir), _make_env_resolver()


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
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    from ews_ingest.dashboard.ui import (
        inject_theme,
        render_company_card,
        render_portfolio_overview,
    )

    st.set_page_config(page_title="Portfolio Risk Dashboard", page_icon="📊", layout="wide")
    inject_theme()

    companies, landing, env = _cached_inputs()
    if not companies:
        st.warning("No companies found in entities.yaml. Seed the borrower universe first.")
        return

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

    # --- Header ---
    st.markdown(
        "<div style='font-size:1.6rem;font-weight:600;color:#fafafa;"
        "letter-spacing:-0.02em;margin-bottom:0.2rem'>Portfolio Risk</div>"
        "<div style='color:#52525b;font-size:0.82rem;margin-bottom:1.8rem'>"
        "Borrower-level risk indicators from the ingestion-layer landing zone."
        "</div>",
        unsafe_allow_html=True,
    )

    # --- Portfolio overview panel ---
    stats = _portfolio_stats(computed)
    render_portfolio_overview(stats)
    st.divider()

    # --- Company cards, sorted by composite risk descending ---
    computed.sort(key=lambda x: -x[2])
    for company, results, composite, _flags in computed:
        comp_status = _composite_status(composite)
        render_company_card(
            company.name,
            company.sector,
            company.ticker,
            composite,
            comp_status,
            ((p.indicator_id, p.label, p.description, r) for p, r in results),
            _collect_sources(results),
        )

    with st.expander("Methodology", expanded=False):
        st.markdown(
            """
**Indicators** are pluggable `SignalProvider` modules (auto-discovered under
`src/ews_ingest/dashboard/signals/`). Each declares *roles*, not source_ids.

**Role -> source_id** is bound portfolio-wide in `config/indicators.yaml`:

* swap a source for a category → re-point the role;
* add a new indicator → drop a file in `signals/` and add its role.

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


if __name__ == "__main__":
    if __package__ in ("", None):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
