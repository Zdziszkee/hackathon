"""Stooq.com (spec §3): daily OHLCV (bulk CSV)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["Stooq", "parse"]

BASE = "https://stooq.com/q/d/l"


def parse(text: str) -> list[RecordInput]:
    """Wrap a Stooq daily CSV body as one record (rows parsed later)."""
    return [RecordInput(payload={"csv": text}, raw_format=RawFormat.CSV)]


@register_source("credit_market.stooq")
class Stooq:
    """Per-ticker daily OHLCV (Stooq bulk CSV download)."""

    source_id = "credit_market.stooq"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.ticker:
                continue
            url = f"{BASE}/?s={entity.ticker}.us&i=d"
            text = ctx.http.get_text(url, policy=ctx.rate_policy)
            for spec in parse(text):
                spec.entities = [entity]
                spec.url = url
                yield build_record(ctx, self.source_id, self.source_type, spec)
