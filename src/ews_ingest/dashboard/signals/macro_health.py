"""Country macro-health indicator (role: ``macro.mfg_pmi``).

Headline ISM Manufacturing PMI parsed from the landed page text. PMI > 50 =
expansion (lower risk); below 50 = contraction (higher risk).
"""

from __future__ import annotations

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.signals import (
    SignalContext,
    SignalResult,
    demo_result,
    ok_result,
    register_provider,
)
from ews_ingest.dashboard.signals.ism import parse_ism

__all__ = ["Provider", "compute"]

ROLE = "macro.mfg_pmi"


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return demo_result(
            label_hint="macro_health",
            value=f"{demo.pmi()}",
            score=abs(50.0 - demo.pmi()) * 5.0,
            source_ids=(),
            note="No PMI source bound — showing demo.",
        )
    if missing := ctx.missing_env(source_id):
        return demo_result(
            label_hint="macro_health",
            value=f"{demo.pmi()}",
            score=abs(50.0 - demo.pmi()) * 5.0,
            missing_env=tuple(missing),
            source_ids=(source_id,),
            note="API key not configured — showing demo PMI.",
        )
    store = ctx.landing.read(source_id)
    latest = store.latest()
    if latest is None:
        return demo_result(
            label_hint="macro_health",
            value=f"{demo.pmi()}",
            score=abs(50.0 - demo.pmi()) * 5.0,
            source_ids=(source_id,),
            note="No ISM PMI records landed — showing demo PMI.",
        )
    page_text = str(latest.payload.get("page_text") or "")
    ism = parse_ism(page_text)
    pmi = ism["headline"]
    if pmi is None:
        return demo_result(
            label_hint="macro_health",
            value=f"{demo.pmi()}",
            score=abs(50.0 - demo.pmi()) * 5.0,
            source_ids=(source_id,),
            note="Could not parse PMI from landed page text — showing demo.",
        )
    score = abs(50.0 - pmi) * 5.0
    status = "good" if pmi >= 52 else "warning" if pmi >= 50 else "bad"
    return ok_result(
        value=f"{pmi:.1f}",
        score=min(100.0, max(0.0, score)),
        status=status,
        detail={"pmi": pmi},
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "macro_health"
    label = "Country Macro Health (PMI)"

    description = (
        "ISM Manufacturing PMI headline. Above 50 means expansion, below 50 means contraction."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
