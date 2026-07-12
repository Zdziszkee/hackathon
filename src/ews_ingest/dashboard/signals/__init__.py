"""Signal-provider package: auto-discovered indicator modules.

Every module under this package that defines a ``Provider: SignalProvider``
instance is imported here via :func:`list_providers` (pkgutil walk, mirroring
the ingestion-layer pattern in ``ews_ingest.sources``). Add a new indicator
file and it is picked up — no central import list to maintain.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import cast

from ews_ingest.dashboard.signals.protocol import (
    SignalContext,
    SignalProvider,
    SignalResult,
    SignalStatus,
)

__all__ = [
    "PROVIDERS",
    "SignalContext",
    "SignalProvider",
    "SignalResult",
    "cast_status",
    "demo_result",
    "list_providers",
    "ok_result",
    "register_provider",
    "unavailable_result",
]

PROVIDERS: list[SignalProvider] = []


def register_provider(provider: SignalProvider) -> SignalProvider:
    """Register a ``Provider`` instance so the UI renders it."""
    PROVIDERS.append(provider)
    return provider


def list_providers() -> list[SignalProvider]:
    """Return all registered indicator providers, sorted by ``indicator_id``."""
    _import_all()
    return sorted(PROVIDERS, key=lambda p: p.indicator_id)


def _import_all() -> None:
    for module_info in pkgutil.iter_modules(__path__, __name__ + "."):
        if module_info.name in {"protocol", "__init__"}:
            continue
        if module_info.ispkg:
            continue
        importlib.import_module(module_info.name)


def unavailable_result(
    *,
    note: str,
    source_ids: tuple[str, ...] = (),
) -> SignalResult:
    """Build a standard ``unavailable`` result (no binding / no region)."""
    return SignalResult(
        value="n/a",
        score=0.0,
        status=cast(SignalStatus, "unavailable"),
        detail={},
        source_ids=source_ids,
        note=note,
    )


def demo_result(
    *,
    label_hint: str,
    value: str | float,
    score: float,
    missing_env: tuple[str, ...] = (),
    source_ids: tuple[str, ...] = (),
    note: str | None = None,
) -> SignalResult:
    """Build a standard ``demo`` result (no/partial landed data)."""
    return SignalResult(
        value=value,
        score=score,
        status=cast(SignalStatus, "demo"),
        detail={"label_hint": label_hint},
        source_ids=source_ids,
        missing_env=missing_env,
        note=note,
    )


def ok_result(
    *,
    value: str | float,
    score: float,
    status: str = "good",
    detail: dict[str, object] | None = None,
    source_ids: tuple[str, ...] = (),
) -> SignalResult:
    """Build a standard ``ok/warning/bad`` result computed from real data."""
    return SignalResult(
        value=value,
        score=score,
        status=cast(SignalStatus, status),
        detail=detail or {},
        source_ids=source_ids,
    )


def cast_status(status: str) -> SignalStatus:
    """Narrow a runtime-built status string to the ``SignalStatus`` literal."""
    return cast(SignalStatus, status)
