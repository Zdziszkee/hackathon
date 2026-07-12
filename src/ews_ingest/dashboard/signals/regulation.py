"""Policy & regulation-stability indicator (role: ``news.distress``).

Proxy: count of news stories (per-company) whose titles match a
regulation/policy keyword set, as a stand-in for "regulatory changes
concerning this company". Works against any source bound to ``news.distress``:
GDELT records have ``article.title``; Hacker News records have ``title`` at
the top level. Both formats are handled.
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


def _extract_title(payload: object) -> str:
    """Pull a title string from either GDELT or Hacker News payload shape."""
    if not isinstance(payload, dict):
        return ""
    v = payload.get("title")
    if isinstance(v, str) and v:
        return v.lower()
    article = payload.get("article")
    if isinstance(article, dict):
        t = article.get("title")
        if isinstance(t, str):
            return t.lower()
    return ""


def _is_regulation(title: str) -> bool:
    return any(term in title for term in _REGULATION_TERMS)


def _matches_entity(entities: object, company: Identifiers) -> bool:
    if not isinstance(entities, list) or not entities:
        return True
    for e in entities:
        # ``rec.entities`` are Pydantic ``Identifiers`` models in-memory;
        # landing-zone records deserialised from JSON are dicts. Handle both.
        if isinstance(e, dict):
            et = e.get("ticker")
            en = e.get("name")
        else:
            et = getattr(e, "ticker", None)
            en = getattr(e, "name", None)
        if isinstance(et, str) and company.ticker and et.upper() == company.ticker.upper():
            return True
        if isinstance(en, str) and company.name and en.upper() == company.name.upper():
            return True
    return False


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
            note="No news records landed — no data found.",
        )
    count = 0
    total = 0
    for rec in records:
        if not _matches_entity(getattr(rec, "entities", None), company):
            continue
        title = _extract_title(rec.payload)
        if not title:
            continue
        total += 1
        if _is_regulation(title):
            count += 1
    if total == 0:
        return demo_result(
            label_hint="regulation",
            value=f"{demo.regulation_count()} articles",
            score=min(100.0, demo.regulation_count() * 15.0),
            source_ids=(source_id,),
            note="No news stories for this company — no data found.",
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


class _Provider:
    indicator_id = "regulation"
    label = "Policy & Regulation Stability"

    description = (
        "Proxy: count of news stories matching regulation/policy keywords "
        "for this company. Works against any source bound to news.distress."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
