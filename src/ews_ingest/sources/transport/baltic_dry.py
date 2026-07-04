"""Baltic Dry Index (spec §6): STUB — no free official API; low reliability.

Only delayed headline mentions in shipping news exist. Per agreed fragile-source
handling the connector is registered but unimplemented.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord, SourceType
from ews_ingest.core.registry import register_source

__all__ = ["BalticDry"]


@register_source("transport.baltic_dry")
class BalticDry:
    """Baltic Dry Index (stub — no free official source)."""

    source_id = "transport.baltic_dry"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:
        msg = (
            "TODO(spec §6): no free Baltic Exchange official data license; delayed "
            "shipping-news scrape is low reliability (secondary priority)."
        )
        raise NotImplementedError(msg)
