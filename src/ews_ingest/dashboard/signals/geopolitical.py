"""Geopolitical-risk indicator (role: ``sanctions``).

Counts OpenSanctions matches (sanctions + PEP) for the company name. Degrades
gracefully when ``OPENSANCTIONS_API_KEY`` is unset (demo) — the connector
returns results without the key but they are limited; the dashboard treats a
missing key as demo too for honesty.
"""

from __future__ import annotations

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

ROLE = "sanctions"


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No sanctions source bound.",
        )
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    if missing := ctx.missing_env(source_id):
        return demo_result(
            label_hint="geopolitical",
            value=f"{demo.sanctions_count()} flags",
            score=demo.sanctions_count() * 30.0,
            missing_env=tuple(missing),
            source_ids=(source_id,),
            note="Required env var(s) not set — showing demo flag count.",
        )
    records = ctx.landing.read(source_id).records
    if not records:
        return demo_result(
            label_hint="geopolitical",
            value=f"{demo.sanctions_count()} flags",
            score=demo.sanctions_count() * 30.0,
            source_ids=(source_id,),
            note="No sanctions records landed — no data found.",
        )
    matches = 0
    for rec in records:
        if not _matches_entity(rec.entities, company):
            continue
        payload = rec.payload
        match = payload.get("match")
        if match is not None:
            matches += 1
    score = min(100.0, matches * 30.0)
    status = "good" if matches == 0 else "warning" if matches <= 2 else "bad"
    return ok_result(
        value=f"{matches} flags",
        score=score,
        status=status,
        detail={"matches": matches},
        source_ids=(source_id,),
    )


def _matches_entity(entities: list[Identifiers], company: Identifiers) -> bool:
    if not entities:
        return True
    return any(e.name and e.name == company.name for e in entities)


class _Provider:
    indicator_id = "geopolitical"
    label = "Geopolitical Risk"

    description = (
        "Count of sanctions and politically exposed person (PEP) matches from OpenSanctions."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
