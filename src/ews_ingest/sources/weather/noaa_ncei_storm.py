"""NOAA NCEI Storm Events / Billion-Dollar Disasters (spec §8): bulk file."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["NoaaNceiStorm"]

URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"


@register_source("weather.noaa_ncei_storm")
class NoaaNceiStorm:
    """Record the NCEI Storm Events bulk-file index manifest."""

    source_id = "weather.noaa_ncei_storm"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"index_url": URL, "datasets": ["details", "fatalities", "locations"]},
                raw_format=RawFormat.CSV,
                url=URL,
                extra={"note": "bytes_not_persisted_in_jsonl"},
            ),
        )
