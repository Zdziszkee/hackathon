"""OpenCorporates (spec §12): company registry, officers/subsidiaries (free tier)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Opencorporates", "parse"]

BASE = "https://api.opencorporates.com/v0.4/companies/search"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    results = raw.get("results") if isinstance(raw, dict) else None
    companies = results.get("companies") if isinstance(results, dict) else None
    items = companies if isinstance(companies, list) else []
    return [RecordInput(payload={"company": c}, raw_format=RawFormat.JSON) for c in items]


@register_source("identity.opencorporates")
class Opencorporates:
    """Per-entity company/officers search (free tier, rate-limited)."""

    source_id = "identity.opencorporates"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        token = os.environ.get("OPENCORPORATES_API_TOKEN", "")
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            params: dict[str, str | int] = {"q": entity.name, "jurisdiction_code": "us"}
            if token:
                params["api_token"] = token
            raw = ctx.http.get_json(BASE, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = BASE
                yield build_record(ctx, self.source_id, self.source_type, spec)
