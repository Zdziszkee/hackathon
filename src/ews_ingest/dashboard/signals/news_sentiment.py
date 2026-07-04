"""Aggregated news-sentiment indicator (role: ``news.distress``).

GDELT articles carry a numeric ``tone`` field (already computed by GDELT — no
NLP dependency needed). This indicator averages the tone field across all
per-company articles in the landing zone and scales to a 0-100 risk score
where more-negative tone = higher risk.
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


def _article_tone(article: object) -> float | None:
    if not isinstance(article, dict):
        return None
    tone = article.get("tone") or article.get("socialscore") or None
    if isinstance(tone, (int, float)):
        return float(tone)
    if isinstance(tone, str):
        try:
            return float(tone.split(",", maxsplit=1)[0])
        except ValueError:
            return None
    return None


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
            label_hint="news_sentiment",
            value=rf"{demo.sentiment():+.2f}",
            score=50.0 - demo.sentiment() * 3.0,
            source_ids=(source_id,),
            note="No GDELT records landed — showing demo sentiment.",
        )
    tones: list[float] = []
    for rec in records:
        if not _matches_entity(rec.entities, company):
            continue
        payload = rec.payload
        tone = _article_tone(payload.get("article"))
        if tone is not None:
            tones.append(tone)
    if not tones:
        return demo_result(
            label_hint="news_sentiment",
            value=rf"{demo.sentiment():+.2f}",
            score=50.0 - demo.sentiment() * 3.0,
            source_ids=(source_id,),
            note="No articles with tone mentioning this company — showing demo.",
        )
    mean = sum(tones) / len(tones)
    # GDELT tone bounds roughly -10..+10; map to score 0..100 (worse = negative)
    score = max(0.0, min(100.0, 50.0 - mean * 3.0))
    status = "good" if mean > 2 else "warning" if mean > -2 else "bad"
    return ok_result(
        value=rf"{mean:+.2f}",
        score=score,
        status=status,
        detail={"mean_tone": round(mean, 3), "articles": len(tones)},
        source_ids=(source_id,),
    )


def _matches_entity(entities: list[Identifiers], company: Identifiers) -> bool:
    if not entities:
        return True
    return any(
        (e.name and e.name == company.name) or (e.ticker and e.ticker == company.ticker)
        for e in entities
    )


class _Provider:
    indicator_id = "news_sentiment"
    label = "Aggregated News Sentiment"

    description = "Mean GDELT article tone for this company. Negative tones indicate higher risk."
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
