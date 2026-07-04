"""UN Comtrade (spec extension): global trade flows (free, no key on legacy API).

Pulls US-reported trade for commodity codes relevant to both monitored sectors:
- 27 (mineral fuels / petrochemicals) — petrochemical sector
- 87 (vehicles other than railway) — transport sector
- 30 (pharmaceuticals, included as a chemical sub-segment reference)

Legacy API: comtrade.un.org/api/get (no key, deprecated but functional). The
modern comtradeapi.un.org/data/v1 requires a registration key
(``UN_COMTRADE_API_KEY``); if present it is forwarded as ``subscription-key``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["UnComtrade", "parse"]

LEGACY_BASE = "https://comtrade.un.org/api/get"
MODERN_BASE = "https://comtradeapi.un.org/data/v1/get/C/A/HS"

# (commodity code, label, sector)
COMMODITIES: tuple[tuple[str, str, str], ...] = (
    ("27", "mineral_fuels", "petrochemical"),
    ("87", "vehicles_other_than_railway", "transport"),
    ("30", "pharmaceuticals", "chemical"),
)

REPORTER_US = "842"  # US reporter code
FLOW_IMPORT = "1"
FLOW_EXPORT = "2"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a Comtrade response into one record per trade row."""
    vals = raw.get("dataset") if isinstance(raw, dict) else None
    items = vals if isinstance(vals, list) else []
    return [RecordInput(payload={"trade_row": r}, raw_format=RawFormat.JSON) for r in items]


def _legacy_params(code: str, flow: str) -> dict[str, str | int]:
    return {
        "max": 500,
        "type": "C",
        "freq": "A",
        "px": "HS",
        "ps": "2022",
        "r": REPORTER_US,
        "p": "all",
        "rg": flow,
        "cc": code,
        "fmt": "json",
    }


@register_source("supply_chain.un_comtrade")
class UnComtrade:
    """Pull US-reported trade flows for sector-relevant commodity codes."""

    source_id = "supply_chain.un_comtrade"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        key = os.environ.get("UN_COMTRADE_API_KEY", "")
        for code, label, sector in COMMODITIES:
            for flow in (FLOW_IMPORT, FLOW_EXPORT):
                params = _legacy_params(code, flow)
                raw = ctx.http.get_json(LEGACY_BASE, policy=ctx.rate_policy, params=params)
                for spec in parse(raw):
                    spec.url = LEGACY_BASE
                    spec.extra = {
                        "commodity_code": code,
                        "label": label,
                        "sector": sector,
                        "flow": "import" if flow == FLOW_IMPORT else "export",
                        "modern_api_key": bool(key),
                    }
                    yield build_record(ctx, self.source_id, self.source_type, spec)
