"""Consolidated Screening List / trade.gov (spec §2): merged OFAC+BIS+DDTC.

Free key: CSL_API_KEY. API base: https://api.trade.gov/gateway/v1.
Per-entity fuzzy name search; results are screening hits (no financials).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["ConsolidatedScreening", "parse"]

BASE = "https://api.trade.gov/gateway/v1/csl-search"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract screening hits from a CSL response."""
    results = raw.get("results") if isinstance(raw, dict) else None
    items = results if isinstance(results, list) else []
    return [RecordInput(payload={"hit": h}, raw_format=RawFormat.JSON) for h in items]


@register_source("sanctions.consolidated_screening")
class ConsolidatedScreening:
    """Per-entity consolidated screening-list name hits."""

    source_id = "sanctions.consolidated_screening"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("CSL_API_KEY", "")
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            params: dict[str, str | int] = {"q": entity.name}
            if api_key:
                params["api_key"] = api_key
            raw = ctx.http.get_json(BASE, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = BASE
                yield build_record(ctx, self.source_id, self.source_type, spec)
