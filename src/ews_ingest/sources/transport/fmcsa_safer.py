"""FMCSA SAFER Company Snapshot (spec §6): per-USDOT carrier profile (Scrape)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fmcsa

__all__ = ["FmcsaSafer", "parse"]

SELECTOR = "table"


def parse(adaptor: object) -> list[RecordInput]:
    """Extract raw HTML tables from a SAFER snapshot page."""
    css = getattr(adaptor, "css", None)
    if css is None:
        return []
    tables = css(SELECTOR)
    html = "".join(getattr(t, "html", "") for t in tables) if tables else ""
    return [RecordInput(payload={"html": html}, raw_format=RawFormat.HTML)]


@register_source("transport.fmcsa_safer")
class FmcsaSafer:
    """Per-USDOT SAFER Company Snapshot scrape."""

    source_id = "transport.fmcsa_safer"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.usdot:
                continue
            url = fmcsa.safer_snapshot_url(entity.usdot)
            adaptor = ctx.scraper.fetch_html(url, policy=ctx.rate_policy)
            for spec in parse(adaptor):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
