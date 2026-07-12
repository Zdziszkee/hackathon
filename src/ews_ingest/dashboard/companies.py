"""Company universe loader: YAML (preferred) or JSON (legacy compat) -> runtime view.

Used for static entities.yaml and test fixtures. Live portfolio is in SQLite DB.
"""

from __future__ import annotations

import json
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
        """Free-form sector string from ``extra_ids`` (populated by the
        dynamic Yahoo sector lookup). Empty when the lookup failed.
        """
        return str(self.identifiers.extra_ids.get("sector", ""))

    @property
    def ticker(self) -> str:
        return self.identifiers.ticker or "—"


def _read_raw(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    # JSON support removed for entity files; use YAML for static/legacy
    if path.suffix == ".json":
        # legacy compat only
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        entries = data.get("companies") if "companies" in data else data
    else:
        entries = data
    return cast(list[dict[str, object]], entries)


def load_companies(path: Path) -> list[Company]:
    """Load a static entities file (yaml or json) for tests / legacy config."""
    return [Company(identifiers=Identifiers.model_validate(entry)) for entry in _read_raw(path)]
