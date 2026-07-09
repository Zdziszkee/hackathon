"""Config-driven source registry (open-closed: add a module, no central edit)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TypeVar, cast

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord
from ews_ingest.core.protocol import DataSource, Scope

__all__ = [
    "SourceProfile",
    "all_source_ids",
    "get_source",
    "get_source_profile",
    "pick_sources",
    "register_source",
    "run_source",
]

_REGISTRY: dict[str, type[object]] = {}
_PROFILES: dict[str, SourceProfile] = {}
T = TypeVar("T", bound=object)


class SourceProfile:
    """Decorator-time metadata for a registered source.

    Stored alongside the connector class so the dashboard's onboarding
    orchestrator (PR 4) and the gen-sources-yaml tool can filter by
    scope without instantiating every connector.
    """

    __slots__ = ("scope", "source_id")

    def __init__(self, source_id: str, scope: Scope) -> None:
        self.source_id = source_id
        self.scope = scope


def register_source(
    source_id: str,
    *,
    scope: Scope = Scope.PER_ENTITY,
) -> Callable[[type[T]], type[T]]:
    """Class decorator registering a connector under ``source_id``.

    ``scope`` is recorded for the :func:`pick_sources` filter. Default
    value matches the most common pattern (a per-company SEC-style
    connector); override on aggregate / facility / manifest connectors.
    """

    def decorator(cls: type[T]) -> type[T]:
        _REGISTRY[source_id] = cls
        _PROFILES[source_id] = SourceProfile(source_id=source_id, scope=scope)
        return cls

    return decorator


def get_source(source_id: str) -> DataSource:
    """Instantiate a registered connector by id (no-arg constructor)."""
    cls = _REGISTRY.get(source_id)
    if cls is None:
        msg = f"Unknown source_id: {source_id!r}"
        raise KeyError(msg)
    return cast(DataSource, cls())


def get_source_profile(source_id: str) -> SourceProfile:
    """Return the decorator-time profile for ``source_id``."""
    try:
        return _PROFILES[source_id]
    except KeyError as exc:
        msg = f"Unknown source_id: {source_id!r}"
        raise KeyError(msg) from exc


def all_source_ids() -> list[str]:
    return sorted(_REGISTRY)


def pick_sources(
    *,
    scopes: set[Scope] | None = None,
) -> list[str]:
    """Return registered source_ids filtered by ``scopes``.

    Used by the dashboard onboarding orchestrator to pick the right
    subset of sources to refresh on add (typically
    ``{Scope.PER_ENTITY, Scope.FACILITY}`` — sector-aggregates and
    manifests run on the regular ingestion schedule, not on add).
    """
    out: list[str] = []
    for source_id in all_source_ids():
        profile = _PROFILES[source_id]
        if scopes is not None and profile.scope not in scopes:
            continue
        out.append(source_id)
    return out


def run_source(source_id: str, ctx: FetchContext) -> Iterator[RawRecord]:
    """Convenience: instantiate + fetch in one call."""
    return get_source(source_id).fetch(ctx)
