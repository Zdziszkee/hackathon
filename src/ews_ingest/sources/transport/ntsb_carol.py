"""NTSB Accident/Incident Database CAROL (spec §6): API/Bulk, no key."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["NtsbCarol", "parse"]

BASE = "https://data.ntsb.gov/carol-main/api"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a CAROL result-set into one record per study/accident."""
    results = raw.get("results") if isinstance(raw, dict) else None
    items = results if isinstance(results, list) else []
    return [RecordInput(payload={"accident": r}, raw_format=RawFormat.JSON) for r in items]


@register_source("transport.ntsb_carol")
class NtsbCarol:
    """Pull NTSB aviation/surface accident incidents for both sectors."""

    source_id = "transport.ntsb_carol"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        url = f"{BASE}/main/search"
        params: dict[str, str | int] = {" eventType": "A", "output": "JSON", "limit": 100}
        raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params)
        for spec in parse(raw):
            spec.url = url
            yield build_record(ctx, self.source_id, self.source_type, spec)
