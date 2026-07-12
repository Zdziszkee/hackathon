"""GDELT Project news (spec §2): tone/themes/geo via REST API v2. High-value."""

from __future__ import annotations

from collections.abc import Iterator

import httpx

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import gdelt as api
from ews_ingest.providers.gdelt import DISTRESS_KEYWORDS

__all__ = ["GdeltNews", "parse"]


_ALIGNMENT = " | ".join(DISTRESS_KEYWORDS)


def _entity_query(name: str) -> str:
    # GDELT requires OR groups to be self-contained. Build
    # `("NAME" kw1) | ("NAME" kw2) | ...` so the parens hold OR'd
    # statements that each include the quoted entity name.
    quoted = f'"{name}"'
    return " | ".join(f"({quoted} {kw})" for kw in DISTRESS_KEYWORDS)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split a GDELT doc-search response into one record per article."""
    articles = raw.get("articles") if isinstance(raw, dict) else None
    items = articles if isinstance(articles, list) else []
    return [RecordInput(payload={"article": a}, raw_format=RawFormat.JSON) for a in items]


@register_source("news.gdelt", scope=Scope.PER_ENTITY)
class GdeltNews:
    """Per-entity distress article search via GDELT v2 doc endpoint."""

    source_id = "news.gdelt"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.name:
                continue
            query = _entity_query(entity.name)
            yield from self._safe_search(ctx, query, entities=[entity])

    @staticmethod
    def _safe_search(
        ctx: FetchContext,
        query: str,
        *,
        entities: list[Identifiers] | None = None,
    ) -> Iterator[RawRecord]:
        """Run one GDELT doc search, resilient to rate-limit / non-JSON errors.

        GDELT's public endpoint periodically returns a 429 or an HTML body
        instead of JSON (and ``HttpClient.request`` raises ``HTTPStatusError``
        on the 4xx even after retries). One failed query must not abort the
        whole run — we log + skip so the remaining companies still land.
        """
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        try:
            raw = api.doc_search(ctx.http, ctx.rate_policy, query=query)
        except httpx.HTTPStatusError as exc:
            ctx.logger.warning(
                "gdelt query failed: %s status=%s",
                query[:60],
                exc.response.status_code,
            )
            return
        except Exception as exc:
            ctx.logger.warning("gdelt query error: %s status=NA %s", query[:60], exc)
            return
        for spec in parse(raw):
            if entities:
                spec.entities = list(entities)
            spec.url = url
            yield build_record(ctx, "news.gdelt", SourceType.API, spec)
