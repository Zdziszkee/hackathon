"""CourtListener / RECAP Archive (spec §11): free PACER mirror. Check first."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Courtlistener", "parse"]

BASE = "https://www.courtlistener.com/api/rest-v4"
DOCKETS = f"{BASE}/dockets/"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a dockets search response into one record per docket."""
    results = raw.get("results") if isinstance(raw, dict) else None
    items = results if isinstance(results, list) else []
    return [RecordInput(payload={"docket": r}, raw_format=RawFormat.JSON) for r in items]


def _query(text: str) -> str:
    return text.replace(" ", "+")


@register_source(
    "default_truth.courtlistener",
    scope=Scope.PER_ENTITY,
)
class Courtlistener:
    """Per-entity bankruptcy/docket search via CourtListener RECAP."""

    source_id = "default_truth.courtlistener"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        token = os.environ.get("COURTLISTENER_API_KEY", "")
        headers = {"Authorization": f"Token {token}"} if token else None
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            params: dict[str, str | int] = {
                "q": _query(entity.name),
                "type": "d",
                "court": "bankr",
                "order_by": "score desc",
            }
            raw = ctx.http.get_json(DOCKETS, policy=ctx.rate_policy, params=params, headers=headers)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = DOCKETS
                yield build_record(ctx, self.source_id, self.source_type, spec)
