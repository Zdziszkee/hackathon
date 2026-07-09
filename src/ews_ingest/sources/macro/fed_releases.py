"""Fed H.15/G.17 releases (spec §4): rates and industrial production releases (no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["FedReleases", "parse"]

RELEASES: tuple[tuple[str, str], ...] = (
    ("https://www.federalreserve.gov/releases/h15/", "H15"),
    ("https://www.federalreserve.gov/releases/g17/", "G17"),
)


def parse(text: str) -> list[RecordInput]:
    """Wrap a release HTML page as one record."""
    return [RecordInput(payload={"page_text": text[:5000]}, raw_format=RawFormat.HTML)]


@register_source("macro.fed_releases", scope=Scope.SECTOR_AGGREGATE)
class FedReleases:
    """Scrape Fed H.15 / G.17 release pages (CSV downloads discontinued)."""

    source_id = "macro.fed_releases"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for url, label in RELEASES:
            text = ctx.http.get_text(url, policy=ctx.rate_policy)
            for spec in parse(text):
                spec.url = url
                spec.extra = {"release": label}
                yield build_record(ctx, self.source_id, self.source_type, spec)
