"""NOAA/GDACS (spec extension): Global Disaster Alerts Coordination System RSS.

Free, no key. GDACS aggregates disaster alerts (storms, earthquakes, floods,
volcanoes, droughts) with severity/impact data. RSS feed at gdacs.org/xml/rss.xml.
Gulf-Coast storm alerts hit both monitored sectors (refinery + port exposure).
"""

from __future__ import annotations

from collections.abc import Iterator

import feedparser

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["NoaaGdacs", "parse"]

URL = "https://www.gdacs.org/xml/rss.xml"


def parse(text: str) -> list[RecordInput]:
    """Parse the GDACS RSS XML body into one record per alert entry."""
    feed = feedparser.parse(text)
    out: list[RecordInput] = []
    for entry in feed.entries:
        out.append(
            RecordInput(
                payload={
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "summary": entry.get("summary"),
                    "published": entry.get("published"),
                    "gdacs_severity": entry.get("gdacs_severity"),
                    "alertlevel": (entry.get("alertlevel") or _first(entry, "alertlevel")),
                },
                raw_format=RawFormat.JSON,
            )
        )
    return out


def _first(entry: object, key: str) -> object:
    tags = getattr(entry, "tags", []) if hasattr(entry, "tags") else []
    for tag in tags if isinstance(tags, list) else []:
        term = getattr(tag, "term", None) if not isinstance(tag, dict) else tag.get("term")
        if term == key:
            return getattr(tag, "value", None) if not isinstance(tag, dict) else tag.get("value")
    return None


@register_source("weather.noaa_gdacs", scope=Scope.SECTOR_AGGREGATE)
class NoaaGdacs:
    """Pull global disaster alerts from GDACS RSS."""

    source_id = "weather.noaa_gdacs"
    source_type = SourceType.RSS

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        text = ctx.http.get_text(URL, policy=ctx.rate_policy)
        for spec in parse(text):
            spec.url = URL
            yield build_record(ctx, self.source_id, self.source_type, spec)
