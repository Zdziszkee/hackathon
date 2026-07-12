"""Hacker News (Algolia Search API) — free, no key, per-entity story search.

Replaces / supplements ``news.gdelt`` (which GDELT rate-limits aggressively) for
the dashboard's news-sentiment signal. Stories are scored locally with VADER so
the dashboard can show a real ``tone`` number without depending on a per-doc
provider.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import hackernews as api

__all__ = ["HackerNews", "parse"]


def _entity_query(name: str, ticker: str | None = None) -> str:
    """Build a focused query.

    HN Algolia's default endpoint searches story titles + text. Using
    ``OR`` between terms forces the API to also return comments, which
    don't carry their own sentiment text — so we just use the most
    distinctive single term (ticker first, then a cleaned name).
    """
    if ticker:
        return ticker
    if name:
        # Strip common corporate suffixes so "Amazon.com, Inc." -> "Amazon".
        cleaned = name.split(",", maxsplit=1)[0]
        for suffix in (" Inc", " Corp"):
            cleaned = cleaned.split(suffix, maxsplit=1)[0]
        cleaned = cleaned.strip()
        if cleaned:
            return cleaned
    return name


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """One record per *story* hit; comments filtered out (they reuse the
    parent story's title via ``story_title`` which is noise for sentiment).
    Payload carries the fields the signal needs.
    """
    hits = raw.get("hits") if isinstance(raw, dict) else None
    items = hits if isinstance(hits, list) else []
    out: list[RecordInput] = []
    for h in items:
        if not isinstance(h, dict):
            continue
        tags = h.get("_tags")
        if isinstance(tags, list) and "story" not in tags:
            # Skip comments; they don't carry their own sentiment text.
            continue
        title = h.get("title") or ""
        if not title:
            continue
        out.append(
            RecordInput(
                payload={
                    "title": title,
                    "story_text": h.get("story_text") or "",
                    "url": h.get("url") or "",
                    "points": h.get("points") or 0,
                    "num_comments": h.get("num_comments") or 0,
                    "created_at": h.get("created_at") or "",
                    "objectID": h.get("objectID") or "",
                },
                raw_format=RawFormat.JSON,
            )
        )
    return out


@register_source("news.hackernews", scope=Scope.PER_ENTITY)
class HackerNews:
    """Per-entity Hacker News story search (Algolia, free, no key)."""

    source_id = "news.hackernews"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name and not entity.ticker:
                continue
            query = _entity_query(entity.name or "", entity.ticker)
            url = f"{api.BASE}/search"
            try:
                raw = api.search(
                    ctx.http, ctx.rate_policy, query=query, hits_per_page=50, days_back=365
                )
            except Exception as exc:
                ctx.logger.warning("hn query failed: %s err=%s", query[:60], exc)
                continue
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
