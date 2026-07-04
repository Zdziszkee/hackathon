"""SEC Submissions/Company Facts for identity (spec §12): CIK/ticker/SIC map (API)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecIdentity", "parse"]


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap a submissions doc as one identity record (filer metadata/crosswalk)."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("identity.sec_identity")
class SecIdentity:
    """Per-entity SEC identity/crosswalk via the Submissions API."""

    source_id = "identity.sec_identity"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.cik:
                continue
            raw = sec.submissions(ctx.http, ctx.rate_policy, entity.cik)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = f"https://data.sec.gov/submissions/CIK{entity.cik.zfill(10)}.json"
                yield build_record(ctx, self.source_id, self.source_type, spec)
