"""DOT BTS TranStats (spec §6): Form 41 Financial/Traffic, T-100 (airline RASM)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import bts

__all__ = ["BtsTranstats"]

FILES: tuple[str, ...] = ("T_SCHEDULE_T100_Domestic.zip", "T_AIRLINE_CARRIER_CODE.zip")


@register_source("transport.bts_transtats")
class BtsTranstats:
    """Record TranStats bulk-file manifests (Form 41 / T-100)."""

    source_id = "transport.bts_transtats"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for filename in FILES:
            url = bts.transtats_bulk_url(filename)
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload={"filename": filename, "url": url},
                    raw_format=RawFormat.CSV,
                    url=url,
                    extra={"note": "bytes_not_persisted_in_jsonl, verify_filename"},
                ),
            )
