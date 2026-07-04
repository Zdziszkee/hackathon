"""World Bank Debarred Firms & Individuals (spec §2): bulk file."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["WorldBankDebarred"]

URL = (
    "https://www.worldbank.org/content/dam/Worldbank/docsite/DebarredFirmsSupplierJsonSanctions.xml"
)


@register_source("sanctions.world_bank_debarred")
class WorldBankDebarred:
    """Record the World Bank debarred-firms file manifest."""

    source_id = "sanctions.world_bank_debarred"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": URL, "format": "xml"},
                raw_format=RawFormat.XML,
                url=URL,
                extra={"note": "bytes_not_persisted_in_jsonl"},
            ),
        )
