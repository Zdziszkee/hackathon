"""Logistics disruption (spec extension): news-driven disruption signal via GDELT.

Queries the GDELT doc endpoint for logistics/supply-chain distress terms and
splits the response into per-article records. Sector-agnostic; complements the
per-entity news.gdelt connector with sector-level disruption surveillance.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import gdelt as api

__all__ = ["LogisticsDisruption", "parse"]

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

QUERIES: tuple[str, ...] = (
    "port congestion",
    "supply chain disruption",
    "container ship delay",
    "rail freight disruption",
    "trucking capacity shortage",
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a GDELT doc-search response into one record per article."""
    articles = raw.get("articles") if isinstance(raw, dict) else None
    items = articles if isinstance(articles, list) else []
    return [RecordInput(payload={"article": a}, raw_format=RawFormat.JSON) for a in items]


@register_source(
    "supply_chain.logistics_disruption",
    scope=Scope.SECTOR_AGGREGATE,
)
class LogisticsDisruption:
    """Pull sector-level logistics-disruption news via GDELT."""

    source_id = "supply_chain.logistics_disruption"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for query in QUERIES:
            raw = api.doc_search(ctx.http, ctx.rate_policy, query=query)
            for spec in parse(raw):
                spec.url = GDELT_URL
                spec.extra = {"query": query}
                yield build_record(ctx, self.source_id, self.source_type, spec)
