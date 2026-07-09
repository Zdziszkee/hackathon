"""EIA refinery capacity & utilization (spec §7): same EIA key as §5 (API/Bulk)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import eia as eia_api

__all__ = ["EiaRefinery", "parse"]

BASE = "https://api.eia.gov/v2"

ROUTE: list[str] = ["petroleum", "sum", "snd", "data"]
SERIES: tuple[tuple[str, str], ...] = (
    ("WPULEUS3", "refinery_utilization"),
    ("WPRB_NP_US", "refinery_production"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source(
    "petrochem.eia_refinery",
    scope=Scope.SECTOR_AGGREGATE,
)
class EiaRefinery:
    """Pull EIA refinery utilization/capacity series."""

    source_id = "petrochem.eia_refinery"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("EIA_API_KEY", "")
        for series_id, label in SERIES:
            params: dict[str, str | int] = {
                "frequency": "monthly",
                "facets[series][0]": series_id,
            }
            if ctx.since is not None:
                params["start"] = ctx.since.isoformat()
            raw = eia_api.data(
                ctx.http,
                ctx.rate_policy,
                api_key=api_key,
                route=ROUTE,
                params=params,
            )
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload=raw,
                    raw_format=RawFormat.JSON,
                    url=BASE,
                    extra={"series_id": series_id, "label": label},
                ),
            )
