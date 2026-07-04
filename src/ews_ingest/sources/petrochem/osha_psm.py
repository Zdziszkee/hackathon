"""OSHA enforcement / PSM citations (spec §7): bulk file."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["OshaPsm"]

URL = "https://www.osha.gov/establishment/search/Inspection-Data-All-Citations.csv"


@register_source("petrochem.osha_psm")
class OshaPsm:
    """Record the OSHA enforcement / PSM citation bulk-file manifest."""

    source_id = "petrochem.osha_psm"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": URL, "filter": "NAICS 325, process safety management"},
                raw_format=RawFormat.CSV,
                url=URL,
                extra={"note": "bytes_not_persisted_in_jsonl, verify_url"},
            ),
        )
