"""Twelve Data (spec §3): quotes/fundamentals (free key)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["TwelveData", "parse"]

BASE = "https://api.twelvedata.com/time_series"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap a Twelve Data time-series response as one record."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("credit_market.twelve_data")
class TwelveData:
    """Per-ticker daily time series (Twelve Data)."""

    source_id = "credit_market.twelve_data"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("TWELVEDATA_API_KEY", "")
        for entity in ctx.resolver.all():
            if not entity.ticker:
                continue
            url = BASE
            params: dict[str, str | int] = {
                "symbol": entity.ticker,
                "interval": "1day",
                "outputsize": "5000",
                "apikey": api_key,
            }
            raw = ctx.http.get_json(url, policy=ctx.rate_policy, params=params)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
