"""Daily price-momentum indicator (role: ``credit.price_momentum``).

Reads the per-company daily-close series landed by
``credit_market.yahoo`` (yfinance chart response) and computes the
trailing 30-trading-day return. Negative momentum = sustained sell-off
(often precedes fundamental news by weeks).

Same series is also used by the correlation graph; this signal surfaces
the per-company slope as a 0..100 risk score.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from datetime import UTC

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    cast_status,
    demo_result,
    has_rate_limit_record,
    ok_result,
    rate_limited_result,
    register_provider,
)

__all__ = ["Provider", "compute"]

ROLE = "credit.price_momentum"
_WINDOW_DAYS = 30


def _entity_matches(ents: object, company: Identifiers) -> bool:
    if isinstance(ents, list):
        return any(
            isinstance(e, object)
            and (
                (
                    getattr(e, "ticker", None)
                    and company.ticker
                    and getattr(e, "ticker", "").upper() == company.ticker.upper()
                )
                or (
                    getattr(e, "cik", None) and company.cik and getattr(e, "cik", "") == company.cik
                )
                or (
                    getattr(e, "name", None)
                    and company.name
                    and getattr(e, "name", "").upper() == company.name.upper()
                )
            )
            for e in ents
        )
    if isinstance(ents, dict):
        return bool(
            (
                ents.get("ticker")
                and company.ticker
                and str(ents.get("ticker", "")).upper() == company.ticker.upper()
            )
            or (ents.get("cik") and company.cik and str(ents.get("cik", "")) == company.cik)
            or (
                ents.get("name")
                and company.name
                and str(ents.get("name", "")).upper() == company.name.upper()
            )
        )
    return False


def _read_company_closes(
    records: Iterable[object], company: Identifiers
) -> list[tuple[str, float]]:
    """Return ``[(date, close)]`` sorted chronologically.

    yfinance chart response shape:
        payload.chart.result[0].timestamp[i]  (unix seconds)
        payload.chart.result[0].indicators.quote[0].close[i]
    """
    series: list[tuple[str, float]] = []
    for rec in records:
        if not _entity_matches(getattr(rec, "entities", None), company):
            continue
        payload = getattr(rec, "payload", None)
        if not isinstance(payload, dict):
            continue
        chart = payload.get("chart")
        if not isinstance(chart, dict):
            continue
        results = chart.get("result")
        if not isinstance(results, list) or not results:
            continue
        first = results[0]
        if not isinstance(first, dict):
            continue
        timestamps = first.get("timestamp")
        indicators = first.get("indicators")
        if not isinstance(timestamps, list) or not isinstance(indicators, dict):
            continue
        quotes = indicators.get("quote")
        if not isinstance(quotes, list) or not quotes:
            continue
        q = quotes[0]
        if not isinstance(q, dict):
            continue
        closes = q.get("close")
        if not isinstance(closes, list):
            continue
        for i, c in enumerate(closes):
            if i >= len(timestamps):
                break
            if isinstance(c, (int, float)) and c > 0 and isinstance(timestamps[i], (int, float)):
                d = _dt.datetime.fromtimestamp(int(timestamps[i]), tz=UTC).date()
                series.append((d.isoformat(), float(c)))
    series.sort(key=lambda x: x[0])
    return series


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No price-history source bound for this portfolio.",
        )
    if miss := ctx.missing_env(source_id):
        return demo_result(
            label_hint="momentum",
            value="n/a",
            score=50.0,
            missing_env=tuple(miss),
            source_ids=(source_id,),
            note="API key not configured — no data found.",
        )
    records = ctx.landing.read(source_id).records
    if has_rate_limit_record(records):
        return rate_limited_result(source_id)
    series = _read_company_closes(records, company)
    if len(series) < 2:
        return demo_result(
            label_hint="momentum",
            value="n/a",
            score=50.0,
            source_ids=(source_id,),
            note="Not enough price points for this borrower — no data found.",
        )
    cutoff_date = _dt.datetime.now(UTC).date() - _dt.timedelta(days=_WINDOW_DAYS * 2)
    cutoff = cutoff_date.isoformat()
    windowed = [(d, c) for d, c in series if d >= cutoff]
    if len(windowed) < 2:
        windowed = series[-_WINDOW_DAYS:]
    if len(windowed) < 2:
        return demo_result(
            label_hint="momentum",
            value="n/a",
            score=50.0,
            source_ids=(source_id,),
            note="Insufficient price history in trailing window.",
        )
    start_close = windowed[0][1]
    end_close = windowed[-1][1]
    if start_close <= 0:
        return demo_result(
            label_hint="momentum",
            value="n/a",
            score=50.0,
            source_ids=(source_id,),
            note="Non-positive start price — return undefined.",
        )
    momentum = (end_close / start_close) - 1.0
    score = max(0.0, min(100.0, 50.0 - momentum * 250.0))
    status = "good" if momentum > 0.0 else "warning" if momentum > -0.10 else "bad"
    return ok_result(
        value=rf"{momentum:+.1%}",
        score=score,
        status=status,
        detail={
            "momentum_30d": round(momentum, 4),
            "start_date": windowed[0][0],
            "end_date": windowed[-1][0],
            "start_close": start_close,
            "end_close": end_close,
        },
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "price_momentum"
    label = "Price Momentum (30d)"

    description = (
        f"Trailing {_WINDOW_DAYS}-trading-day return on the company's daily close. "
        f"Negative = sustained sell-off, often a leading indicator of "
        f"fundamental news."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
