"""NAICS code definitions (spec §13 extension): census.gov industry taxonomy.

Pulls the Census Bureau NAICS sector definitions (the authoritative US industry
classification). Crosswalks NAICS 325 / 484 to human-readable sectors and seeds
the industry classification universe. No key required for the definitions page.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["NaicsCensus", "parse"]

URL = "https://www.census.gov/naics/"
ROW_SELECTOR = "table tr"

# NAICS 2022 sector prefixes of interest.
SECTORS: tuple[str, ...] = (
    "31-33",
    "42",
    "44-45",
    "48-49",
    "51",
    "52",
    "54",
    "31",
    "32",
    "33",
    "48",
    "49",
    "325",
    "484",
)


def _cell_text(node: object) -> str:
    text = getattr(node, "text", "")
    return str(text).strip() if text else ""


def parse(adaptor: object) -> list[RecordInput]:
    """Extract NAICS code/title rows from the Census NAICS definitions page."""
    css = getattr(adaptor, "css", None)
    if css is None:
        return []
    out: list[RecordInput] = []
    min_cells_naics = 2
    for row in css(ROW_SELECTOR):
        cells = row.css("td") if hasattr(row, "css") else []
        if len(cells) < min_cells_naics:
            continue
        code = _cell_text(cells[0])
        title = _cell_text(cells[1])
        if not code:
            continue
        out.append(
            RecordInput(
                payload={"naics_code": code, "title": title},
                raw_format=RawFormat.HTML,
            )
        )
    return out


@register_source("universe.naics_census")
class NaicsCensus:
    """Scrape Census NAICS definitions for the industry classification universe."""

    source_id = "universe.naics_census"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        adaptor = ctx.scraper.fetch_html(URL, policy=ctx.rate_policy)
        for spec in parse(adaptor):
            spec.url = URL
            yield build_record(ctx, self.source_id, self.source_type, spec)
