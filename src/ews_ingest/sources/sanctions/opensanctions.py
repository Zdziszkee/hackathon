"""OpenSanctions (spec §2): aggregator of sanctions + PEP data (free key, non-commercial)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Opensanctions", "parse"]

BASE = "https://data.opensanctions.org"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract matched entities from an OpenSanctions search response."""
    results = raw.get("results") if isinstance(raw, dict) else None
    items = results if isinstance(results, list) else []
    return [RecordInput(payload={"match": r}, raw_format=RawFormat.JSON) for r in items]


@register_source("sanctions.opensanctions")
class Opensanctions:
    """Per-entity sanctions/PEP name search via OpenSanctions."""

    source_id = "sanctions.opensanctions"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("OPENSANCTIONS_API_KEY", "")
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            url = f"{BASE}s/search/default"
            params: dict[str, str | int] = {"q": entity.name}
            if api_key:
                params["api_key"] = api_key
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
