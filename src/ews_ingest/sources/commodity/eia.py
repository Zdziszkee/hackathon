"""EIA (spec §5): Brent/WTI/ULSD/jet fuel/Henry Hub/refinery utilization. High-value."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import eia as eia_api

__all__ = ["Eia", "parse"]

BASE = "https://api.eia.gov/v2"

# (route, facet series id, label). EIA v2 daily fuel-price series.
SERIES: tuple[tuple[list[str], str, str], ...] = (
    (["petroleum", "pri", "spt", "data"], "RBRTE.D", "brent_spot"),
    (["petroleum", "pri", "spt", "data"], "RWTC.D", "wti_spot"),
    (["petroleum", "pri", "spt", "data"], "D2OOULCD.D", "ulsd_diesel"),
    (["petroleum", "pri", "spt", "data"], "D2OJULCD.D", "jet_fuel"),
    (["natural-gas", "pri", "sum", "data"], "RNGWHHD.D", "henry_hub_gas"),
    (["petroleum", "sum", "snd", "data"], "WPULEUS3", "refinery_utilization"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("commodity.eia")
class Eia:
    """Pull each configured EIA daily fuel-price series (5y rolling)."""

    source_id = "commodity.eia"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("EIA_API_KEY", "")
        since = ctx.since.isoformat() if ctx.since is not None else None
        for route, series_id, label in SERIES:
            params: dict[str, str | int] = {
                "frequency": "daily",
                "facets[series][0]": series_id,
            }
            if since is not None:
                params["start"] = since
            raw = eia_api.data(
                ctx.http,
                ctx.rate_policy,
                api_key=api_key,
                route=route,
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
