"""WARN Act layoff-notice indicator (role: ``labor.warn``).

Counts recent Worker Adjustment & Retraining Notices (state mass-layoff
filings) from the ``labor.state_warn_*`` sources. Each state connector
stores records with ``payload.warn_row`` containing ``company``,
``location``, ``num_employees``, ``notice_date`` (most fields may be empty
if the upstream page doesn't expose them — the count itself is still a
real number).

Same value for every company (regional indicator), by design.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from datetime import UTC

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
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

ROLE = "labor.warn"
_TRAILING_DAYS = 730  # ~2 years; WARN filings lag and the data we land is historical


def _count_warns(records: Iterable[object], *, today: _dt.date) -> int:
    """Count WARN notices in the trailing window across all records."""
    cutoff = today - _dt.timedelta(days=_TRAILING_DAYS)
    n = 0
    for rec in records:
        payload = getattr(rec, "payload", None)
        if not isinstance(payload, dict):
            continue
        row = payload.get("warn_row")
        if not isinstance(row, dict):
            continue
        d_raw = row.get("notice_date")
        if not isinstance(d_raw, str) or not d_raw:
            # No date → still count, but only if the record is recent.
            fetched = getattr(rec, "fetched_at", None)
            if fetched is None:
                continue
            try:
                fd = fetched.date()
            except AttributeError:
                continue
            if fd >= cutoff:
                n += 1
            continue
        # Best-effort parse: pick first 4-digit year, accept ISO-ish.
        s = d_raw.strip()
        parsed: _dt.date | None = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                parsed = _dt.datetime.strptime(s[:10], fmt).replace(tzinfo=UTC).date()
                break
            except ValueError:
                continue
        if parsed is None:
            continue
        if parsed >= cutoff:
            n += 1
    return n


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
            note="No WARN source bound for this portfolio.",
        )
    if miss := ctx.missing_env(source_id):
        return demo_result(
            label_hint="warn",
            value=f"{demo.regulation_count()} notices",
            score=50.0,
            missing_env=tuple(miss),
            source_ids=(source_id,),
            note="API key not configured — no data found.",
        )
    records = ctx.landing.read(source_id).records
    if has_rate_limit_record(records):
        return rate_limited_result(source_id)
    today = _dt.datetime.now(UTC).date()
    n = _count_warns(records, today=today)
    if n == 0:
        return demo_result(
            label_hint="warn",
            value="0 notices",
            score=50.0,
            source_ids=(source_id,),
            note=f"No WARN notices landed in the last {_TRAILING_DAYS} days — no data found.",
        )
    # Score: more notices = more labor-market stress. Same for every company.
    score = min(100.0, 50.0 + min(n, 20) * 2.5)
    status = "good" if score < 55 else "warning" if score < 80 else "bad"
    return ok_result(
        value=f"{n} notices",
        score=score,
        status=status,
        detail={"warn_count": n, "window_days": _TRAILING_DAYS},
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "warn_layoffs"
    label = "WARN Act Layoffs"

    description = (
        f"Count of state WARN (Worker Adjustment & Retraining) mass-layoff "
        f"notices landed in the last {_TRAILING_DAYS} days across the "
        f"portfolio's state sources. Higher = more labor-market stress."
    )
    roles: tuple[str, ...] = (ROLE,)
    weight: float = 0.06

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
