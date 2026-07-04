"""Bluesky / AT Protocol (spec §2): public post search (no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Bluesky", "parse"]

SEARCH_URL = "https://public.api.bsky.app/xrpc/app.bsky.actor.search"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract actors from a Bluesky search response."""
    actors = raw.get("actors") if isinstance(raw, dict) else None
    out: list[RecordInput] = []
    for actor in actors if isinstance(actors, list) else []:
        handle = actor.get("handle") if isinstance(actor, dict) else None
        desc = actor.get("description") if isinstance(actor, dict) else None
        out.append(
            RecordInput(payload={"handle": handle, "description": desc}, raw_format=RawFormat.JSON)
        )
    return out


@register_source("news.bluesky")
class Bluesky:
    """Per-entity actor search on the Bluesky public API."""

    source_id = "news.bluesky"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            url = SEARCH_URL
            params = {"q": entity.name, "limit": 25}
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
