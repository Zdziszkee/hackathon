"""OFAC SDN/Consolidated List (spec §2): primary US sanctions bulk file.

No key. Bulk files (sdn.csv, add.csv, alt.csv) distributed as a dated zip from
``https://www.treasury.gov/ofac/downloads/sdn.zip`` containing CSVs. Only the
manifest is persisted (JSONL landing); row-level screening is deferred.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["OfacSdn"]

URL = "https://www.treasury.gov/ofac/downloads/sdn.zip"


@register_source("sanctions.ofac_sdn")
class OfacSdn:
    """Record OFAC SDN bulk-file manifest (rows parsed later)."""

    source_id = "sanctions.ofac_sdn"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": URL, "files": ["sdn.csv", "add.csv", "alt.csv"]},
                raw_format=RawFormat.CSV,
                url=URL,
                extra={"note": "bytes_not_persisted_in_jsonl"},
            ),
        )
