"""FRED credit-spread proxies (spec §3): BAMLH0A0HYM2, BAMLC0A4CBBB, AAA, BAA.

No free single-name CDS source exists; these are the agreed proxies.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import fred

__all__ = ["FredCreditSpreads", "parse"]

BASE = "https://api.stlouisfed.org/fred/series/observations"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap a FRED observations response as one record."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source(
    "credit_market.fred_credit",
    scope=Scope.SECTOR_AGGREGATE,
)
class FredCreditSpreads:
    """Credit-spread proxies (no single-name CDS exists)."""

    source_id = "credit_market.fred_credit"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        api_key = os.environ.get("FRED_API_KEY", "")
        for series_id in fred.CREDIT_SPREADS:
            params: dict[str, str | int] = {}
            if ctx.since is not None:
                params["observation_start"] = ctx.since.isoformat()
            raw = fred.series_observations(
                ctx.http,
                ctx.rate_policy,
                series_id=series_id,
                api_key=api_key,
                params=params or None,
            )
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload=raw,
                    raw_format=RawFormat.JSON,
                    url=BASE,
                    extra={"series_id": series_id},
                ),
            )
