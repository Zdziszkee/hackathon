"""BTS Freight Transportation Services Index (spec §6): API/Bulk, no key."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import bts

__all__ = ["BtsFtsi", "parse"]


def parse(rows: list[object]) -> list[RecordInput]:
    return [RecordInput(payload={"row": r}, raw_format=RawFormat.JSON) for r in rows]


@register_source(
    "transport.bts_ftsi",
    scope=Scope.SECTOR_AGGREGATE,
)
class BtsFtsi:
    """Pull the Freight Transportation Services Index (Socrata rows)."""

    source_id = "transport.bts_ftsi"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        resource_id = bts.RESOURCES["ftsi"]
        params: dict[str, str | int] = {"$limit": 5000}
        rows = bts.socrata(ctx.http, ctx.rate_policy, resource_id=resource_id, params=params)
        for spec in parse(rows):
            spec.url = f"https://data.bts.gov/resource/{resource_id}.json"
            yield build_record(ctx, self.source_id, self.source_type, spec)
