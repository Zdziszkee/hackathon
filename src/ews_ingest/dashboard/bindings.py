"""Role -> source_id bindings loaded from ``config/indicators.yaml``.

The dashboard asks ``bindings.source_for(role)`` instead of hardcoding a
``source_id``. Swapping the source behind any indicator is a YAML edit; the
portfolio is treated as one cross-region whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

__all__ = ["IndicatorBindings", "load_bindings"]


@dataclass(frozen=True)
class IndicatorBindings:
    """Role -> source_id lookup (portfolio-wide, open-closed)."""

    _roles: dict[str, str | None]

    def source_for(self, role: str) -> str | None:
        """Return the source_id bound to ``role`` (or ``None`` if unbound)."""
        return self._roles.get(role)

    def roles(self) -> dict[str, str | None]:
        return dict(self._roles)


def load_bindings(path: Path) -> IndicatorBindings:
    """Parse ``indicators.yaml`` into an :class:`IndicatorBindings`."""
    if not path.exists():
        return IndicatorBindings({})
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    roles_block = cast(dict[str, object], raw.get("roles", {}))
    roles = {role: (v if isinstance(v, str) else None) for role, v in roles_block.items()}
    return IndicatorBindings(roles)
