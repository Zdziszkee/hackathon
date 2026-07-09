"""SEC EDGAR Submissions API (spec §1): filer metadata, CIK/ticker/SIC crosswalk."""

from __future__ import annotations

from collections.abc import Iterator

import httpx

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecSubmissions", "parse"]


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract filer metadata as one record; carry CIK/ticker from the doc."""
    cik = str(raw.get("cik", "")).lstrip("0").zfill(10)
    tickers = raw.get("tickers")
    ticker = None
    if isinstance(tickers, list) and tickers:
        first = tickers[0]
        if isinstance(first, str):
            ticker = first
        elif isinstance(first, dict):
            ticker = str(first.get("ticker", "")) or None
    entity = Identifiers(cik=cik or None, ticker=ticker)
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON, entities=[entity])]


@register_source(
    "company_financials.submissions",
    scope=Scope.PER_ENTITY,
)
class SecSubmissions:
    """Per-entity submission history + filer metadata (CIK/ticker/SIC)."""

    source_id = "company_financials.submissions"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.cik:
                continue
            try:
                raw = sec.submissions(ctx.http, ctx.rate_policy, entity.cik)
            except httpx.HTTPStatusError as exc:
                # One wrong/retired CIK must not abort the whole batch — log it
                # and continue so the surviving good companies still land.
                ctx.logger.warning(
                    "submissions CIK=%s (%s) -> %s",
                    entity.cik,
                    entity.ticker or entity.name,
                    exc.response.status_code,
                )
                continue
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = f"https://data.sec.gov/submissions/CIK{entity.cik.zfill(10)}.json"
                yield build_record(ctx, self.source_id, self.source_type, spec)
