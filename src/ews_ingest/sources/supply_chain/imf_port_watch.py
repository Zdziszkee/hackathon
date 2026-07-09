"""IMF Port Watch (spec extension): port-level trade/traffic data.

Best-effort (the portwatch.imf.org portal is JavaScript-driven; a documented
JSON endpoint is not publicly stable). Records a manifest pointing at the portal
plus a provisional API path flagged for verification. When a stable endpoint is
confirmed, fill in the live fetch.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawFormat, RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.records import RecordInput, build_record
from ews_ingest.core.registry import register_source

__all__ = ["ImfPortWatch"]

PORTAL = "https://portwatch.imf.org"
API_CANDIDATE = "https://portwatch.imf.org/api/dataset"


@register_source("supply_chain.imf_port_watch", scope=Scope.MANIFEST)
class ImfPortWatch:
    """Record IMF Port Watch portal manifest (live endpoint to be verified)."""

    source_id = "supply_chain.imf_port_watch"
    source_type = SourceType.API

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        yield build_record(
            ctx,
            self.source_id,
            self.source_type,
            RecordInput(
                payload={"portal": PORTAL, "api_candidate": API_CANDIDATE},
                raw_format=RawFormat.JSON,
                url=PORTAL,
                extra={"note": "portal_js_driven; verify_stable_api_endpoint"},
            ),
        )
