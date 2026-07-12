"""Aggregated news-sentiment indicator (role: ``news.distress``).

Computes a per-company distress sentiment by running VADER (rule-based
sentiment analyzer) over Hacker News story titles + text. The role is
``news.distress`` and the default source binding is ``news.hackernews`` (free,
no key). GDELT (``news.gdelt``) is kept as a fallback when bound, but the
GDELT doc API is heavily rate-limited and the local HN+VADER path is the
reliable default.

Score is the VADER ``compound`` value (range -1..+1) mapped to 0..100 risk
where more-negative tone = higher risk. Falls back to a deterministic demo
value when no records have landed for the company yet.
"""

from __future__ import annotations

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

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


def _vader_compound(text: str) -> float:
    """Return VADER compound score (-1..+1) for ``text``; 0.0 on empty text."""
    if not text:
        return 0.0
    sia = SentimentIntensityAnalyzer()
    return float(sia.polarity_scores(text)["compound"])


ROLE = "news.distress"


def _story_text(payload: object) -> str:
    """Concatenate the human-readable text fields from a story payload."""
    if not isinstance(payload, dict):
        return ""
    title = payload.get("title") or ""
    body = payload.get("story_text") or ""
    if not isinstance(title, str):
        title = ""
    if not isinstance(body, str):
        body = ""
    # ``title`` carries the bulk of the signal; ``story_text`` is the
    # self-post body (often empty for link submissions).
    return f"{title}. {body}".strip()


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
    seed = company.name or company.ticker or company.cik or "company"
    demo = DemoValues.for_company(seed)

    source_id = ctx.source_for(ROLE)
    if source_id is None:
        return demo_result(
            label_hint="news_sentiment",
            value=rf"{demo.sentiment():+.2f}",
            score=50.0,
            source_ids=(),
            note="No news source bound for this region.",
        )

    miss = ctx.missing_env(source_id)
    if miss:
        return demo_result(
            label_hint="news_sentiment",
            value=rf"{demo.sentiment():+.2f}",
            score=50.0 - demo.sentiment() * 3.0,
            missing_env=tuple(miss),
            source_ids=(source_id,),
            note="API key(s) not configured — no data found.",
        )

    compounds: list[float] = []
    for rec in ctx.landing.read(source_id).records:
        if not _matches_entity(getattr(rec, "entities", None), company):
            continue
        text = _story_text(rec.payload)
        if not text:
            continue
        compounds.append(_vader_compound(text))

    if not compounds:
        return demo_result(
            label_hint="news_sentiment",
            value=rf"{demo.sentiment():+.2f}",
            score=50.0 - demo.sentiment() * 3.0,
            source_ids=(source_id,),
            note="No news stories landed for this company — no data found.",
        )

    mean = sum(compounds) / len(compounds)
    # Map compound (-1..+1) to 0..100 risk: negative tone = higher risk.
    score = max(0.0, min(100.0, 50.0 - mean * 50.0))
    status = "good" if mean > 0.2 else "warning" if mean > -0.2 else "bad"
    return ok_result(
        value=rf"{mean:+.2f}",
        score=score,
        status=cast_status(status),
        detail={"mean_compound": round(mean, 3), "stories": len(compounds)},
        source_ids=(source_id,),
    )


class _Provider:
    indicator_id = "news_sentiment"
    label = "Aggregated News Sentiment"

    description = (
        "Mean VADER sentiment of Hacker News stories mentioning this "
        "company over the last year. Negative tone = higher risk."
    )
    roles: tuple[str, ...] = (ROLE,)

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult:
        return compute(company, ctx)


Provider = _Provider()
register_provider(Provider)
