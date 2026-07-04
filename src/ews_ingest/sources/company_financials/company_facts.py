"""SEC EDGAR XBRL Company Facts (spec §1): balance sheet/income/cashflow."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecCompanyFacts", "parse"]


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Wrap a companyfacts document as a single landing record."""
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("company_financials.company_facts")
class SecCompanyFacts:
    """Per-entity XBRL company facts (full financial history)."""

    source_id = "company_financials.company_facts"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.cik:
                continue
            raw = sec.company_facts(ctx.http, ctx.rate_policy, entity.cik)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = (
                    f"https://data.sec.gov/api/xbrl/companyfacts/CIK{entity.cik.zfill(10)}.json"
                )
                yield build_record(ctx, self.source_id, self.source_type, spec)
