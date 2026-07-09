"""FMCSA Licensing & Insurance / INSHIST (spec §6): bulk file."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fmcsa

__all__ = ["FmcsaLiInsurance"]


@register_source(
    "transport.fmcsa_li_insurance",
    scope=Scope.MANIFEST,
)
class FmcsaLiInsurance:
    """Record the FMCSA L&I bulk-file manifest."""

    source_id = "transport.fmcsa_li_insurance"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        url = fmcsa.census_url(fmcsa.BULK_FILES["li_insurance"])
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"url": url},
                raw_format=RawFormat.CSV,
                url=url,
                extra={"note": "bytes_not_persisted_in_jsonl"},
            ),
        )
