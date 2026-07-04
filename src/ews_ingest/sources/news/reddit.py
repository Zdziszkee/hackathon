"""Reddit Data API (spec §2): subreddit/ticker mentions via .json endpoints."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Reddit", "parse"]

TICKER_SUBS: tuple[str, ...] = ("investing", "stocks", "wallstreetbets")
UA = "ews-ingest/0.1 credit-risk research (contact@example.com)"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract listings children from a Reddit .json response."""
    out: list[RecordInput] = []
    data = raw.get("data") if isinstance(raw, dict) else None
    children = data.get("children") if isinstance(data, dict) else None
    for child in children if isinstance(children, list) else []:
        entry = child.get("data") if isinstance(child, dict) else None
        if not isinstance(entry, dict):
            entry = {}
        out.append(
            RecordInput(
                payload={
                    "title": entry.get("title"),
                    "selftext": entry.get("selftext"),
                    "subreddit": entry.get("subreddit"),
                    "created_utc": entry.get("created_utc"),
                    "score": entry.get("score"),
                },
                raw_format=RawFormat.JSON,
            )
        )
    return out


@register_source("news.reddit")
class Reddit:
    """Per-entity ticker + sector-subreddit mention search."""

    source_id = "news.reddit"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.ticker:
                continue
            for sub in TICKER_SUBS:
                url = f"https://www.reddit.com/r/{sub}/search.json"
                params = {
                    "q": entity.ticker,
                    "restrict_sr": 1,
                    "sort": "new",
                    "t": "year",
                    "limit": 25,
                }
                raw = ctx.http.get_json(
                    url, policy=ctx.rate_policy, params=params, headers={"User-Agent": UA}
                )
                for spec in parse(raw):
                    spec.entities = [entity]
                    spec.url = url
                    yield build_record(ctx, self.source_id, self.source_type, spec)
