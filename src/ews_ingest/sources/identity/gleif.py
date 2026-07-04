"""GLEIF Level 1 + Level 2 (spec §12): who-is-who + parent mapping. High-value."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import gleif

__all__ = ["GleifL1", "GleifL2"]

_LEI_BASE = "https://api.gleif.org/api/v1/lei-records"
_RR_URL = "https://api.gleif.org/api/v1/rr-records"


@register_source("identity.gleif_l1")
class GleifL1:
    """Per-entity LEI record (who-is-who) from GLEIF Level 1."""

    source_id = "identity.gleif_l1"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.lei:
                continue
            raw = gleif.lei_record(ctx.http, ctx.rate_policy, entity.lei)
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload=raw,
                    raw_format=RawFormat.JSON,
                    entities=[Identifiers(lei=entity.lei, name=entity.name)],
                    url=f"{_LEI_BASE}/{entity.lei}",
                ),
            )


@register_source("identity.gleif_l2")
class GleifL2:
    """Per-entity parent relationships (who-owns-whom) from GLEIF Level 2."""

    source_id = "identity.gleif_l2"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            if not entity.lei:
                continue
            raw = gleif.rr_records_for_lei(ctx.http, ctx.rate_policy, entity.lei)
            data = raw.get("data") if isinstance(raw, dict) else None
            items = data if isinstance(data, list) else []
            for item in items:
                yield build_record(
                    ctx,
                    self.source_id,
                    self.source_type,
                    RecordInput(
                        payload={"relationship": item},
                        raw_format=RawFormat.JSON,
                        entities=[Identifiers(lei=entity.lei, name=entity.name)],
                        url=_RR_URL,
                    ),
                )
