"""Company universe loader: entities.yaml -> runtime company view.

Adds the seeded ``sector`` used by sector-routed indicators (e.g. demand trend).
The portfolio is cross-region as a whole, so no region derivation happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from ews_ingest.core.models import Identifiers

__all__ = ["Company", "load_companies"]


@dataclass(frozen=True)
class Company:
    """A borrower in the portfolio universe."""

    identifiers: Identifiers

    @property
    def name(self) -> str:
        return self.identifiers.name or self.identifiers.ticker or "—"

    @property
    def sector(self) -> str:
        return str(self.identifiers.extra_ids.get("sector", "unknown"))

    @property
    def ticker(self) -> str:
        return self.identifiers.ticker or "—"


def load_companies(path: Path) -> list[Company]:
    """Load entities.yaml -> list of :class:`Company`."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    entries = cast(list[dict[str, object]], raw)
    return [Company(identifiers=Identifiers.model_validate(entry)) for entry in entries]
