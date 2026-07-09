"""BEA (spec §4): GDP, industry value-added (API, free key)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Bea", "parse"]

BASE = "https://apps.bea.gov/api/data"

DATASETS: tuple[tuple[str, str], ...] = (
    ("NIPA", "GDP"),
    ("GDPbyIndustry", "industry_value_added"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("macro.bea", scope=Scope.SECTOR_AGGREGATE)
class Bea:
    """Pull BEA GDP and industry value-added datasets."""

    source_id = "macro.bea"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        user_id = os.environ.get("BEA_API_KEY", "")
        for dataset, label in DATASETS:
            params: dict[str, str | int] = {
                "UserID": user_id,
                "method": "GetData",
                "DatasetName": dataset,
                "TableName": "T10101",
                "Year": "ALL",
                "ResultFormat": "JSON",
            }
            raw = ctx.http.get_json(BASE, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.url = BASE
                spec.extra = {"dataset": dataset, "label": label, "note": "verify_table"}
                yield build_record(ctx, self.source_id, self.source_type, spec)
