"""FINRA TRACE (spec §3): corporate bond price/yield/volume, delayed (free key)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["FinraTrace", "parse"]

BASE = "https://api.finra.org/data/group/traceIdentifier"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap a TRACE response as one record."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("credit_market.finra_trace", scope=Scope.PER_ENTITY)
class FinraTrace:
    """Per-ticker corporate-bond TRACE aggregates (delayed)."""

    source_id = "credit_market.finra_trace"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("FINRA_API_KEY", "")
        headers: dict[str, str] | None = {"Authorization": f"Bearer {api_key}"} if api_key else None
        for entity in ctx.resolver.all():
            if not entity.ticker:
                continue
            url = BASE
            try:
                raw = ctx.http.get_json(url, policy=ctx.rate_policy, headers=headers)
                for spec in parse(raw):
                    spec.entities = [entity]
                    spec.url = url
                    spec.extra = {"ticker": entity.ticker, "note": "verify_endpoint"}
                    yield build_record(ctx, self.source_id, self.source_type, spec)
            except Exception as exc:
                ctx.logger.warning("finra_trace failed for %s: %s", entity.ticker, exc)
                continue
