"""FMCSA Company Census File (spec §6): bulk, filtered to NAICS 484. High-value.

Row-level ingestion: fetch the property-carrier census CSV, parse rows whose
NAICS starts with 484, and emit one landing record per carrier carrying its
USDOT# (cross-source identifier for later joins).
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

__all__ = ["FmcsaCensus", "parse"]

CENSUS_FILE = "CENSUS_Property.csv"
NAICS_PREFIX = "484"

# Expected header field names in the FMCSA census CSV.
COL_USDOT = "USDOT_NUMBER"
COL_NAME = "NAME"
COL_NAICS = "NAICS_CODE"


def _str(cell: object) -> str:
    return str(cell).strip() if cell is not None else ""


def parse(text: str) -> list[RecordInput]:
    """Parse the census CSV and keep NAICS-484 property carriers."""
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
    return out


@register_source("transport.fmcsa_census")
class FmcsaCensus:
    """Land NAICS-484 property carriers from the FMCSA census bulk file."""

    source_id = "transport.fmcsa_census"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        url = fmcsa.census_url(CENSUS_FILE)
        text = ctx.http.get_text(url, policy=ctx.rate_policy)
        for spec in parse(text):
            spec.url = url
            yield build_record(ctx, self.source_id, self.source_type, spec)
