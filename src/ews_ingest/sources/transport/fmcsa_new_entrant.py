"""FMCSA New Entrant / Out-of-Service Orders / Authority Revocations (spec §6)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fmcsa

__all__ = ["FmcsaNewEntrant"]

FILES: tuple[str, ...] = ("new_entrant", "oos_orders")


@register_source("transport.fmcsa_new_entrant")
class FmcsaNewEntrant:
    """Record FMCSA new-entrant / out-of-service / authority-revocation manifests."""

    source_id = "transport.fmcsa_new_entrant"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for key in FILES:
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
