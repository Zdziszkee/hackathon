"""PHMSA pipeline & hazmat incident data (spec §7): bulk file."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["PhmsaPipeline"]

URL = (
    "https://www.phmsa.dot.gov/sites/phmsa.dot.gov/files/data_downloads/"
    "Annual hazardous liquid accidents 2010-present.zip"
)


@register_source(
    "petrochem.phmsa_pipeline",
    scope=Scope.MANIFEST,
)
class PhmsaPipeline:
    """Record the PHMSA pipeline/hazmat incident bulk-file manifest."""

    source_id = "petrochem.phmsa_pipeline"
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
