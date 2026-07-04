"""Wikipedia sector/company lists (spec §13, Scrape)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["WikipediaLists", "parse"]

LISTS: tuple[str, ...] = (
    "https://en.wikipedia.org/wiki/List_of_publicly_traded_chemical_manufacturers",
    "https://en.wikipedia.org/wiki/List_of_trucking_companies",
)

ROW_SELECTOR = "table.wikitable tr"


def _cell(node: object) -> str:
    text = getattr(node, "text", "")
    return str(text).strip() if text else ""


def parse(adaptor: object) -> list[RecordInput]:
    css = getattr(adaptor, "css", None)
    if css is None:
        return []
    out: list[RecordInput] = []
    for row in css(ROW_SELECTOR):
        cells = row.css("td") if hasattr(row, "css") else []
        if not cells:
            continue
        texts = [_cell(c) for c in cells]
        out.append(RecordInput(payload={"row": texts}, raw_format=RawFormat.HTML))
    return out


@register_source("universe.wikipedia_lists")
class WikipediaLists:
    """Scrape wikipedia sector lists for prototype-universe seeding."""

    source_id = "universe.wikipedia_lists"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for url in LISTS:
            adaptor = ctx.scraper.fetch_html(url, policy=ctx.rate_policy)
            for spec in parse(adaptor):
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
