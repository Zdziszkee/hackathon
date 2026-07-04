"""World Bank Commodity Pink Sheet (spec §5): fertilizer & cereal prices (bulk)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["WorldbankPinksheet"]

URL = "https://www.worldbank.org/content/dam/Worldbank/Indicators/Prices/Pink_Sheet/Pink_Data.xlsx"


@register_source("commodity.worldbank_pinksheet")
class WorldbankPinksheet:
    """Record the World Bank Pink Sheet bulk-file manifest (xlsx)."""

    source_id = "commodity.worldbank_pinksheet"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": URL, "format": "xlsx"},
                raw_format=RawFormat.CSV,
                url=URL,
                extra={"note": "bytes_not_persisted_in_jsonl, verify_url"},
            ),
        )
