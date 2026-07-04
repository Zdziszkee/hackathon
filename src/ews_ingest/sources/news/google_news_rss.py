"""Google News RSS (spec §2): per-entity + sector distress headlines (Scrape, no key).

Hits the public ``news.google.com/rss/search`` feed via scrapling's HTTP fetcher
(no API key, no browser). Mirrors :mod:`ews_ingest.sources.news.gdelt` query
shape: per-entity distress alignment plus sector-level queries.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterator

import feedparser

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.core.scrape import FetchMode
from ews_ingest.providers.gdelt import DISTRESS_KEYWORDS

__all__ = ["GoogleNewsRss", "parse"]

BASE = "https://news.google.com/rss/search"

# Sector-level distress query terms (mirrors news.gdelt).
SECTOR_QUERIES: tuple[str, ...] = (
    "diesel driver shortage",
    "refinery outage chemicals",
    "airline bankruptcy restructuring",
    "trucking layoffs",
)

_ALIGNMENT = " OR ".join(DISTRESS_KEYWORDS)


def _entity_query(name: str) -> str:
    return f'"{name}" ({_ALIGNMENT})'


def _search_url(query: str) -> str:
    return f"{BASE}?q={urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"


def parse(xml_bytes: bytes) -> list[RecordInput]:
    """Split a Google News RSS feed into one record per ``<item>``."""
    feed = feedparser.parse(xml_bytes)
    out: list[RecordInput] = []
    for entry in feed.entries:
        title = str(entry.get("title", "") or "").strip()
        link = str(entry.get("link", "") or "").strip()
        pub = str(entry.get("published", "") or "").strip()
        source_field = entry.get("source")
        source = ""
        if isinstance(source_field, dict):
            source = str(source_field.get("title", "") or "").strip()
        desc = str(entry.get("summary", "") or "").strip()
        if not title and not link:
            continue
        out.append(
            RecordInput(
                payload={
                    "title": title,
                    "link": link,
                    "pub_date": pub,
                    "source": source,
                    "description": desc,
                },
                raw_format=RawFormat.XML,
            )
        )
    return out


def _body_bytes(page: object) -> bytes:
    body = getattr(page, "body", b"") or b""
    if isinstance(body, str):
        return body.encode("utf-8", errors="replace")
    return body


@register_source("news.google_news_rss")
class GoogleNewsRss:
    """Per-entity + sector distress headlines via the public Google News RSS feed."""

    source_id = "news.google_news_rss"
    source_type = SourceType.RSS

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            url = _search_url(_entity_query(entity.name))
            page = ctx.scraper.fetch_html(url, policy=ctx.rate_policy, mode=FetchMode.HTTP)
            for spec in parse(_body_bytes(page)):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
        for query in SECTOR_QUERIES:
            url = _search_url(query)
            page = ctx.scraper.fetch_html(url, policy=ctx.rate_policy, mode=FetchMode.HTTP)
            for spec in parse(_body_bytes(page)):
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
