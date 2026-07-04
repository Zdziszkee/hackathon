"""FMCSA SMS BASIC scores (spec §6): absolute violation measures remain public."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["FmcsaSms", "parse"]

BASE = "https://ai.fmcsa.dot.gov/SMS/Data/File"


def parse(raw: dict[str, object]) -> list[RecordInput]:
    return [RecordInput(payload=raw, raw_format=RawFormat.JSON)]


@register_source("transport.fmcsa_sms")
class FmcsaSms:
    """Record the FMCSA SMS BASIC violation bulk-file manifest."""

    source_id = "transport.fmcsa_sms"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        url = BASE
        raw = ctx.http.get_json(url, policy=ctx.rate_policy)
        for spec in parse(raw):
            spec.url = url
            spec.extra = {
                "note": "percentiles_restricted_post_FAST_2015; absolute_violations_public",
            }
            yield build_record(ctx, self.source_id, self.source_type, spec)
