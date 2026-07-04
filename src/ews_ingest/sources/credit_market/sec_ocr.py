"""SEC Office of Credit Ratings, Form NRSRO Exhibits (spec §3): bulk PDF manifest."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["SecOcr"]

BASE = "https://www.sec.gov/page/creditratingagencyfilings"


@register_source("credit_market.sec_ocr")
class SecOcr:
    """Record the SEC OCR NRSRO exhibit file manifest."""

    source_id = "credit_market.sec_ocr"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": BASE, "format": "pdf"},
                raw_format=RawFormat.PDF,
                url=BASE,
                extra={"note": "bytes_not_persisted_in_jsonl"},
            ),
        )
