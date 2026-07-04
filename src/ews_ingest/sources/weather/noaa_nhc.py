"""NOAA National Hurricane Center (spec §8): API, no key."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["NoaaNhc", "parse"]

BASE = "https://www.nhc.noaa.gov/CurrentStorms.json"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    storms = raw.get("activeStorms") if isinstance(raw, dict) else None
    items = storms if isinstance(storms, list) else []
    return [RecordInput(payload={"storm": s}, raw_format=RawFormat.JSON) for s in items]


@register_source("weather.noaa_nhc")
class NoaaNhc:
    """Pull active Atlantic/EPac storm advisories from NHC."""

    source_id = "weather.noaa_nhc"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        raw = ctx.http.get_json(BASE, policy=ctx.rate_policy)
        for spec in parse(raw):
            spec.url = BASE
            yield build_record(ctx, self.source_id, self.source_type, spec)
