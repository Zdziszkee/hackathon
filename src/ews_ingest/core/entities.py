"""Entity universe loader and resolver for cross-source identifier joins."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast, runtime_checkable

import yaml

from ews_ingest.core.models import Identifiers

__all__ = ["EntityResolver", "YamlEntityResolver"]


@runtime_checkable
class EntityResolver(Protocol):
    """Lookup seeded entities by any known cross-source identifier."""

    def all(self) -> list[Identifiers]: ...
    def find_cik(self, cik: str) -> Identifiers | None: ...
    def find_ticker(self, ticker: str) -> Identifiers | None: ...
    def find_usdot(self, usdot: str) -> Identifiers | None: ...
    def find_epa_frs(self, epa_frs_id: str) -> Identifiers | None: ...


class YamlEntityResolver:
    """In-memory resolver backed by ``config/entities.yaml``."""

    def __init__(self, entities: list[Identifiers]) -> None:
        self._entities = entities
        self._by_cik = {e.cik: e for e in entities if e.cik}
        self._by_ticker = {e.ticker: e for e in entities if e.ticker}
        self._by_usdot = {e.usdot: e for e in entities if e.usdot}
        self._by_epa = {e.epa_frs_id: e for e in entities if e.epa_frs_id}

    @classmethod
    def from_yaml(cls, path: Path) -> YamlEntityResolver:
        if not path.exists():
            return cls([])
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = cast(list[dict[str, object]], raw)
        entities = [Identifiers.model_validate(e) for e in entries]
        return cls(entities)

    def all(self) -> list[Identifiers]:
        return list(self._entities)

    def find_cik(self, cik: str) -> Identifiers | None:
        return self._by_cik.get(cik)

    def find_ticker(self, ticker: str) -> Identifiers | None:
        return self._by_ticker.get(ticker)

    def find_usdot(self, usdot: str) -> Identifiers | None:
        return self._by_usdot.get(usdot)

    def find_epa_frs(self, epa_frs_id: str) -> Identifiers | None:
        return self._by_epa.get(epa_frs_id)
