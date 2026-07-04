"""EPA TRI (spec §7): facility-level chemical releases (API, no key). NAICS 325."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import epa

__all__ = ["EpaTri", "parse"]


def parse(rows: list[object]) -> list[RecordInput]:
    return [RecordInput(payload={"release": r}, raw_format=RawFormat.JSON) for r in rows]


@register_source("petrochem.epa_tri")
class EpaTri:
    """Pull EPA TRI release rows for NAICS 325 facilities."""

    source_id = "petrochem.epa_tri"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        rows = epa.tri_table(
            ctx.http,
            ctx.rate_policy,
            table="tri.tri_facility",
            params={"rows_first": 1, "rows_last": 100},
        )
        for spec in parse(rows):
            spec.url = "https://data.epa.gov/dmapservice/tri.tri_facility/1:100/JSON"
            spec.extra = {"note": "NAICS-325 scoping deferred; DMAP filter column TBD"}
            yield build_record(ctx, self.source_id, self.source_type, spec)
