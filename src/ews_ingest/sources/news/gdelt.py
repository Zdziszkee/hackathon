"""GDELT Project news (spec §2): tone/themes/geo via REST API v2. High-value."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import gdelt as api
from ews_ingest.providers.gdelt import DISTRESS_KEYWORDS

__all__ = ["GdeltNews", "parse"]

# Sector-level distress query terms (spec §2 example phrasing).
SECTOR_QUERIES: tuple[str, ...] = (
    "diesel driver shortage",
    "refinery outage chemicals",
    "airline bankruptcy restructuring",
    "trucking layoffs",
)

_ALIGNMENT = " | ".join(DISTRESS_KEYWORDS)


def _entity_query(name: str) -> str:
    return f'"{name}" ({_ALIGNMENT})'


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a GDELT doc-search response into one record per article."""
    articles = raw.get("articles") if isinstance(raw, dict) else None
    items = articles if isinstance(articles, list) else []
    return [RecordInput(payload={"article": a}, raw_format=RawFormat.JSON) for a in items]


@register_source("news.gdelt")
class GdeltNews:
    """Per-entity + sector distress article search via GDELT v2 doc endpoint."""

    source_id = "news.gdelt"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            query = _entity_query(entity.name)
            raw = api.doc_search(ctx.http, ctx.rate_policy, query=query)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = "https://api.gdeltproject.org/api/v2/doc/doc"
                yield build_record(ctx, self.source_id, self.source_type, spec)
        for query in SECTOR_QUERIES:
            raw = api.doc_search(ctx.http, ctx.rate_policy, query=query)
            for spec in parse(raw):
                spec.url = "https://api.gdeltproject.org/api/v2/doc/doc"
                yield build_record(ctx, self.source_id, self.source_type, spec)
