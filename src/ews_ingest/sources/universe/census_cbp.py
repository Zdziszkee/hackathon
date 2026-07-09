"""Census Bureau County Business Patterns (spec §13, free key optional): seeding."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["CensusCbp", "parse"]

BASE = "https://api.census.gov/data/2022/cbp"
NAICS_FILTERS: tuple[str, ...] = ("325", "484")


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("universe.census_cbp", scope=Scope.SECTOR_AGGREGATE)
class CensusCbp:
    """Pull County Business Patterns for NAICS 325 and 484 (establishment counts)."""

    source_id = "universe.census_cbp"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        key = os.environ.get("CENSUS_API_KEY", "")
        for naics in NAICS_FILTERS:
            url = BASE
            params: dict[str, str | int] = {"get": "ESTAB,EMP", "NAICS": naics, "for": "us"}
            if key:
                params["key"] = key
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.url = url
                spec.extra = {"naics": naics}
                yield build_record(ctx, self.source_id, self.source_type, spec)
