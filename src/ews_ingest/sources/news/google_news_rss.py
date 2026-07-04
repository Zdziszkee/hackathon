"""Google News RSS (spec §2): headlines by query.

Fetched via scrapling (:class:`~ews_ingest.core.scrape.Scraper`) rather than
plain httpx: Google aggressively rate-limits/blocks non-browser traffic.
"""

from __future__ import annotations

from collections.abc import Iterator

import feedparser

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["GoogleNewsRss", "parse"]

BASE = "https://news.google.com/rss/search"


def _query(text: str) -> str:
    return text.replace(" ", "+")


def parse(adaptor: object) -> list[RecordInput]:
    """Parse a Google News RSS XML body into one record per entry."""
    body = getattr(adaptor, "body", b"") or b""
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
    feed = feedparser.parse(text)
    out: list[RecordInput] = []
    for entry in feed.entries:
        out.append(
            RecordInput(
                payload={
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "summary": entry.get("summary"),
                    "published": entry.get("published"),
                    "source": entry.get("source"),
                },
                raw_format=RawFormat.JSON,
            )
        )
    return out


@register_source("news.google_news_rss")
class GoogleNewsRss:
    """Per-entity headline search via Google News RSS."""

    source_id = "news.google_news_rss"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            url = f"{BASE}?q={_query(entity.name)}&hl=en-US&gl=US&ceid=US:en"
            adaptor = ctx.scraper.fetch_html(url, policy=ctx.rate_policy)
            for spec in parse(adaptor):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
