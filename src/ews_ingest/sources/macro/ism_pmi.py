"""ISM Manufacturing/Services PMI (spec §4): headline number only (Scrape)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["IsmPmi", "parse"]

URL = "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/"


def parse(text: str) -> list[RecordInput]:
    """Wrap the ISM report page text as one record (headline PMI parsed later)."""
    return [RecordInput(payload={"page_text": text[:5000]}, raw_format=RawFormat.HTML)]


@register_source("macro.ism_pmi")
class IsmPmi:
    """Scrape the ISM Report on Business landing page for headline PMI."""

    source_id = "macro.ism_pmi"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        text = ctx.http.get_text(URL, policy=ctx.rate_policy)
        for spec in parse(text):
            spec.url = URL
            yield build_record(ctx, self.source_id, self.source_type, spec)
