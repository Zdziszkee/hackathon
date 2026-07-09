"""ATA Truck Tonnage Index (spec §6): headline only (Scrape, press release)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["AtaTonnage", "parse"]

URL = "https://www.trucking.org/economics-and-industry-data"


def parse(text: str) -> list[RecordInput]:
    return [RecordInput(payload={"page_text": text[:5000]}, raw_format=RawFormat.HTML)]


@register_source(
    "transport.ata_tonnage",
    scope=Scope.SECTOR_AGGREGATE,
)
class AtaTonnage:
    """Scrape the ATA Truck Tonnage Index press-release headline."""

    source_id = "transport.ata_tonnage"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        text = ctx.http.get_text(URL, policy=ctx.rate_policy)
        for spec in parse(text):
            spec.url = URL
            yield build_record(ctx, self.source_id, self.source_type, spec)
