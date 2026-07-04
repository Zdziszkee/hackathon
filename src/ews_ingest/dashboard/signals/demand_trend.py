"""Demand-trend indicator (sector-routed roles).

Airlines -> ``demand.air`` (BTS Air Travel Consumer Report).
Logistics / Transport -> ``demand.truck`` (ATA Truck Tonnage Index) +
``demand.freight_payments`` (Cass Freight via FRED).
Petrochemical -> ``demand.chem`` (EIA refinery utilization / fuel prices).

Trend = signed slope of the last N numeric points; normalized to a -10..+10
score where negative (falling demand) is higher risk.
"""

from __future__ import annotations

import contextlib
import re

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

_ROUTES = {
    "airlines": ["demand.air"],
    "transport_logistics": ["demand.truck", "demand.freight_payments"],
    "petrochemical": ["demand.chem"],
}
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numeric_points(payload: dict[str, object]) -> list[float]:
    """Best-effort extraction of a numeric series from a landed payload."""
    out: list[float] = []

    def walk(node: object) -> None:
        if isinstance(node, (int, float)):
            out.append(float(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            for m in _NUM_RE.findall(node):
                with contextlib.suppress(ValueError):
                    out.append(float(m))

    walk(payload)
    return out


def _slope(points: list[float]) -> float | None:
    if len(points) < 4:
        return None
    n = len(points)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(points) / n
    num = sum((xs[i] - mean_x) * (points[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n)) or 1.0
    return num / den


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    sector = str(company.extra_ids.get("sector", ""))
    roles = _ROUTES.get(sector, [])
    source_ids = tuple(filter(None, (ctx.source_for(r) for r in roles)))
    if not source_ids:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note=f"No demand source role bound for sector {sector!r} in this region.",
        )
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)

    all_points: list[float] = []
    missing_env: list[str] = []
    for sid in source_ids:
        if missing := ctx.missing_env(sid):
            missing_env.extend(missing)
            continue
        for payload in ctx.landing.iter_payloads(sid):
            all_points.extend(_numeric_points(payload))

    if missing_env and not all_points:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            missing_env=tuple(missing_env),
            source_ids=source_ids,
            note="API key(s) not configured — showing demo demand trend.",
        )
    if len(all_points) < 4:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            source_ids=source_ids,
            note="Not enough demand data points landed — showing demo trend.",
        )

    series = sorted(all_points)
    slope = _slope(series)
    if slope is None:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            source_ids=source_ids,
            note="Could not compute slope — showing demo trend.",
        )
    magnitude = abs(slope)
    trend_score = (slope / (magnitude + 1e-9)) * min(10.0, magnitude * 100.0)
    score = max(0.0, min(100.0, 50.0 - trend_score * 5.0))
    status = "good" if trend_score > 0 else "warning" if trend_score > -3 else "bad"
    return ok_result(
        value=rf"{trend_score:+.2f}",
        score=score,
        status=status,
        detail={"slope": round(slope, 6), "points": len(series)},
        source_ids=source_ids,
    )


def _matches_entity(__entities: list[Identifiers], __company: Identifiers) -> bool:
    return True  # demand is sector-level, not per-company


class _Provider:
    indicator_id = "demand_trend"
    label = "Demand Trend"

    description = "Sector-routed demand signal: airlines via BTS, trucking via ATA tonnage, petrochem via EIA."
    roles: tuple[str, ...] = tuple(r for rs in _ROUTES.values() for r in rs)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
