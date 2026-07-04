"""DataSource protocol that every connector implements."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from ews_ingest.core.context import FetchContext
from ews_ingest.core.models import RawRecord, SourceType

__all__ = ["DataSource"]


@runtime_checkable
class DataSource(Protocol):
    """A single ingestion source. Implementations register via decorator.

    The per-host rate policy is config-driven (``sources.yaml``) and supplied
    at runtime via ``ctx.rate_policy``; connectors do not hardcode transport
    behavior, keeping them decoupled from throttling concerns.
    """

    source_id: str
    source_type: SourceType

    def fetch(self, ctx: FetchContext) -> Iterator[RawRecord]: ...
