"""Read landed JSONL records written by the ingestion layer.

The landing zone layout is ``<base>/<source_id>/dt=YYYY-MM-DD/<run>.jsonl``
(see :class:`ews_ingest.core.landing.JsonlLandWriter`). This reader parses
those files back into :class:`RawRecord` instances, newest-first, and exposes
helpers per source_id. It is the only place the dashboard touches on-disk data,
so swapping the sink (S3/parquet later) only changes this module.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ews_ingest.core.models import RawRecord

__all__ = ["LandingReader", "RecordStore"]


@dataclass(frozen=True)
class RecordStore:
    """All landed records for a single source_id, newest-first."""

    source_id: str
    records: tuple[RawRecord, ...]

    def latest(self) -> RawRecord | None:
        return self.records[0] if self.records else None

    def empty(self) -> bool:
        return not self.records


class LandingReader:
    """Parse landed JSONL into :class:`RawRecord` lists, keyed by source_id."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    def available_source_ids(self) -> list[str]:
        if not self._base.exists():
            return []
        return sorted(p.name for p in self._base.iterdir() if p.is_dir())

    def read(
        self,
        source_id: str,
        *,
        since: date | None = None,
    ) -> RecordStore:
        """Return all landed records for ``source_id``, newest-first."""
        root = self._base / source_id
        if not root.exists():
            return RecordStore(source_id, ())
        records: list[RawRecord] = []
        for partition in root.iterdir():
            if not partition.is_dir() or not partition.name.startswith("dt="):
                continue
            partition_date = _parse_dt(partition.name)
            if partition_date is None:
                continue
            if since is not None and partition_date < since:
                continue
            for fp in sorted(partition.glob("*.jsonl")):
                for line in fp.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    records.append(RawRecord.model_validate(json.loads(line)))
        records.sort(key=lambda r: r.fetched_at, reverse=True)
        return RecordStore(source_id, tuple(records))

    def iter_payloads(
        self,
        source_id: str,
        *,
        since: date | None = None,
    ) -> Iterator[dict[str, object]]:
        """Yield ``payload`` dicts for every landed record of a source."""
        for rec in self.read(source_id, since=since).records:
            yield rec.payload


def _parse_dt(name: str) -> date | None:
    stem = name.removeprefix("dt=")
    try:
        return date.fromisoformat(stem)
    except ValueError:
        return None


def fetched_date(rec: RawRecord) -> datetime:
    return rec.fetched_at
