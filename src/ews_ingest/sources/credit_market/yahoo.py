"""Yahoo Finance unofficial (spec §3): OHLCV (API, no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Yahoo", "parse"]

BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap a Yahoo chart response as one record per symbol."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("credit_market.yahoo", scope=Scope.PER_ENTITY)
class Yahoo:
    """Per-ticker 5y daily OHLCV (unofficial endpoint)."""

    source_id = "credit_market.yahoo"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.ticker:
                continue
            url = f"{BASE}/{entity.ticker}?range=5y&interval=1d"
            raw = ctx.http.get_json(url, policy=ctx.rate_policy)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
