"""EPA FRS (spec §7): facility ID crosswalk/geolocation (API, no key)."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import epa

__all__ = ["EpaFrs"]


@register_source("petrochem.epa_frs", scope=Scope.PER_ENTITY)
class EpaFrs:
    """Per-entity EPA FRS facility lookup (FRS ID crosswalk + geolocation)."""

    source_id = "petrochem.epa_frs"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        for entity in ctx.resolver.all():
            frs_id = entity.epa_frs_id
            if not frs_id:
                continue
            raw = epa.frs_facility(ctx.http, ctx.rate_policy, registry_id=frs_id)
            yield build_record(
                ctx,
                self.source_id,
                self.source_type,
                RecordInput(
                    payload=raw,
                    raw_format=RawFormat.JSON,
                    entities=[Identifiers(epa_frs_id=frs_id, name=entity.name)],
                    url="https://frsquery.epa.gov/frs_rest_services.get_facility",
                ),
            )
