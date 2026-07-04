"""FMCSA Census filtered by NAICS 484 (spec §13): transport universe seeding.

Reuses the census CSV parse (NAICS-484 property carriers) so the seeded
transport universe is consistent with the §6 census ingest.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fmcsa

__all__ = ["FmcsaCensusUniverse", "parse"]

CENSUS_FILE = "CENSUS_Property.csv"
NAICS_PREFIX = "484"

# Universe seeding keeps only carriers with a recent record.
COL_USDOT = "USDOT_NUMBER"
COL_NAME = "NAME"
COL_NAICS = "NAICS_CODE"

_SEED_LIMIT = 1000


def _str(cell: object) -> str:
    return str(cell).strip() if cell is not None else ""


def parse(text: str, limit: int = _SEED_LIMIT) -> list[RecordInput]:
    """Parse census rows into a seeded USDOT-identifier universe (NAICS 484)."""
    reader = csv.DictReader(io.StringIO(text))
    out: list[RecordInput] = []
    for row in reader:
        naics = _str(row.get(COL_NAICS))
        if not naics.startswith(NAICS_PREFIX):
            continue
        usdot = _str(row.get(COL_USDOT))
        name = _str(row.get(COL_NAME)) or None
        if not usdot:
            continue
        out.append(
            RecordInput(
                payload={"usdot": usdot, "name": name, "naics": naics},
                raw_format=RawFormat.JSON,
                entities=[Identifiers(usdot=usdot, name=name)],
            )
        )
        if len(out) >= limit:
            break
    return out


@register_source("universe.fmcsa_census_universe")
class FmcsaCensusUniverse:
    """Seed the transport universe from the FMCSA census (NAICS 484, limited)."""

    source_id = "universe.fmcsa_census_universe"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        url = fmcsa.census_url(CENSUS_FILE)
        text = ctx.http.get_text(url, policy=ctx.rate_policy)
        for spec in parse(text):
            spec.url = url
            yield build_record(ctx, self.source_id, self.source_type, spec)
