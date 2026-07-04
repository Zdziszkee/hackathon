"""Regional Fed manufacturing surveys (spec §4): Philly/NY/Dallas/Richmond/KC (no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["RegionalFed", "parse"]

SURVEYS: tuple[tuple[str, str], ...] = (
    (
        "https://www.philadelphiafed.org/-/media/frbp/data/business-outlook/sos/current.csv",
        "philly_bco",
    ),
    ("https://www.newyorkfed.org/medialibrary/media/survey/empire/pdf/empire.csv", "ny_empire"),
)


def parse(text: str) -> list[RecordInput]:
    return [RecordInput(payload={"csv": text}, raw_format=RawFormat.CSV)]


@register_source("macro.regional_fed")
class RegionalFed:
    """Fetch regional Fed manufacturing survey CSVs (best-effort endpoints)."""

    source_id = "macro.regional_fed"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for url, label in SURVEYS:
            text = ctx.http.get_text(url, policy=ctx.rate_policy)
            for spec in parse(text):
                spec.url = url
                spec.extra = {"survey": label, "note": "verify_endpoint"}
                yield build_record(ctx, self.source_id, self.source_type, spec)
