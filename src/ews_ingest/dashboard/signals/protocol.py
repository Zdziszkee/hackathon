"""Signal-provider protocol + shared result/context types.

Each indicator is an independent module under :mod:`ews_ingest.dashboard.signals`
that exposes a ``Provider`` instance implementing :class:`SignalProvider`.
Modules are auto-discovered via :func:`list_providers` (pkgutil, mirrors the
ingestion-layer pattern) — drop a new file in and it is picked up, no central
import list.

Providers declare the *roles* they consume (e.g. ``"macro.mfg_pmi"``), never a
concrete ``source_id``. The role is resolved to a source via
:class:`IndicatorBindings` (``config/indicators.yaml``). The portfolio is
cross-region as a whole, so bindings are flat (no per-region blocks).

Two extension axes (independent):

* new indicator  -> add a file in ``signals/`` + a role in YAML
* new source     -> register the connector + re-point the role in YAML
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.bindings import IndicatorBindings
from ews_ingest.dashboard.db import HistoricalStore
from ews_ingest.dashboard.landing import LandingReader

__all__ = [
    "HistoricalStore",
    "IndicatorBindings",
    "LandingReader",
    "SignalContext",
    "SignalProvider",
    "SignalResult",
    "SignalStatus",
]

SignalStatus = Literal["good", "warning", "bad", "demo", "unavailable"]


@dataclass(frozen=True)
class SignalResult:
    """A single computed indicator value for one company."""

    value: str | float
    score: float
    status: SignalStatus
    detail: dict[str, object] = field(default_factory=dict)
    source_ids: tuple[str, ...] = ()
    missing_env: tuple[str, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class SignalContext:
    """Dependency bundle handed to every :class:`SignalProvider`.

    One context serves the whole cross-region portfolio; per-company filtering
    happens inside providers via the entity fields on landed records.
    """

    bindings: IndicatorBindings
    landing: LandingReader
    env_present: Callable[[str], bool]
    missing_env: Callable[[str], list[str]]
    historical: HistoricalStore | None = None

    def source_for(self, role: str) -> str | None:
        """Resolve a role to a concrete source_id (portfolio-wide)."""
        return self.bindings.source_for(role)


@runtime_checkable
class SignalProvider(Protocol):
    """A single risk indicator for one company.

    Implementations read landed records (via ``ctx.landing``) for the source(s)
    bound to their declared ``roles``. They must degrade gracefully: missing
    binding -> ``unavailable``; landed data absent -> ``demo`` (shown as
    "no data found") with a deterministic fallback; missing API key ->
    ``demo`` with ``missing_env`` populated.
    """

    indicator_id: str
    label: str
    description: str
    roles: tuple[str, ...]

    def compute(self, company: Identifiers, ctx: SignalContext) -> SignalResult: ...
