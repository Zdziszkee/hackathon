"""IMF Primary Commodity Price System (spec §5): bulk commodity prices (no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["ImfPcps", "parse"]

BASE = "https://www.imf.org/external/np/res/commod/External_Data.xlsx"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("commodity.imf_pcps")
class ImfPcps:
    """Record the IMF Primary Commodity Price bulk-file manifest."""

    source_id = "commodity.imf_pcps"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": BASE, "format": "xlsx"},
                raw_format=RawFormat.CSV,
                url=BASE,
                extra={"note": "bytes_not_persisted_in_jsonl, verify_url"},
            ),
        )
