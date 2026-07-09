"""EPA ECHO (spec §7): violations/enforcement/inspections (API, no key). NAICS 325."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source
from ews_ingest.providers import epa

__all__ = ["EpaEcho", "parse"]


def parse(raw: dict[str, object]) -> list[RecordInput]:
    """Split an ECHO facility-info response into one record per facility."""
    results = raw.get("Results") if isinstance(raw, dict) else None
    inner = results.get("Facilities") if isinstance(results, dict) else None
    items = inner if isinstance(inner, list) else []
    return [RecordInput(payload={"facility": f}, raw_format=RawFormat.JSON) for f in items]


@register_source("petrochem.epa_echo", scope=Scope.FACILITY)
class EpaEcho:
    """Pull EPA ECHO facilities for NAICS 325 (petrochemicals)."""

    source_id = "petrochem.epa_echo"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        raw = epa.echo_rest(
            ctx.http,
            ctx.rate_policy,
            service="get_facility_info",
            params={"p_naics": epa.NAICS_325},
        )
        for spec in parse(raw):
            spec.url = "https://ofmpub.epa.gov/echo/echo_rest_services.get_facility_info"
            yield build_record(ctx, self.source_id, self.source_type, spec)
