"""SEC DERA Financial Statement Data Sets (spec §1): quarterly bulk XBRL."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["SecDeraBulk"]

# Example quarterly submissions. Real filenames follow "YYYYq<q>.zip".
DERA_FILES: tuple[str, ...] = ("2024q1.zip", "2024q2.zip")


@register_source("company_financials.dera_bulk", scope=Scope.MANIFEST)
class SecDeraBulk:
    """Record metadata for each quarterly DERA bulk zip (rows parsed later)."""

    source_id = "company_financials.dera_bulk"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        # JSONL landing cannot economically hold bulk binaries; record the
        # file manifest so the feature-engineering phase can download+parse it.
        for filename in DERA_FILES:
            url = f"https://www.sec.gov/dera/data/financial-statement-data-sets/{filename}"
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload={"filename": filename, "url": url},
                    raw_format=RawFormat.CSV,
                    url=url,
                    extra={"partition_key": filename, "note": "bytes_not_persisted_in_jsonl"},
                ),
            )
