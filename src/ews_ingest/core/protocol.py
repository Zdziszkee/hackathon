"""DataSource protocol that every connector implements."""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord, SourceType

__all__ = ["DataSource", "Scope"]


class Scope(StrEnum):
    """How a connector produces records.

    Used by :func:`ews_ingest.core.registry.pick_sources` to filter the
    set of sources the onboarding orchestrator runs for a new ticker,
    and by the per-source ``enabled`` flag in ``config/sources.yaml`` to
    disable categories at config time.
    """

    PER_ENTITY = "per_entity"
    """Iterates ``ctx.resolver.all()``; emits one record per company."""

    FACILITY = "facility"
    """Pulls an external registry; emits records with facility-level IDs
    (USDOT, EPA FRS, etc.) — NOT keyed to a company in the resolver."""

    SECTOR_AGGREGATE = "sector_aggregate"
    """Pulls one URL or a fixed set of series; emits N records with no
    entity attached (e.g. macro indicators, commodity prices, sector-wide
    indexes)."""

    MANIFEST = "manifest"
    """Yields one or more records describing a bulk file URL (no actual
    data; just a pointer for a downstream phase to read)."""

    UNIVERSE = "universe"
    """Pulls a reference list of *companies* (CIK + ticker + name) for
    seeding the entity universe. Does NOT iterate ``ctx.resolver.all()``."""


@runtime_checkable
class DataSource(Protocol):
    """A single ingestion source. Implementations register via decorator.

    The per-host rate policy is config-driven (``sources.yaml``) and supplied
    at runtime via ``ctx.rate_policy``; connectors do not hardcode transport
    behavior, keeping them decoupled from throttling concerns.

    ``scope`` is set by the
    :func:`ews_ingest.core.registry.register_source` decorator (not by the
    class itself) so a single connector class can be registered under
    multiple ``source_id``s with different scopes if needed (e.g. universe
    vs. instance variants).
    """

    source_id: str
    source_type: SourceType
    scope: Scope

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]: ...
