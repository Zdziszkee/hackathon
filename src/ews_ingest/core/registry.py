"""Config-driven source registry (open-closed: add a module, no central edit)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TypeVar, cast

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord
from ews_ingest.core.protocol import DataSource

__all__ = ["all_source_ids", "get_source", "register_source", "run_source"]

_REGISTRY: dict[str, type[object]] = {}
T = TypeVar("T", bound=object)


def register_source(source_id: str) -> Callable[[type[T]], type[T]]:
    """Class decorator registering a connector under ``source_id``."""

    def decorator(cls: type[T]) -> type[T]:
        _REGISTRY[source_id] = cls
        return cls

    return decorator


def get_source(source_id: str) -> DataSource:
    """Instantiate a registered connector by id (no-arg constructor)."""
    cls = _REGISTRY.get(source_id)
    if cls is None:
        msg = f"Unknown source_id: {source_id!r}"
        raise KeyError(msg)
    return cast(DataSource, cls())


def all_source_ids() -> list[str]:
    return sorted(_REGISTRY)


def run_source(source_id: str, ctx: FetchContext) -> Iterator[RawRecord]:
    """Convenience: instantiate + fetch in one call."""
    return get_source(source_id).fetch(ctx)
