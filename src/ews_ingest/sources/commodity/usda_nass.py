"""USDA NASS Quick Stats / ERS (spec §5): ag & fertilizer prices (free key)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["UsdaNass", "parse"]

BASE = "https://quickstats.nass.usda.gov/api/api_GET"

QUERIES: tuple[tuple[str, str], ...] = (
    ("statisticcat_desc=PRICE RECEIVED&commodity_desc=FERTILIZER", "fertilizer_prices"),
    ("statisticcat_desc=PRICE RECEIVED&commodity_desc=CORN", "corn_prices"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("commodity.usda_nass")
class UsdaNass:
    """Pull USDA NASS price series."""

    source_id = "commodity.usda_nass"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        key = os.environ.get("USDA_API_KEY", "")
        for query, label in QUERIES:
            url = f"{BASE}?{query}"
            params: dict[str, str | int] = {"format": "JSON"}
            if key:
                params["key"] = key
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params or None)
            for spec in parse(raw):
                spec.url = url
                spec.extra = {"label": label}
                yield build_record(ctx, self.source_id, self.source_type, spec)
