"""FMCSA MCMIS crash & inspection public-use files (spec §6): bulk."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fmcsa

__all__ = ["FmcsaMcmis"]


@register_source(
    "transport.fmcsa_mcmis",
    scope=Scope.MANIFEST,
)
class FmcsaMcmis:
    """Record the FMCSA MCMIS crash/inspection bulk-file manifests."""

    source_id = "transport.fmcsa_mcmis"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for key in ("mcmis_crash", "mcmis_inspection"):
            url = fmcsa.census_url(fmcsa.BULK_FILES[key])
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload={"url": url, "dataset": key},
                    raw_format=RawFormat.CSV,
                    url=url,
                    extra={"note": "bytes_not_persisted_in_jsonl"},
                ),
            )
