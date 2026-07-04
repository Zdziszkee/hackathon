"""SEC 8-K material events (spec §2): Item 1.03/2.02/5.02 from recent filings."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

__all__ = ["SecEightK", "parse"]

FORM_8K = "8-K"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Extract 8-K filings from a submissions document's recent filings."""
    out: list[RecordInput] = []
    filings_obj = raw.get("filings") if isinstance(raw, dict) else None
    recent = filings_obj.get("recent") if isinstance(filings_obj, dict) else None
    if not isinstance(recent, dict):
        return out
    forms = recent.get("form")
    accessions = recent.get("accessionNumber")
    dates = recent.get("filingDate")
    docs = recent.get("primaryDocument")
    if not isinstance(forms, list) or not isinstance(accessions, list):
        return out
    acc_list = accessions if isinstance(accessions, list) else []
    date_list = dates if isinstance(dates, list) else []
    doc_list = docs if isinstance(docs, list) else []
    for i, form in enumerate(forms):
        if form != FORM_8K:
            continue
        acc = acc_list[i] if i < len(acc_list) else None
        date = date_list[i] if i < len(date_list) else None
        doc = doc_list[i] if i < len(doc_list) else None
        out.append(
            RecordInput(
                payload={
                    "form": str(form),
                    "accession": acc,
                    "filingDate": date,
                    "primaryDocument": doc,
                },
                raw_format=RawFormat.JSON,
            )
        )
    return out


@register_source("news.eight_k")
class SecEightK:
    """Per-entity 8-K material events (bankruptcy/Item 1.03, etc.)."""

    source_id = "news.eight_k"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.cik:
                continue
            raw = sec.submissions(ctx.http, ctx.rate_policy, entity.cik)
            for spec in parse(raw):
                spec.entities = [entity]
                spec.url = f"https://data.sec.gov/submissions/CIK{entity.cik.zfill(10)}.json"
                yield build_record(ctx, self.source_id, self.source_type, spec)
