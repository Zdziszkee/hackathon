"""FRED PPI/CPI mirrors (spec §10): free key."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fred

__all__ = ["FredPricing", "parse"]

BASE = "https://api.stlouisfed.org/fred/series/observations"

SERIES: tuple[tuple[str, str], ...] = (
    ("WPSFD49207", "ppi_final_demand"),
    ("CPIAUCSL", "cpi_all_items"),
    ("CUSR0000SETB01", "cpi_motor_fuel"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("pricing.fred_pricing")
class FredPricing:
    """Pull FRED PPI/CPI mirror series (5y rolling)."""

    source_id = "pricing.fred_pricing"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("FRED_API_KEY", "")
        for series_id, label in SERIES:
            params: dict[str, str | int] = {}
            if ctx.since is not None:
                params["observation_start"] = ctx.since.isoformat()
            raw = fred.series_observations(
                ctx.http,
                ctx.rate_policy,
                series_id=series_id,
                api_key=api_key,
                params=params or None,
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
