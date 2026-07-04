"""SEC Form 4 / 13F / SC 13D-G (spec §3): insider & institutional holdings."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecForm413f", "parse"]

FORMS: tuple[str, ...] = ("4", "13F-HR", "SC 13D", "SC 13G")


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a full-text search response into one record per hit."""
    hits = raw.get("hits") if isinstance(raw, dict) else None
    rows = hits.get("hits") if isinstance(hits, dict) else None
    items = rows if isinstance(rows, list) else []
    return [RecordInput(payload={"hit": h}, raw_format=RawFormat.JSON) for h in items]


@register_source("credit_market.sec_form4_13f")
class SecForm413f:
    """Per-entity insider/institutional holding filings via full-text search."""

    source_id = "credit_market.sec_form4_13f"
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
