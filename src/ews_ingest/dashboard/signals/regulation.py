"""Policy & regulation-stability indicator (role: ``news.distress``).

Proxy: count of GDELT distress articles (per-company) whose titles match a
regulation/policy keyword set, as a stand-in for "regulatory changes concerning
this company". GDELT's ``artlist`` mode (what the connector lands) does not
carry theme codes, so we score titles heuristically for regulation signals.

Imitation of the spec is honest: there is no source that literally counts new
regulations, so this is the closest existing-source proxy.
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

ROLE = "news.distress"

_REGULATION_TERMS = (
    "regulation",
    "regulator",
    "regulate",
    "compliance",
    "ruling",
    "law",
    "lawsuit",
    "lawsuit",
    "ban",
    "tariff",
    "fine",
    "penalty",
    "consent decree",
    "epa",
    "doj",
    "sec",
    "fcc",
    "faa",
    "european union",
    "directive",
    "antitrust",
)


def _title(article: object) -> str:
    if isinstance(article, dict):
        v = article.get("title") or article.get("url") or ""
        return str(v).lower()
    return ""


def _is_regulation(title: str) -> bool:
    return any(term in title for term in _REGULATION_TERMS)


def compute(company: Identifiers, ctx: SignalContext) -> SignalResult:
    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return SignalResult(
            value="n/a",
            score=0.0,
            status=cast_status("unavailable"),
            detail={},
            source_ids=(),
            note="No news source bound for this region.",
        )
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)
    records = ctx.landing.read(source_id).records
    if not records:
        return demo_result(
            label_hint="regulation",
            value=f"{demo.regulation_count()} articles",
            score=min(100.0, demo.regulation_count() * 15.0),
            source_ids=(source_id,),
            note="No GDELT records landed — showing demo count.",
        )
    count = 0
    total = 0
    for rec in records:
        if not _matches_entity(rec.entities, company):
            continue
        payload = rec.payload
        article = payload.get("article")
        if article is None:
            continue
        total += 1
        if _is_regulation(_title(article)):
            count += 1
    if total == 0:
        return demo_result(
            label_hint="regulation",
            value=f"{demo.regulation_count()} articles",
            score=min(100.0, demo.regulation_count() * 15.0),
            source_ids=(source_id,),
            note="No articles mentioning this company landed — showing demo.",
        )
    score = min(100.0, count * 15.0)
    status = "good" if count <= 1 else "warning" if count <= 4 else "bad"
    return ok_result(
        value=f"{count} articles",
        score=score,
        status=status,
        detail={"regulation_articles": count, "total_articles_seen": total},
        source_ids=(source_id,),
    )


def _matches_entity(entities: list[Identifiers], company: Identifiers) -> bool:
    if not entities:
        return True
    return any(e.name and e.name == company.name for e in entities)


class _Provider:
    indicator_id = "regulation"
    label = "Policy & Regulation Stability"

    description = "Proxy: count of GDELT distress articles matching regulation/policy keywords for this company."
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
