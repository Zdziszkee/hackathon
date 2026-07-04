"""Rating agency press releases (spec §3): Moody's/S&P/Fitch actions only (Scrape).

STUB: scraping these newsrooms is fragile (anti-bot, unstable selectors).
Per the agreed fragile-source handling, the connector is registered but
``fetch`` is unimplemented pending stable per-agency selectors.
"""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord, SourceType
from ews_ingest.core.registry import register_source

__all__ = ["RatingAgencies"]

_AGENCIES: tuple[str, ...] = ("moodys", "sp", "fitch")


@register_source("credit_market.rating_agencies")
class RatingAgencies:
    """Rating-agency press-release actions (stub — fragile scrape)."""

    source_id = "credit_market.rating_agencies"
    source_type = SourceType.SCRAPE

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]:  # noqa: ARG002
        agencies = ", ".join(_AGENCIES)
        msg = (
            "TODO(spec §3): Moody's/S&P/Fitch newsroom scraping is fragile; "
            f"implement per-agency adapters for [{agencies}]."
        )
        raise NotImplementedError(msg)
