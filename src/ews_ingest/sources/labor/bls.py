"""BLS (spec §9): CES, JOLTS, QCEW (free key)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import bls

__all__ = ["Bls", "parse"]

# High-value labor series (US).
SERIES: tuple[str, ...] = (
    "CES0000000001",  # total nonfarm employment
    "JTS0000000001",  # total JOLTS (hires/separations)
    "SMU00000000000000001",  # QCEW-ish aggregate (placeholder)
    "LNS14000000",  # unemployment rate U-3
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a BLS series response into one record per data series."""
    results = raw.get("Results") if isinstance(raw, dict) else None
    series_list = results.get("series") if isinstance(results, dict) else None
    items = series_list if isinstance(series_list, list) else []
    return [RecordInput(payload={"series": s}, raw_format=RawFormat.JSON) for s in items]


@register_source("labor.bls")
class Bls:
    """Pull BLS CES/JOLTS/QCEW series for the named sectors."""

    source_id = "labor.bls"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        # BLS_API_KEY (registration key) lifts rate limits; passed via HTTP header.
        _key = os.environ.get("BLS_API_KEY", "")
        start_year = str(ctx.since.year) if ctx.since is not None else None
        for series_id in SERIES:
            raw = bls.series_data(
                ctx.http,
                ctx.rate_policy,
                series_id=series_id,
                start_year=start_year,
                end_year=start_year,
            )
            for spec in parse(raw):
                spec.url = "https://api.bls.gov/publicAPI/v2/timeseries/data"
                spec.extra = {"series_id": series_id}
                yield build_record(ctx, self.source_id, self.source_type, spec)
