"""SEC 8-K Item 1.03 Bankruptcy/Receivership (spec §11): ground truth via SEC."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec
from ews_ingest.sources.news import eight_k

__all__ = ["Sec8kBankruptcy", "parse"]

ITEM_1_03 = "1.03"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Filter 8-K filings to bankruptcy/receivership (Item 1.03) candidates.

    The submissions index lists forms + accession numbers; the actual item is in
    the filed document. Here we flag 8-Ks for later document parsing.
    """
    return eight_k.parse(raw)


@register_source("default_truth.sec_8k_bankruptcy")
class Sec8kBankruptcy:
    """Per-entity SEC 8-K filings ( Item 1.03 verified at doc-parse stage )."""

    source_id = "default_truth.sec_8k_bankruptcy"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.cik:
                continue
            raw = sec.submissions(ctx.http, ctx.rate_policy, entity.cik)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = f"https://data.sec.gov/submissions/CIK{entity.cik.zfill(10)}.json"
                spec.extra = {"item": ITEM_1_03, "note": "verify_item_in_filed_document"}
                yield build_record(ctx, self.source_id, self.source_type, spec)
