"""Company IR sites (spec §2): press releases/decks (Scrape)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["CompanyIr"]

SELECTOR = "a, .press-release, .press-release-list li"


def parse(adaptor: object) -> list[RecordInput]:
    """Extract press-release link anchors from a parsed IR page."""
    out: list[RecordInput] = []
    css = getattr(adaptor, "css", None)
    if css is None:
        return out
    for node in css(SELECTOR):
        text = getattr(node, "text", "")
        attrib = getattr(node, "attrib", {}) or {}
        href = attrib.get("href") if isinstance(attrib, dict) else None
        if not href and not text:
            continue
        out.append(
            RecordInput(
                payload={"anchor_text": str(text), "href": href},
                raw_format=RawFormat.HTML,
            )
        )
    return out


@register_source("news.company_ir")
class CompanyIr:
    """Scrape each seeded entity's IR page when ``ir_url`` is provided."""

    source_id = "news.company_ir"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            ir_url = entity.extra_ids.get("ir_url")
            if not ir_url:
                continue
            adaptor = ctx.scraper.fetch_html(ir_url, policy=ctx.rate_policy)
            for spec in parse(adaptor):
                spec.entities = [entity]
                spec.url = ir_url
                yield build_record(ctx, self.source_id, self.source_type, spec)
