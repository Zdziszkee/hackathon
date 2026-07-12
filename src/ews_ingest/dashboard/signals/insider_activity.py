"""Insider / institutional activity indicator (role: ``credit.insider``).

Uses SEC Form 4 (insider transactions) and 13F-HR (institutional holdings)
search hits from the ``credit_market.sec_form4_13f`` landing zone. The
connector lands raw full-text-search results (not parsed XML transactions),
so this signal uses *filing activity* as the proxy:

* a high count of recent Form 4 filings in either direction = unusual
  insider activity around this name (often a precursor to news);
* 13F-HR hits indicate institutional repositioning.

For MVP we count filings per company over a trailing window. The signal
falls back to ``demo`` when no records have landed.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from datetime import UTC
from typing import Any

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

ROLE = "credit.insider"

_TRAILING_DAYS = 730  # ~2 years; Form 4/13F are quarterly/yearly
# Form 4 = insider; 13F-HR = institutional; SC 13D/G = activist/blockholder.
_INSIDER_FORMS = {"4", "4/A"}
_INSTITUTIONAL_FORMS = {"13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}


def _hit_date(hit: dict[str, object]) -> str:
    """Extract the filing/period date from a search-hit payload."""
    src = hit.get("_source") if isinstance(hit, dict) else None
    if not isinstance(src, dict):
        return ""
    for key in ("file_date", "period_ending"):
        v = src.get(key)
        if isinstance(v, str):
            return v
    return ""


def _hit_forms(hit: dict[str, object]) -> set[str]:
    """Extract form types from a search-hit payload."""
    src = hit.get("_source") if isinstance(hit, dict) else None
    if not isinstance(src, dict):
        return set()
    forms: set[str] = set()
    raw = src.get("form")
    if isinstance(raw, str):
        forms.add(raw)
    elif isinstance(raw, list):
        for f in raw:
            if isinstance(f, str):
                forms.add(f)
    return forms


def _is_recent(date_str: str, *, today: _dt.date, window_days: int) -> bool:
    if not date_str:
        return False
    try:
        d = _dt.date.fromisoformat(date_str[:10])
    except ValueError:
        return False
    return (today - d).days <= window_days


def _count_for_company(records: Iterable[object], company: Identifiers) -> tuple[int, int]:
    """Return (insider_count, institutional_count) for a company in the window."""
    today = _dt.datetime.now(UTC).date()
    insider = 0
    institutional = 0
    for rec in records:
        ents = getattr(rec, "entities", None)
        # Pydantic model list (in-memory) — match by ticker/cik/name.
        if isinstance(ents, list):
            match = any(
                (
                    isinstance(e, object)
                    and (
                        (
                            getattr(e, "ticker", None)
                            and company.ticker
                            and getattr(e, "ticker", "").upper() == company.ticker.upper()
                        )
                        or (
                            getattr(e, "cik", None)
                            and company.cik
                            and getattr(e, "cik", "") == company.cik
                        )
                        or (
                            getattr(e, "name", None)
                            and company.name
                            and getattr(e, "name", "").upper() == company.name.upper()
                        )
                    )
                )
                for e in ents
            )
        elif isinstance(ents, dict):
            match = (
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
        else:
            match = False
        if not match:
            continue
        payload = getattr(rec, "payload", None)
        if not isinstance(payload, dict):
            continue
        hit_obj: Any = payload.get("hit")
        if not isinstance(hit_obj, dict):
            continue
        if not _is_recent(_hit_date(hit_obj), today=today, window_days=_TRAILING_DAYS):
            continue
        forms = _hit_forms(hit_obj)
        if forms & _INSIDER_FORMS:
            insider += 1
        if forms & _INSTITUTIONAL_FORMS:
            institutional += 1
    return insider, institutional


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
            note="No insider-filing source bound for this portfolio.",
        )
    if miss := ctx.missing_env(source_id):
        return demo_result(
            label_hint="insider",
            value=f"Insider {demo.regulation_count()} filings",
            score=50.0,
            missing_env=tuple(miss),
            source_ids=(source_id,),
            note="API key not configured — showing demo count.",
        )
    records = ctx.landing.read(source_id).records
    insider, institutional = _count_for_company(records, company)
    total = insider + institutional
    if total == 0:
        return demo_result(
            label_hint="insider",
            value="0 filings",
            score=50.0,
            source_ids=(source_id,),
            note=f"No Form 4 / 13F filings for this borrower in the last {_TRAILING_DAYS} days — showing demo.",
        )
    # Unusual activity heuristic: any insider Form 4 in the window is
    # noteworthy. Score scales with count (capped).
    score = min(100.0, 50.0 + insider * 10.0 + institutional * 2.0)
    status = "good" if score < 55 else "warning" if score < 80 else "bad"
    return ok_result(
        value=f"{insider} ins / {institutional} 13F",
        score=score,
        status=status,
        detail={
            "insider_filings": insider,
            "institutional_filings": institutional,
            "window_days": _TRAILING_DAYS,
        },
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "insider_activity"
    label = "Insider Activity"

    description = (
        f"Count of SEC Form 4 (insider) and 13F-HR (institutional) filings "
        f"mentioning this borrower in the last {_TRAILING_DAYS} days. High "
        f"insider count = unusual activity around the name."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
