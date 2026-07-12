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


ROLE = "macro.demand_trend"

# Universal economic demand proxy: the FRED INDPRO (Industrial
# Production Index) series. The signal runs the same series for
# every company — the result represents the macro environment, not a
# per-company demand curve. Sources are looked up via
# ``config/indicators.yaml`` under the ``macro.demand_trend`` role,
# which is bound to ``macro.fred_macro`` (INDPRO + TCU series).
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


# FRED series IDs we treat as "demand" for this signal. macro.fred_macro
# emits multiple series per run (yields + INDPRO + TCU + TRUCKD11); we
# restrict to industrial production (INDPRO) so the slope reflects real
# activity on a single consistent scale (index ~100) rather than a mixed
# unit soup with TCU's percentage scale.
_DEMAND_SERIES_IDS = frozenset({"INDPRO"})


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
            note="No source bound — no data found.",
        )

    missing_env: list[str] = []
    if miss := ctx.missing_env(source_id):
        missing_env.extend(miss)

    points: list[float] = []
    if not missing_env:
        # macro.fred_macro emits multiple series per run (yields + INDPRO +
        # TCU + TRUCKD11). Restrict to demand series so the slope reflects
        # real activity, not a mixed-unit soup. iter_payloads yields only
        # the payload dict, so go through ``read`` to access ``extra.series_id``.
        for rec in ctx.landing.read(source_id).records:
            extra_obj: object = getattr(rec, "extra", None)
            if not isinstance(extra_obj, dict):
                continue
            series_id: object = extra_obj.get("series_id")
            if not isinstance(series_id, str) or series_id not in _DEMAND_SERIES_IDS:
                continue
            points.extend(_numeric_points(rec.payload))

    if missing_env and not points:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            missing_env=tuple(missing_env),
            source_ids=(source_id,),
            note="API key(s) not configured — no data found.",
        )
    if len(points) < 4:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            source_ids=(source_id,),
            note="Not enough demand data points landed — no data found.",
        )

    slope = _slope(points)
    if slope is None:
        return demo_result(
            label_hint="demand",
            value=rf"{demo.demand_trend():+.2f}",
            score=50.0 + demo.demand_trend() * 5.0,
            source_ids=(source_id,),
            note="Could not compute slope — no data found.",
        )
    magnitude = abs(slope)
    # INDPRO is an index around 100 (monthly). A slope of ~1.0/month is
    # a ~12% annualized move — already a strong signal. Scale by 10 so the
    # trend_score saturates at ±10 for monthly slopes of ~1.0+.
    trend_score = (slope / (magnitude + 1e-9)) * min(10.0, magnitude * 10.0)
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
