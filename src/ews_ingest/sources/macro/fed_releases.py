"""Fed H.15/G.17 releases (spec §4): rates and industrial production releases (no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["FedReleases", "parse"]

RELEASES: tuple[tuple[str, str], ...] = (
    ("https://www.federalreserve.gov/datadownload/Output/csvData/FED-H15/h15.csv", "H15"),
    ("https://www.federalreserve.gov/datadownload/Output/csvData/FED-G17/g17.csv", "G17"),
)


def parse(text: str) -> list[RecordInput]:
    """Wrap a release CSV body as one record."""
    return [RecordInput(payload={"csv": text}, raw_format=RawFormat.CSV)]


@register_source("macro.fed_releases")
class FedReleases:
    """Fetch Fed H.15 / G.17 release CSVs (best-effort endpoints)."""

    source_id = "macro.fed_releases"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for url, label in RELEASES:
            text = ctx.http.get_text(url, policy=ctx.rate_policy)
            for spec in parse(text):
                spec.url = url
                spec.extra = {"release": label, "note": "verify_endpoint"}
                yield build_record(ctx, self.source_id, self.source_type, spec)
