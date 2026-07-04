"""Treasury fiscaldata.treasury.gov (spec §3): yields/TIC (API, no key).

Endpoint routes are best-effort and flagged in ``extra.note`` for verification.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["TreasuryFiscaldata", "parse"]

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2"

# Dataset routes under the fiscal_service v2 API.
DATASETS: tuple[tuple[str, str], ...] = (
    ("debt/sd/od", "debt_outstanding"),
    ("accounting/od/of-1", "federal_securities"),
)


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Each fiscaldata page becomes one record."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("credit_market.treasury_fiscaldata")
class TreasuryFiscaldata:
    """Treasury fiscaldata debt/securities datasets (yield curve via FRED §4)."""

    source_id = "credit_market.treasury_fiscaldata"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for route, label in DATASETS:
            url = f"{BASE}/{route}"
            raw = ctx.http.get_json(url, policy=ctx.rate_policy)
            for spec in parse(raw):
                spec.url = url
                spec.extra = {"dataset": label, "note": "verify_endpoint"}
                yield build_record(ctx, self.source_id, self.source_type, spec)
