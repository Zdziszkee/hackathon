"""Bind ``source_id`` -> required env vars (from sources.yaml) for the dashboard.

Lives apart from :mod:`config` so the dashboard has no dependency on the full
ingest service bundle (loose coupling). When a source has no env requirements
or all are set, :meth:`EnvResolver.is_present` is ``True``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["EnvResolver"]


@dataclass(frozen=True)
class EnvResolver:
    """Per-source ``env_required`` knowledge for :class:`SignalContext`."""

    _required: dict[str, tuple[str, ...]]

    def is_present(self, source_id: str) -> bool:
        return not self._missing_for(source_id)

    def missing_for(self, source_id: str) -> list[str]:
        return self._missing_for(source_id)

    def _missing_for(self, source_id: str) -> list[str]:
        required = self._required.get(source_id, ())
        return [var for var in required if not os.environ.get(var, "")]

    @classmethod
    def from_required_map(
        cls,
        required: dict[str, tuple[str, ...]],
    ) -> EnvResolver:
        return cls({k: tuple(v) for k, v in required.items()})
