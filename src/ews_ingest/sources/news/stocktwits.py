"""Stocktwits API (spec §2): ticker sentiment (free key, rate-limited)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Stocktwits", "parse"]

BASE = "https://api.stocktwits.com/api/2"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract messages from a Stocktwits symbol stream response."""
    out: list[RecordInput] = []
    messages = raw.get("messages") if isinstance(raw, dict) else None
    for m in messages if isinstance(messages, list) else []:
        body = m.get("body") if isinstance(m, dict) else None
        sentiment = None
        entities = m.get("entities") if isinstance(m, dict) else None
        if isinstance(entities, dict):
            sent = entities.get("sentiment")
            sentiment = sent.get("basic") if isinstance(sent, dict) else None
        out.append(
            RecordInput(
                payload={"body": body, "sentiment": sentiment},
                raw_format=RawFormat.JSON,
            )
        )
    return out


@register_source("news.stocktwits")
class Stocktwits:
    """Per-ticker message/sentiment stream."""

    source_id = "news.stocktwits"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        token = os.environ.get("STOCKTWITS_ACCESS_TOKEN", "")
        for entity in ctx.resolver.all():
            if not entity.ticker:
                continue
            url = f"{BASE}/streams/symbol/{entity.ticker}.json"
            params: dict[str, str | int] = {"limit": 30}
            if token:
                params["access_token"] = token
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params or None)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
