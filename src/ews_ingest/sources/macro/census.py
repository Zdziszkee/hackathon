"""Census Bureau (spec §4): durable goods orders, business formation stats (free key optional)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Census", "parse"]

BASE = "https://api.census.gov/data"

SERIES: tuple[tuple[str, str], ...] = (
    ("time/asm?get=NAICS&NAICS=325&YEAR=2022", "chemicals_shipments"),
    ("timeseries/eits/advm?get=cell_value,time_slot_id", "durable_goods_new_orders"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap a Census API response as one record."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("macro.census", scope=Scope.SECTOR_AGGREGATE)
class Census:
    """Pull durable-goods / business-formation statistics."""

    source_id = "macro.census"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        key = os.environ.get("CENSUS_API_KEY", "")
        for path, label in SERIES:
            url = f"{BASE}/{path}"
            params: dict[str, str | int] = {}
            if key:
                params["key"] = key
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params or None)
            for spec in parse(raw):
                spec.url = url
                spec.extra = {"label": label, "note": "verify_dataset"}
                yield build_record(ctx, self.source_id, self.source_type, spec)
