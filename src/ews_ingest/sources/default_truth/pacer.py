"""PACER (spec §11): STUB — fee-based ($0.10/page after free $30/quarter quota).

Fallback for docs not in RECAP. Per agreed fragile/fee-source handling the
connector is registered but unimplemented; RECAP (§11 courtlistener) is the
first-stop free source.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord, SourceType
from ews_ingest.core.protocol import Scope
from ews_ingest.core.registry import register_source

__all__ = ["Pacer"]


@register_source("default_truth.pacer", scope=Scope.MANIFEST)
class Pacer:
    """PACER fallback (stub — fee-based)."""

    source_id = "default_truth.pacer"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        msg = (
            "TODO(spec §11): PACER is fee-based; use RECAP (courtlistener) first. "
            "Implement a dry-run/fee-gated client when PACER credentials are provided."
        )
        raise NotImplementedError(msg)
