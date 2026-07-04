"""BLS PPI (spec §10): Petrochemical Manufacturing (325110), General Freight (484121)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import bls

__all__ = ["BlsPpi", "parse"]


def parse(raw: dict[str, object]) -> list[RecordInput]:
    results = raw.get("Results") if isinstance(raw, dict) else None
    series_list = results.get("series") if isinstance(results, dict) else None
    items = series_list if isinstance(series_list, list) else []
    return [RecordInput(payload={"series": s}, raw_format=RawFormat.JSON) for s in items]


@register_source("pricing.bls_ppi")
class BlsPpi:
    """Pull PPI for petrochem (325110) and general freight trucking (484121)."""

    source_id = "pricing.bls_ppi"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        start_year = str(ctx.since.year) if ctx.since is not None else None
        for label, series_id in bls.PPI_SERIES.items():
            raw = bls.series_data(
                ctx.http,
                ctx.rate_policy,
                series_id=series_id,
                start_year=start_year,
                end_year=start_year,
            )
            for spec in parse(raw):
                spec.url = "https://api.bls.gov/publicAPI/v2/timeseries/data"
                spec.extra = {"series_id": series_id, "label": label}
                yield build_record(ctx, self.source_id, self.source_type, spec)
