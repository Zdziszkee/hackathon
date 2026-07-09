"""USACE Navigation Data Center (spec §6): barge/lock tonnage, Gulf/Mississippi (bulk)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["UsaceNav"]

URL = "https://navigationdatacenter.us/data/DataDictionary/Commodity/COMMODITY_SUMMARIES.zip"


@register_source(
    "transport.usace_nav",
    scope=Scope.MANIFEST,
)
class UsaceNav:
    """Record the USACE navigation (barge/lock tonnage) bulk-file manifest."""

    source_id = "transport.usace_nav"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": URL, "format": "zip"},
                raw_format=RawFormat.CSV,
                url=URL,
                extra={"note": "bytes_not_persisted_in_jsonl, verify_url"},
            ),
        )
