"""Alpha Vantage (spec §3): fundamentals/quotes (free key, 25 req/day backup)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["AlphaVantage", "parse"]

BASE = "https://www.alphavantage.co/query"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap an Alpha Vantage response as one record."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("credit_market.alpha_vantage")
class AlphaVantage:
    """Per-ticker daily time series (backup source, capped 25 req/day)."""

    source_id = "credit_market.alpha_vantage"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
        for entity in ctx.resolver.all():
            if not entity.ticker:
                continue
            url = BASE
            params: dict[str, str | int] = {
                "function": "TIME_SERIES_DAILY",
                "symbol": entity.ticker,
                "outputsize": "full",
                "apikey": api_key,
            }
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
