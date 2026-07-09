"""SEC company_tickers.json / company_tickers_exchange.json (spec §13, no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecCompanyTickers", "parse"]


def parse(rows: list[dict[str, object]]) -> list[RecordInput]:
    """Build a CIK/ticker identifier record per issuer row."""
    out: list[RecordInput] = []
    for row in rows:
        entry = row if isinstance(row, dict) else {}
        cik = entry.get("cik")
        ticker = entry.get("ticker")
        name = entry.get("name")
        out.append(
            RecordInput(
                payload={"cik": cik, "ticker": ticker, "name": name},
                raw_format=RawFormat.JSON,
                entities=[
                    Identifiers(
                        cik=str(cik).zfill(10) if cik is not None else None,
                        ticker=str(ticker) if ticker else None,
                        name=str(name) if name else None,
                    )
                ],
            )
        )
    return out


@register_source("universe.sec_company_tickers", scope=Scope.UNIVERSE)
class SecCompanyTickers:
    """Seed the public corporate universe from SEC company_tickers_exchange.json."""

    source_id = "universe.sec_company_tickers"
    source_type = SourceType.BULK_FILE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        rows = sec.tickers_exchange(ctx.http, ctx.rate_policy)
        url = "https://www.sec.gov/files/company_tickers_exchange.json"
        for spec in parse(rows):
            spec.url = url
            yield build_record(ctx, self.source_id, self.source_type, spec)
