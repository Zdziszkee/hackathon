"""Google Trends unofficial fallback (spec §2): daily trends JSON (no key).

Per-company search-interest time series requires the explore/token flow which
is fragile (spec calls pytrends "archived/unmaintained"); the robust public
endpoint is the daily-trends list. Per-company time series is a TODO.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["GoogleTrends", "parse"]

DAILY_URL = "https://trends.google.com/trends/api/dailytrends"


def parse(text: str) -> list[RecordInput]:
    """Strip the XSSI guard ``)]\\n,`` and parse the daily-trends payload."""
    body = text
    guard = body.find(",")
    if guard != -1 and body.lstrip().startswith(")"):
        body = body[guard + 1 :]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []
    trending = data.get("default", {}) if isinstance(data, dict) else {}
    days = trending.get("trendingSearchesDays") if isinstance(trending, dict) else []
    out: list[RecordInput] = []
    for day in days if isinstance(days, list) else []:
        for ts in day.get("trendingSearches", []) if isinstance(day, dict) else []:
            title = ts.get("title") if isinstance(ts, dict) else None
            out.append(
                RecordInput(
                    payload={"trend": ts if isinstance(ts, dict) else {"title": title}},
                    raw_format=RawFormat.JSON,
                )
            )
    return out


@register_source("news.google_trends")
class GoogleTrends:
    """US daily search-trend spikes (sector/keyword distress signal)."""

    source_id = "news.google_trends"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        url = f"{DAILY_URL}?hl=en-US&geo=US"
        text = ctx.http.get_text(url, policy=ctx.rate_policy)
        for spec in parse(text):
            spec.url = url
            yield build_record(ctx, self.source_id, self.source_type, spec)
