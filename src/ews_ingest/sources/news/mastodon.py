"""Mastodon public API (spec §2): public post search (no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Mastodon", "parse"]

INSTANCE = "https://mastodon.social"
SEARCH_URL = f"{INSTANCE}/api/v2/search"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract statuses from a Mastodon search response."""
    statuses = raw.get("statuses") if isinstance(raw, dict) else None
    out: list[RecordInput] = []
    for stat in statuses if isinstance(statuses, list) else []:
        text = stat.get("content") if isinstance(stat, dict) else None
        created = stat.get("created_at") if isinstance(stat, dict) else None
        out.append(
            RecordInput(payload={"content": text, "created_at": created}, raw_format=RawFormat.JSON)
        )
    return out


@register_source("news.mastodon")
class Mastodon:
    """Per-entity public post search on a Mastodon instance."""

    source_id = "news.mastodon"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            params = {"q": entity.name, "type": "statuses", "limit": 20}
            raw = ctx.http.get_json(SEARCH_URL, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = SEARCH_URL
                yield build_record(ctx, self.source_id, self.source_type, spec)
