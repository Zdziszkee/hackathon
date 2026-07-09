"""Company universe loader: YAML or JSON file -> runtime company view.

The dashboard persists its universe to a JSON file (see
:mod:`ews_ingest.dashboard.company_store`); the legacy ``entities.yaml`` is
still supported (and used by integration tests) so the loader dispatches on the
file extension. Either source produces the same :class:`Identifiers` schema.
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
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(data, dict):
        # Some YAML files wrap the universe in a top-level key (e.g. ``companies:``)
        entries = data.get("companies") if "companies" in data else data
    else:
        entries = data
    return cast(list[dict[str, object]], entries)


def load_companies(path: Path) -> list[Company]:
    """Load ``entities.yaml`` OR ``companies.json`` -> list of :class:`Company`.

    The on-disk schema is identical (a JSON/YAML array of ``Identifiers``-shaped
    dicts), so this loader transparently supports both backends.
    """
    return [Company(identifiers=Identifiers.model_validate(entry)) for entry in _read_raw(path)]
