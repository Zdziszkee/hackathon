"""National Weather Service API (spec §8): api.weather.gov, no key."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Nws", "parse"]

BASE = "https://api.weather.gov"
ALERTS = f"{BASE}/alerts/active"
ACCEPT_HEADERS = {"Accept": "application/ld+json"}


def parse(raw: list[object]) -> list[RecordInput]:
    return [RecordInput(payload={"alert": a}, raw_format=RawFormat.JSON) for a in raw]


@register_source("weather.nws")
class Nws:
    """Pull active NWS alerts (severe weather for Gulf Coast exposures)."""

    source_id = "weather.nws"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        params: dict[str, str | int] = {"area": "TX,LA,MS,AL,FL"}
        data = ctx.http.get_json_list(
            ALERTS,
            policy=ctx.rate_policy,
            params=params,
            headers=ACCEPT_HEADERS,
        )
        for spec in parse(data):
            spec.url = ALERTS
            yield build_record(ctx, self.source_id, self.source_type, spec)
