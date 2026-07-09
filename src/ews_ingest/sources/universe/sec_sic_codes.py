"""SEC SIC code list (spec §13 extension): industry classification crosswalk.

Scrape the SEC SIC code table at sec.gov/info/edgar/siccodes.htm (SEC_USER_AGENT
required). Each SIC code maps to an industry; used to crosswalk filers to
sectors and normalize SEC filings to a common industry taxonomy.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["SecSicCodes", "parse"]

URL = "https://www.sec.gov/info/edgar/siccodes.htm"
ROW_SELECTOR = "table tr"


def _cell_text(node: object) -> str:
    text = getattr(node, "text", "")
    return str(text).strip() if text else ""


def parse(adaptor: object) -> list[RecordInput]:
    """Extract SIC code rows from the SEC SIC table page."""
    css = getattr(adaptor, "css", None)
    if css is None:
        return []
    out: list[RecordInput] = []
    min_cells_sic = 3
    for row in css(ROW_SELECTOR):
        cells = row.css("td") if hasattr(row, "css") else []
        if len(cells) < min_cells_sic:
            continue
        sic = _cell_text(cells[0])
        office = _cell_text(cells[1])
        industry = _cell_text(cells[2])
        if not sic.isdigit():
            continue
        out.append(
            RecordInput(
                payload={"sic_code": sic, "office": office, "industry": industry},
                raw_format=RawFormat.HTML,
            )
        )
    return out


@register_source(
    "universe.sec_sic_codes",
    scope=Scope.SECTOR_AGGREGATE,
)
class SecSicCodes:
    """Scrape the SEC SIC code list for industry classification."""

    source_id = "universe.sec_sic_codes"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        # HttpClient auto-injects SEC_USER_AGENT for sec.gov URLs.
        adaptor = ctx.scraper.fetch_html(URL, policy=ctx.rate_policy)
        for spec in parse(adaptor):
            spec.url = URL
            yield build_record(ctx, self.source_id, self.source_type, spec)
