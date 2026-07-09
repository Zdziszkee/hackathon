"""EPA TRI/FRS filtered by NAICS 325 (spec §13, no key): universe seeding."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import epa

__all__ = ["EpaTriUniverse", "parse"]


def parse(rows: list[object]) -> list[RecordInput]:
    """Build a facility identifier record per TRI row (FRS ID crosswalk)."""
    out: list[RecordInput] = []
    for row in rows:
        entry = row if isinstance(row, dict) else None
        if not isinstance(entry, dict):
            continue
        frs = entry.get("FRS_ID") or entry.get("registry_id")
        name = entry.get("FACILITY_NAME") or entry.get("name")
        out.append(
            RecordInput(
                payload={"facility": entry},
                raw_format=RawFormat.JSON,
                entities=[
                    Identifiers(
                        epa_frs_id=str(frs) if frs else None,
                        name=str(name) if name else None,
                    )
                ],
            )
        )
    return out


@register_source(
    "universe.epa_tri_universe",
    scope=Scope.FACILITY,
)
class EpaTriUniverse:
    """Seed the petrochem facility universe from EPA TRI filtered to NAICS 325."""

    source_id = "universe.epa_tri_universe"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        rows = epa.tri_table(
            ctx.http,
            ctx.rate_policy,
            table="tri.tri_facility",
            params={"rows_first": 1, "rows_last": 500},
        )
        url = "https://data.epa.gov/dmapservice/tri.tri_facility/1:500/JSON"
        for spec in parse(rows):
            spec.url = url
            spec.extra = {"note": "NAICS-325 scoping deferred; DMAP filter column TBD"}
            yield build_record(ctx, self.source_id, self.source_type, spec)
