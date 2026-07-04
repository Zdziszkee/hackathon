"""Common Crawl CC-NEWS (spec §2): raw news WARC crawl."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["CommonCrawlNews", "parse"]

INDEX_URL = "https://index.commoncrawl.org/collinfo"


def parse(raw: list[object]) -> list[RecordInput]:
    """Each crawl-info entry becomes one manifest record (the TB-scale WARCs
    are not persisted in the JSONL landing zone — only the index is)."""
    return [
        RecordInput(payload={"crawl": c}, raw_format=RawFormat.JSON, url=INDEX_URL) for c in raw
    ]


@register_source("news.common_crawl_news")
class CommonCrawlNews:
    """Record the CC-NEWS crawl index manifest for later WARC fetching."""

    source_id = "news.common_crawl_news"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        data = ctx.http.get_json_list(INDEX_URL, policy=ctx.rate_policy)
        for spec in parse(data):
            yield build_record(ctx, self.source_id, self.source_type, spec)
