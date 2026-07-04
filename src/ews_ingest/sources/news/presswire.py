"""Press-wire RSS feeds (spec §2): GlobeNewswire / Business Wire / PR Newswire."""

from __future__ import annotations

from collections.abc import Iterator

import feedparser

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Presswire", "parse"]

# Known sector/industry press-wire RSS feeds (free, public).
FEEDS: tuple[str, ...] = (
    "https://www.globenewswire.com/rss/industry/413/Transportation",
    "https://www.globenewswire.com/rss/industry/226/Chemicals",
)


def _entry(entry: object) -> RecordInput:
    e = entry if isinstance(entry, dict) else {}
    return RecordInput(
        payload={
            "title": e.get("title"),
            "link": e.get("link"),
            "summary": e.get("summary"),
            "published": e.get("published"),
        },
        raw_format=RawFormat.JSON,
    )


def parse(text: str) -> list[RecordInput]:
    feed = feedparser.parse(text)
    return [_entry(entry) for entry in feed.entries]


@register_source("news.presswire")
class Presswire:
    """Aggregates the configured press-wire RSS feeds."""

    source_id = "news.presswire"
    source_type = SourceType.RSS

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for url in FEEDS:
            text = ctx.http.get_text(url, policy=ctx.rate_policy)
            for spec in parse(text):
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
