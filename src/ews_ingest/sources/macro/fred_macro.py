"""FRED macro indicators (spec §4): rates, industrial production, capacity util.

High-value. Uses FRED_API_KEY.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fred

__all__ = ["FredMacro", "parse"]

BASE = "https://api.stlouisfed.org/fred/series/observations"

# Macro series: yield curve + industrial production + capacity utilization +
# truck tonnage (used by the demand-trend indicator for transport_logistics
# borrowers — ATA's own page is JS-rendered, FRED mirrors the index monthly).
SERIES: tuple[tuple[str, str, str], ...] = (
    ("DGS10", "yield_10y", "Treasury 10Y"),
    ("DGS2", "yield_2y", "Treasury 2Y"),
    ("T10Y2Y", "yield_curve_10y_2y", "Yield curve 10Y-2Y"),
    ("INDPRO", "industrial_production", "Industrial Production Index"),
    ("TCU", "capacity_utilization", "Capacity Utilization"),
    ("TRUCKD11", "truck_tonnage", "Truck Tonnage Index"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("macro.fred_macro", scope=Scope.SECTOR_AGGREGATE)
class FredMacro:
    """Pull each configured macro series (5y rolling when ``since`` is set)."""

    source_id = "macro.fred_macro"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("FRED_API_KEY", "")
        for series_id, label, desc in SERIES:
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
                    extra={"series_id": series_id, "label": label, "description": desc},
                ),
            )
