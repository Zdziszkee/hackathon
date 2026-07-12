"""Credit-market stress indicator (role: ``credit.spreads``).

Reads FRED ICE BAML corporate-bond option-adjusted spreads (HY OAS, IG BBB,
AAA, BAA) from the ``credit_market.fred_credit`` landing zone. The HY OAS
series is the headline: above-trend = stress environment, below = benign.

Score: the recent z-score of the HY OAS series, mapped to 0..100 risk.
Same value for every company (macro overlay), by design.
"""

from __future__ import annotations

from collections.abc import Iterable

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    cast_status,
    demo_result,
    ok_result,
    register_provider,
)

__all__ = ["Provider", "compute"]

ROLE = "credit.spreads"

# FRED series IDs we care about; HY OAS is the headline.
_HY_OAS = "BAMLH0A0HYM2"
_SPREAD_SERIES_IDS = frozenset({_HY_OAS, "BAMLC0A4CBBB", "BAA", "AAA"})


def _read_series_points(records: Iterable[object], series_id: str) -> list[tuple[str, float]]:
    """Extract (date, value) pairs for a FRED series from RawRecord list."""
    out: list[tuple[str, float]] = []
    for rec in records:
        extra = getattr(rec, "extra", None)
        if not isinstance(extra, dict) or extra.get("series_id") != series_id:
            continue
        payload = getattr(rec, "payload", None)
        if not isinstance(payload, dict):
            continue
        for row in payload.get("observations", []) or []:
            if not isinstance(row, dict):
                continue
            v = row.get("value")
            date = str(row.get("date") or "")
            if isinstance(v, (int, float)):
                out.append((date, float(v)))
            elif isinstance(v, str) and v not in {"", ".", "nan", "NaN"}:
                try:
                    out.append((date, float(v)))
                except ValueError:
                    continue
    out.sort(key=lambda x: x[0])
    return out


def _zscore(series: list[float]) -> float | None:
    if len(series) < 30:
        return None
    mean = sum(series) / len(series)
    var = sum((x - mean) ** 2 for x in series) / (len(series) - 1)
    if var <= 0:
        return 0.0
    return (series[-1] - mean) / var**0.5


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No credit-spread source bound for this portfolio.",
        )
    if miss := ctx.missing_env(source_id):
        return demo_result(
            label_hint="credit_spreads",
            value=f"HY {demo.gscpi():+.2f}",
            score=50.0 + demo.gscpi() * 20.0,
            missing_env=tuple(miss),
            source_ids=(source_id,),
            note="API key not configured — no data found.",
        )
    records = ctx.landing.read(source_id).records
    points = _read_series_points(records, _HY_OAS)
    series = [v for _, v in points]
    z = _zscore(series)
    last = series[-1] if series else None
    if z is None or last is None:
        return demo_result(
            label_hint="credit_spreads",
            value=f"HY {demo.gscpi():+.2f}",
            score=50.0 + demo.gscpi() * 20.0,
            source_ids=(source_id,),
            note="Not enough HY OAS points landed — no data found.",
        )
    risk = max(0.0, min(100.0, 50.0 + z * 25.0))
    status = "good" if risk < 40 else "warning" if risk < 70 else "bad"
    return ok_result(
        value=f"HY {last:.2f}",
        score=risk,
        status=status,
        detail={"hy_oas_last": last, "hy_oas_z": round(z, 3), "points": len(series)},
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "credit_spreads"
    label = "Credit Spreads"

    description = (
        "ICE BAML High-Yield Option-Adjusted Spread (FRED BAMLH0A0HYM2). "
        "Higher = market-priced default risk. Same value for every company."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
