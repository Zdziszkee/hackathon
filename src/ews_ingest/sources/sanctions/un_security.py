"""UN Security Council Consolidated List (spec §2): bulk XML."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["UnSecurity"]

URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"


@register_source("sanctions.un_security")
class UnSecurity:
    """Record the UN consolidated sanctions XML manifest."""

    source_id = "sanctions.un_security"
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
