"""Port congestion proxy (spec extension): World Bank Container Port Traffic (TEU).

Free, no key. Indicator ``IS.SHP.GOOD.TU`` = container port traffic in TEU,
by country/year. A sustained drop in TEU vs trend signals port congestion /
disruption. api.worldbank.org/v2.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["PortCongestion", "parse"]

BASE = "https://api.worldbank.org/v2/country/all/indicator/IS.SHP.GOOD.TU"
INDICATOR = "IS.SHP.GOOD.TU"


def parse(raw: list[object]) -> list[RecordInput]:
    """Split a World Bank response (``[meta, rows]``) into one record per row."""
    rows = raw[1] if isinstance(raw, list) and len(raw) > 1 else []
    items = rows if isinstance(rows, list) else []
    return [RecordInput(payload={"row": r}, raw_format=RawFormat.JSON) for r in items]


@register_source("supply_chain.port_congestion")
class PortCongestion:
    """Pull container port traffic (TEU) for supply-chain congestion proxy."""

    source_id = "supply_chain.port_congestion"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        params: dict[str, str | int] = {
            "format": "json",
            "date": "2018:2023",
            "per_page": 5000,
        }
        data = ctx.http.get_json_list(BASE, policy=ctx.rate_policy, params=params)
        for spec in parse(data):
            spec.url = BASE
            spec.extra = {"indicator": INDICATOR, "label": "container_port_traffic_teu"}
            yield build_record(ctx, self.source_id, self.source_type, spec)
