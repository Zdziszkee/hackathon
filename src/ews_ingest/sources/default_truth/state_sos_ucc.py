"""State Secretary of State — UCC lien filings & dissolution records (spec §11, Scrape)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["StateSosUcc", "parse"]

# Generic public-records search portals; formats vary by state.
PORTALS: tuple[str, ...] = (
    "https://direct.sos.state.tx.us/ucc/",
    "https://bsd.sos.state.or.us/ucc/",
    "https://corp.sec.state.ma.us/uccweb/",
)

LINK_SELECTOR = "a"


def parse(text: str) -> list[RecordInput]:
    """Wrap a state SoS UCC search page as one record (table parse deferred)."""
    return [RecordInput(payload={"page_text": text[:5000]}, raw_format=RawFormat.HTML)]


@register_source("default_truth.state_sos_ucc")
class StateSosUcc:
    """Scrape state SoS UCC search portals (format varies; per-state adapters later)."""

    source_id = "default_truth.state_sos_ucc"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for portal in PORTALS:
            text = ctx.http.get_text(portal, policy=ctx.rate_policy)
            for spec in parse(text):
                spec.url = portal
                yield build_record(ctx, self.source_id, self.source_type, spec)
