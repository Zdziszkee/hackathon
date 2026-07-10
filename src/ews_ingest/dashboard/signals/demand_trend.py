"""General economic demand indicator.

Renders a single universal demand series (the NY Fed Weekly Economic
Index, or a similar activity proxy) for every company. Sector routing
was removed with the sector vocabulary — every company gets the same
"is the economy expanding or contracting?" signal.

Trend = signed slope of the last N numeric points; normalized to a
-10..+10 score where negative (falling demand) is higher risk.
"""

from __future__ import annotations

import contextlib

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


ROLE = "macro.mfg_pmi"

# Universal economic demand proxy: the FRED INDPRO (Industrial
# Production Index) series. The signal runs the same series for
# every company — the result represents the macro environment, not a
# per-company demand curve. Sources are looked up via
# ``config/indicators.yaml`` under the ``macro.mfg_pmi`` role (the
# closest existing role; rename in YAML if a dedicated role is added).
_VALUE_KEYS = ("value", "Value")
_OBS_KEYS = ("observations", "data")


def _numeric_points(payload: dict[str, object]) -> list[float]:
    """Extract a numeric demand series from a *structured* landed payload."""
    out: list[float] = []
    candidates: list[object] = []
    for obs_key in _OBS_KEYS:
        v = payload.get(obs_key)
        if isinstance(v, list):
            candidates.extend(v)
    for row in candidates:
        if not isinstance(row, dict):
            continue
        for key in _VALUE_KEYS:
            value = row.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                out.append(float(value))
                break
            if isinstance(value, str) and value not in {"", ".", "nan", "NaN", "null"}:
                with contextlib.suppress(ValueError):
                    out.append(float(value))
                break
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
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return demo_result(
            label_hint="general_demand",
            value=f"{demo.demand_trend():+.2f}",
            score=50.0,
            source_ids=(),
            note="No source bound — showing demo.",
        )

    missing_env: list[str] = []
    if miss := ctx.missing_env(source_id):
        missing_env.extend(miss)

    points: list[float] = []
    if not missing_env:
        for payload in ctx.landing.iter_payloads(source_id):
            points.extend(_numeric_points(payload))

    if missing_env and not points:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            missing_env=tuple(missing_env),
            source_ids=(source_id,),
            note="API key(s) not configured — showing demo demand trend.",
        )
    if len(points) < 4:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            source_ids=(source_id,),
            note="Not enough demand data points landed — showing demo trend.",
        )

    slope = _slope(points)
    if slope is None:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            source_ids=(source_id,),
            note="Could not compute slope — showing demo trend.",
        )
    magnitude = abs(slope)
    trend_score = (slope / (magnitude + 1e-9)) * min(10.0, magnitude * 100.0)
    score = max(0.0, min(100.0, 50.0 - trend_score * 5.0))
    status = "good" if trend_score > 0 else "warning" if trend_score > -3 else "bad"
    return ok_result(
        value=rf"{trend_score:+.2f}",
        score=score,
        status=cast_status(status),
        detail={"slope": round(slope, 6), "points": len(points)},
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "general_demand"
    label = "General Demand"

    description = (
        "General economic demand trend (FRED INDPRO proxy). The same "
        "series is shown for every company — the signal represents the "
        "macro environment, not a per-company demand curve."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
