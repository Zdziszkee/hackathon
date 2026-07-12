"""Industry-country volatility indicator (role: ``credit.ohlcv``).

Realized volatility from landed Yahoo Finance OHLCV. Annualized std of daily
log returns over the trailing 60 trading days. Score maps 10..60% annualized
vol to 0..100 (higher vol -> higher risk score).
"""

from __future__ import annotations

import math

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

ROLE = "credit.ohlcv"
_WINDOW = 60


def _closes(payload: dict[str, object]) -> list[float]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        return []
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        return []
    first = results[0]
    if not isinstance(first, dict):
        return []
    indicators = first.get("indicators")
    if not isinstance(indicators, dict):
        return []
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or not quotes:
        return []
    q = quotes[0]
    if not isinstance(q, dict):
        return []
    closes = q.get("close")
    if not isinstance(closes, list):
        return []
    out: list[float] = []
    for v in closes:
        if isinstance(v, (int, float)) and v > 0:
            out.append(float(v))
    return out


def _realized_vol(closes: list[float], window: int) -> float | None:
    if len(closes) < window + 2:
        # fall back to longest-available window if at least ~20 points
        window = len(closes) - 2
    if window < 10:
        return None
    series = closes[-(window + 1) :]
    logs = [math.log(series[i] / series[i - 1]) for i in range(1, len(series)) if series[i - 1] > 0]
    if len(logs) < 10:
        return None
    mean = sum(logs) / len(logs)
    var = sum((x - mean) ** 2 for x in logs) / (len(logs) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100.0  # annualized %


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No OHLCV source bound for this region.",
        )
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    if missing := ctx.missing_env(source_id):
        return demo_result(
            label_hint="volatility",
            value=rf"{demo.volatility()}%",
            score=demo.volatility() / 60.0 * 100.0,
            missing_env=tuple(missing),
            source_ids=(source_id,),
            note="API key not configured — no data found.",
        )
    records = ctx.landing.read(source_id).records
    if not records:
        return demo_result(
            label_hint="volatility",
            value=rf"{demo.volatility()}%",
            score=demo.volatility() / 60.0 * 100.0,
            source_ids=(source_id,),
            note="No OHLCV records landed — no data found.",
        )
    closes: list[float] = []
    for rec in records:
        if not _matches_entity(rec.entities, company):
            pass  # Yahoo records are per-company; but fallback if entities empty
        p = rec.payload
        closes.extend(_closes(p))
    if not closes:
        # No per-company match — fall back to any record (likely single-entity)
        for rec in records:
            closes.extend(_closes(rec.payload))
    vol = _realized_vol(closes, _WINDOW)
    if vol is None:
        return demo_result(
            label_hint="volatility",
            value=rf"{demo.volatility()}%",
            score=demo.volatility() / 60.0 * 100.0,
            source_ids=(source_id,),
            note="Not enough price points landed — no data found.",
        )
    score = min(100.0, max(0.0, (vol - 10.0) / 50.0 * 100.0))
    status = "good" if vol < 25 else "warning" if vol < 40 else "bad"
    return ok_result(
        value=rf"{vol:.1f}%",
        score=score,
        status=status,
        detail={"window": _WINDOW, "annualized_pct": round(vol, 2)},
        source_ids=(source_id,),
    )


def _matches_entity(entities: list[Identifiers], company: Identifiers) -> bool:
    if not entities:
        return True
    return any(e.ticker and e.ticker == company.ticker for e in entities)


class _Provider:
    indicator_id = "volatility"
    label = "Industry-Country Volatility"

    description = "Annualized realized volatility of 60-day log returns from Yahoo Finance OHLCV. Higher means riskier."
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
