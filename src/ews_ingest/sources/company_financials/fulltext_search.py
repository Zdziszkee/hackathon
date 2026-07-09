"""SEC EDGAR Full-Text Search / efts.sec.gov (spec §1): 10-K/10-Q risk factors, MD&A."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecFulltextSearch", "parse"]

# Forms of interest for distress / risk-factor surveillance.
SEARCH_FORMS: tuple[str, ...] = ("10-K", "10-Q", "8-K", "DEF 14A")


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a full-text search response into one record per hit."""
    hits = raw.get("hits") if isinstance(raw, dict) else None
    rows = hits.get("hits") if isinstance(hits, dict) else None
    items = rows if isinstance(rows, list) else []
    return [RecordInput(payload={"hit": h}, raw_format=RawFormat.JSON) for h in items]


@register_source(
    "company_financials.fulltext_search",
    scope=Scope.PER_ENTITY,
)
class SecFulltextSearch:
    """Full-text search across recent filings for each seeded entity."""

    source_id = "company_financials.fulltext_search"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            raw = sec.fulltext_search(
                ctx.http,
                ctx.rate_policy,
                q=entity.name,
                forms=list(SEARCH_FORMS),
            )
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = "https://efts.sec.gov/LATEST/search-index"
                yield build_record(ctx, self.source_id, self.source_type, spec)
