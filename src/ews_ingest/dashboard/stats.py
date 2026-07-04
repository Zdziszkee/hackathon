"""Portfolio-level aggregated risk metrics (shared between app + UI).

Pure-data module so the UI layer can type-check without importing app.py
(which would create a circular dependency — app imports ui).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["PortfolioStats", "SectorStat"]


@dataclass(frozen=True)
class SectorStat:
    """Aggregated risk for one sector."""

    sector: str
    count: int
    share_pct: float
    mean_risk: float


@dataclass(frozen=True)
class PortfolioStats:
    """Cross-borrower aggregated risk metrics shown in the overview panel."""

    n_companies: int
    mean_risk: float
    n_good: int
    n_warning: int
    n_bad: int
    sectors: list[SectorStat] = field(default_factory=list)
    hhi: float = 0.0
    hhi_label: str = "low"
    countries: dict[str, int] = field(default_factory=dict)
    country_concentration_pct: float = 0.0
    n_distinct_countries: int = 0
    top_risk: list[tuple[str, float, str]] = field(default_factory=list)
    worst_indicator_id: str = ""
    worst_indicator_label: str = ""
    worst_indicator_mean: float = 0.0
    total_sanctions_flags: int = 0
    mean_sentiment: float | None = None
    data_coverage_pct: float = 0.0
