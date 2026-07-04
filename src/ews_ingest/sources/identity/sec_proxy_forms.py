"""SEC DEF 14A proxy statements, Forms 3/4/5 (spec §12): API / Scrape."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecProxyForms", "parse"]

FORMS: tuple[str, ...] = ("DEF 14A", "3", "4", "5")


def parse(raw: dict[str, object]) -> list[RecordInput]:
    hits = raw.get("hits") if isinstance(raw, dict) else None
    rows = hits.get("hits") if isinstance(hits, dict) else None
    items = rows if isinstance(rows, list) else []
    return [RecordInput(payload={"hit": h}, raw_format=RawFormat.JSON) for h in items]


@register_source("identity.sec_proxy_forms")
class SecProxyForms:
    """Per-entity DEF 14A / Form 3/4/5 filings via full-text search."""

    source_id = "identity.sec_proxy_forms"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            raw = sec.fulltext_search(
                ctx.http,
                ctx.rate_policy,
                q=entity.name,
                forms=list(FORMS),
            )
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = "https://efts.sec.gov/LATEST/search-index"
                yield build_record(ctx, self.source_id, self.source_type, spec)
