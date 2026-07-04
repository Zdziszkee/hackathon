"""U.S. Chemical Safety Board investigation reports (spec §7): Scrape, PDF."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["CsbReports", "parse"]

URL = "https://www.csb.gov/investigations/"
LINK_SELECTOR = "a"


def parse(adaptor: object) -> list[RecordInput]:
    """Extract investigation-report links from the CSB investigations index."""
    css = getattr(adaptor, "css", None)
    if css is None:
        return []
    out: list[RecordInput] = []
    for node in css(LINK_SELECTOR):
        text = str(getattr(node, "text", "") or "")
        attrib = getattr(node, "attrib", {}) or {}
        href = attrib.get("href") if isinstance(attrib, dict) else None
        if not href or "investigation" not in (href + text).lower():
            continue
        out.append(
            RecordInput(
                payload={"title": text, "href": href},
                raw_format=RawFormat.HTML,
            )
        )
    return out


@register_source("petrochem.csb_reports")
class CsbReports:
    """Scrape the CSB investigation-reports index for report links/PDFs."""

    source_id = "petrochem.csb_reports"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        adaptor = ctx.scraper.fetch_html(URL, policy=ctx.rate_policy)
        for spec in parse(adaptor):
            spec.url = URL
            yield build_record(ctx, self.source_id, self.source_type, spec)
