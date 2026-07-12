"""Per-company and portfolio-level computation logic.

Pure-data module (no Streamlit imports) so the UI layer can type-check
without importing :mod:`ews_ingest.dashboard.app`. The companion module
:mod:`ews_ingest.dashboard.stats` holds the immutable dataclasses that
the functions in this module produce and consume.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ews_ingest.dashboard.companies import Company
from ews_ingest.dashboard.signals import SignalContext
from ews_ingest.dashboard.signals.protocol import SignalProvider, SignalResult
from ews_ingest.dashboard.stats import PortfolioStats, SectorStat

logger = logging.getLogger(__name__)

__all__ = [
    "CompanyResult",
    "ScoredStatus",
    "compute_company",
    "portfolio_stats",
]

# Scores that count toward the composite. Only real landed data;
# `demo` ("no data found") rows are now included (for new companies to show full list)
# composite so we never display a score derived from missing data.
ScoredStatus = str  # "good" | "warning" | "bad" | "demo"
_SCORED_STATUSES: frozenset[ScoredStatus] = frozenset({"good", "warning", "bad"})


# Tiles backed by landed data (used for the coverage KPI only).
_REAL_STATUSES: frozenset[ScoredStatus] = frozenset({"good", "warning", "bad"})

# Composite-score thresholds.
THR_GOOD = 35.0
THR_BAD = 65.0

# HHI concentration bands.
HHI_HIGH = 2500.0
HHI_MODERATE = 1500.0

# Sanctions indicator id (special: the raw value carries the flag count).
_SANCTIONS_INDICATOR = "geopolitical"

# News sentiment indicator id (special: the raw value is a signed string).
_SENTIMENT_INDICATOR = "news_sentiment"


# Per-company computation result: a 4-tuple shaped to match the legacy
# ``app._compute_company`` return type for back-compat.
CompanyResult = tuple[Company, list[tuple[SignalProvider, SignalResult]], float, int]


def composite_status(score: float) -> str:
    """Map a composite score to a status token."""
    if score < THR_GOOD:
        return "good"
    if score < THR_BAD:
        return "warning"
    return "bad"


def _parse_sanctions_flag(value: object) -> int:
    """Best-effort extract of the leading integer from a sanctions value string."""
    text = str(value)
    head = text.split(maxsplit=1)[0] if text else ""
    try:
        return int(head)
    except ValueError, IndexError:
        return 0


def _parse_sentiment(value: object) -> float | None:
    """Extract a signed float from a news-sentiment value string (``+3.2`` / ``-1.4``)."""
    try:
        return float(str(value).lstrip("+-"))
    except ValueError:
        return None


def compute_company(
    company: Company,
    providers: Iterable[SignalProvider],
    ctx: SignalContext,
) -> tuple[list[tuple[SignalProvider, SignalResult]], float, int]:
    """Run every provider against ``company`` and return ``(results, composite, flags)``.

    ``results`` preserves the provider order; ``composite`` is the mean of
    scored tiles (0.0 if none); ``flags`` is the leading-integer value of
    the sanctions provider's tile, or 0 when missing.
    """
    results: list[tuple[SignalProvider, SignalResult]] = []
    scores: list[float] = []
    flags = 0
    for provider in providers:
        result = provider.compute(company.identifiers, ctx)
        results.append((provider, result))
        logger.debug(
            "compute indicator %s for %s: status=%s score=%.1f value=%s note=%s",
            provider.indicator_id,
            company.ticker or company.identifiers.name,
            result.status,
            result.score,
            result.value,
            result.note,
        )
        if result.status in _SCORED_STATUSES:
            scores.append(result.score)
        if provider.indicator_id == _SANCTIONS_INDICATOR and result.status in _SCORED_STATUSES:
            flags = _parse_sanctions_flag(result.value)
    composite = sum(scores) / len(scores) if scores else 0.0
    logger.debug(
        "composite for %s = %.1f (scored %d / %d)",
        company.ticker,
        composite,
        len(scores),
        len(results),
    )
    return results, composite, flags


def portfolio_stats(
    computed: Iterable[CompanyResult],
) -> PortfolioStats:
    """Aggregate per-company results into cross-portfolio risk metrics."""
    rows = list(computed)
    n = max(len(rows), 1)
    all_scores = [sc for _co, _res, sc, _fl in rows]

    n_good, n_warning, n_bad = _score_buckets(all_scores)
    sectors, other_count, hhi, hhi_label = _sector_breakdown(rows, n)
    countries, n_distinct, top_country_share = _country_breakdown(rows, n)
    top_risk = _top_risk_borrowers(rows, k=3)
    worst_id, worst_mean, ind_labels = _worst_indicator(rows)
    total_flags = _total_sanctions_flags(rows)
    mean_sentiment = _mean_sentiment(rows)
    coverage = _data_coverage(rows)

    return PortfolioStats(
        n_companies=len(rows),
        mean_risk=sum(all_scores) / n,
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


def _score_buckets(scores: list[float]) -> tuple[int, int, int]:
    """Bucket composite scores into good / warning / bad counts."""
    n_good = sum(1 for sc in scores if sc < THR_GOOD)
    n_warning = sum(1 for sc in scores if THR_GOOD <= sc < THR_BAD)
    n_bad = sum(1 for sc in scores if sc >= THR_BAD)
    return n_good, n_warning, n_bad


def _sector_breakdown(
    rows: list[CompanyResult], n: int
) -> tuple[list[SectorStat], int, float, str]:
    """Aggregate per-sector counts + HHI, bucketing all-but-top-10 as "Other".

    Sectors are free-form strings from ``extra_ids["sector"]`` (Yahoo), so
    the set is open-ended. HHI uses the full open set so the concentration
    metric is accurate; display bucketing is capped at 10 sectors.
    """
    sec_counts: dict[str, int] = {}
    sec_scores: dict[str, list[float]] = {}
    for co, _res, sc, _fl in rows:
        sec_label = co.sector or "(unknown)"
        sec_counts[sec_label] = sec_counts.get(sec_label, 0) + 1
        sec_scores.setdefault(sec_label, []).append(sc)

    hhi = sum((c / n * 100) ** 2 for c in sec_counts.values())
    hhi_label = "high" if hhi > HHI_HIGH else "moderate" if hhi > HHI_MODERATE else "low"

    top = sorted(sec_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    other_count = sum(c for _, c in sec_counts.items()) - sum(c for _, c in top)
    top_labels = {s for s, _ in top}

    sectors: list[SectorStat] = [
        SectorStat(
            sector=sec_label,
            count=count,
            share_pct=count / n * 100,
            mean_risk=sum(sec_scores[sec_label]) / len(sec_scores[sec_label]),
        )
        for sec_label, count in top
    ]
    if other_count > 0:
        # Mean risk across the rolled-up bucket (still in the unrolled
        # ``sec_scores`` map — sum the contributions from non-top sectors).
        other_scores: list[float] = []
        for sec_label in sec_counts:
            if sec_label not in top_labels:
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

    return sectors, other_count, hhi, hhi_label


def _country_breakdown(rows: list[CompanyResult], n: int) -> tuple[dict[str, int], int, float]:
    """Per-country counts + top-country share."""
    countries: dict[str, int] = {}
    for co, _res, _sc, _fl in rows:
        ctry = str(co.identifiers.extra_ids.get("country", "Unknown"))
        countries[ctry] = countries.get(ctry, 0) + 1
    n_distinct = len(countries)
    top_country_share = max(countries.values()) / n * 100 if countries else 0.0
    return countries, n_distinct, top_country_share


def _top_risk_borrowers(rows: list[CompanyResult], *, k: int) -> list[tuple[str, float, str]]:
    """Top-``k`` borrowers by descending composite score."""
    return sorted(
        ((co.name, sc, co.sector) for co, _res, sc, _fl in rows),
        key=lambda x: -x[1],
    )[:k]


def _worst_indicator(
    rows: list[CompanyResult],
) -> tuple[str, float, dict[str, str]]:
    """Indicator with the highest mean score across the portfolio."""
    ind_scores: dict[str, list[float]] = {}
    ind_labels: dict[str, str] = {}
    for _co, res, _sc, _fl in rows:
        for p, r in res:
            if r.status in _SCORED_STATUSES:
                ind_scores.setdefault(p.indicator_id, []).append(r.score)
                ind_labels[p.indicator_id] = p.label
    worst_id = ""
    worst_mean = 0.0
    for iid, scs in ind_scores.items():
        mean = sum(scs) / len(scs)
        if mean > worst_mean:
            worst_mean = mean
            worst_id = iid
    return worst_id, worst_mean, ind_labels


def _total_sanctions_flags(rows: list[CompanyResult]) -> int:
    return sum(fl for *_rest, fl in rows)


def _mean_sentiment(rows: list[CompanyResult]) -> float | None:
    """Mean signed sentiment across the portfolio (None when no data)."""
    vals: list[float] = []
    for _co, res, _sc, _fl in rows:
        for p, r in res:
            if p.indicator_id == _SENTIMENT_INDICATOR and r.status in _SCORED_STATUSES:
                val = _parse_sentiment(r.value)
                if val is not None:
                    vals.append(val)
    return sum(vals) / len(vals) if vals else None


def _data_coverage(rows: list[CompanyResult]) -> float:
    """Percentage of tiles backed by landed (non-demo/"no data found") data."""
    total_real = sum(1 for _co, res, _s, _f in rows for _p, r in res if r.status in _REAL_STATUSES)
    total_tiles = sum(len(res) for _co, res, _s, _f in rows) or 1
    return total_real / total_tiles * 100
