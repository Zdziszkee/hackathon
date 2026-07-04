"""SEC EDGAR Concept & Frames API (spec §1): time series / cross-company."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import httpx

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import sec

_logger = logging.getLogger(__name__)

__all__ = ["SecConceptFrames"]

# A small set of high-value balance-sheet concepts to pull per entity.
CONCEPTS: tuple[tuple[str, str], ...] = (
    ("us-gaap", "Assets"),
    ("us-gaap", "Liabilities"),
    ("us-gaap", "Revenues"),
    ("us-gaap", "NetIncomeLoss"),
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
)

# Frames are "CY"+year+"Q"+qtr aggregated across filers, e.g. CY2024Q1I.
CROSS_FRAMES: tuple[tuple[str, str, str], ...] = (
    ("us-gaap", "Assets", "CY2024Q4I"),
    ("us-gaap", "Revenues", "CY2024Q4I"),
)


@register_source("company_financials.concept_frames")
class SecConceptFrames:
    """Per-entity concept time series + a few cross-company frames."""

    source_id = "company_financials.concept_frames"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.cik:
                continue
            for tax, tag in CONCEPTS:
                url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{entity.cik.zfill(10)}/{tax}/{tag}.json"
                try:
                    raw = sec.concept(
                        ctx.http,
                        ctx.rate_policy,
                        cik=entity.cik,
                        concept_path=f"{tax}/{tag}",
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == httpx.codes.NOT_FOUND:
                        _logger.debug("concept %s/%s not reported by %s", tax, tag, entity.cik)
                        continue
                    raise
                yield build_record(
                    ctx,
                    self.source_id,
                    self.source_type,
                    RecordInput(
                        payload=raw,
                        raw_format=RawFormat.JSON,
                        entities=[entity],
                        url=url,
                    ),
                )
        for tax, tag, frame in CROSS_FRAMES:
            raw = sec.frames(ctx.http, ctx.rate_policy, tax, tag, frame)
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload=raw,
                    raw_format=RawFormat.JSON,
                    url=f"https://data.sec.gov/api/xbrl/frames/{tax}/{tag}/{frame}.json",
                ),
            )
