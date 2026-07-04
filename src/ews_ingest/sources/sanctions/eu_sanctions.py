"""EU Financial Sanctions Files (spec §2): bulk XML."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["EuSanctions"]

URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctions/1/content/download"


@register_source("sanctions.eu_sanctions")
class EuSanctions:
    """Record the EU financial sanctions file manifest."""

    source_id = "sanctions.eu_sanctions"
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
