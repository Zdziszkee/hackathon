"""Earnings-surprise (SUE) indicator (role: ``financials.sue``).

Standardized Unexpected Earnings = (current net income - trailing 4-quarter
mean) / trailing 4-quarter stdev. Positive SUE = beat relative to recent
trend; large negative SUE = missed badly. The series is the key leading
indicator for customer/supplier cascade propagation.

Reads from the already-landed SEC XBRL ``company_financials.company_facts``
payload (quarterly ``NetIncomeLoss``) and the ``8-K`` filings (used as a
proxy for the *period ending* of the latest quarter).
"""

from __future__ import annotations

import statistics
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

ROLE = "financials.sue"
_TRAILING_QUARTERS = 4


def _extract_quarterly_ni(payload: dict[str, object]) -> list[tuple[str, float]]:
    """Return ``[(end_date, net_income)]`` sorted chronologically."""
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return []
    us_gaap = facts.get("us-gaap")
    if not isinstance(us_gaap, dict):
        return []
    node = us_gaap.get("NetIncomeLoss")
    if not isinstance(node, dict):
        node = us_gaap.get("ProfitLoss")
    if not isinstance(node, dict):
        return []
    units = node.get("units")
    if not isinstance(units, dict):
        return []
    usd = units.get("USD")
    if not isinstance(usd, list):
        return []
    rows: list[tuple[str, float, str]] = []
    for row in usd:
        if not isinstance(row, dict):
            continue
        v = row.get("val")
        end_raw = row.get("end")
        fp_raw = row.get("fp")
        form_raw = row.get("form")
        if not isinstance(v, (int, float)):
            continue
        end = str(end_raw) if isinstance(end_raw, str) else ""
        if not end:
            continue
        fp = str(fp_raw) if isinstance(fp_raw, str) else ""
        form = str(form_raw) if isinstance(form_raw, str) else ""
        # Only quarterly (FP) filings — skip YTD duplicates.
        if fp and not fp.startswith("Q"):
            continue
        rows.append((end, float(v), form))
    # Deduplicate by end-date: keep the latest form (10-K > 10-Q).
    rows.sort(key=lambda x: (x[0], x[2]))
    seen: set[str] = set()
    deduped: list[tuple[str, float]] = []
    for end, v, _form in reversed(rows):
        if end in seen:
            continue
        seen.add(end)
        deduped.append((end, v))
    deduped.sort(key=lambda x: x[0])
    return deduped


def _facts_for_company(records: Iterable[object], company: Identifiers) -> dict[str, object] | None:
    for rec in records:
        ents = getattr(rec, "entities", None)
        match = False
        if isinstance(ents, list):
            match = any(
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
        if match:
            payload = getattr(rec, "payload", None)
            if isinstance(payload, dict):
                return payload
    return None


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
            note="No XBRL source bound for SUE.",
        )
    if miss := ctx.missing_env(source_id):
        return demo_result(
            label_hint="sue",
            value=rf"{demo.sentiment():+.2f}",
            score=50.0,
            missing_env=tuple(miss),
            source_ids=(source_id,),
            note="API key not configured — showing demo SUE.",
        )
    records = ctx.landing.read(source_id).records
    facts = _facts_for_company(records, company)
    if facts is None:
        return demo_result(
            label_hint="sue",
            value="n/a",
            score=50.0,
            source_ids=(source_id,),
            note="No XBRL facts for this borrower — showing demo SUE.",
        )
    quarters = _extract_quarterly_ni(facts)
    if len(quarters) < _TRAILING_QUARTERS + 1:
        return demo_result(
            label_hint="sue",
            value="n/a",
            score=50.0,
            source_ids=(source_id,),
            note=(
                f"Need {_TRAILING_QUARTERS + 1}+ quarters of NI in XBRL; "
                f"have {len(quarters)} — showing demo SUE."
            ),
        )
    last_end, last_ni = quarters[-1]
    trailing = [v for _, v in quarters[-_TRAILING_QUARTERS - 1 : -1]]
    mean = statistics.fmean(trailing)
    stdev = statistics.stdev(trailing) if len(trailing) > 1 else 0.0
    if stdev <= 0:
        return demo_result(
            label_hint="sue",
            value="n/a",
            score=50.0,
            source_ids=(source_id,),
            note="Trailing-quarter NI has zero variance — SUE undefined.",
        )
    sue = (last_ni - mean) / stdev
    # Negative SUE = bad; map to 0..100 risk.
    score = max(0.0, min(100.0, 50.0 - sue * 15.0))
    status = "good" if sue > 0.5 else "warning" if sue > -0.5 else "bad"
    return ok_result(
        value=rf"{sue:+.2f}s",
        score=score,
        status=status,
        detail={
            "sue": round(sue, 3),
            "last_quarter_ni": last_ni,
            "last_quarter_end": last_end,
            "trailing_mean": round(mean, 2),
            "trailing_stdev": round(stdev, 2),
        },
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "earnings_surprise"
    label = "Earnings Surprise (SUE)"

    description = (
        f"Standardized Unexpected Earnings: (last quarter NI - trailing "
        f"{_TRAILING_QUARTERS}-quarter mean) / trailing stdev. Negative SUE "
        f"= earnings miss, leading indicator for cascades to customers/"
        f"suppliers."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
