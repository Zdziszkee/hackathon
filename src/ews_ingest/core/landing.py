"""Append-only JSONL landing zone with content-hash idempotency."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from ews_ingest.core.models import RawRecord

__all__ = ["JsonlLandWriter", "LandWriter"]


@runtime_checkable
class LandWriter(Protocol):
    """Pluggable sink for raw records (local JSONL now; S3/parquet later)."""

    def has_hash(self, source_id: str, content_hash: str) -> bool: ...
    def write(self, records: list[RawRecord]) -> int: ...


class JsonlLandWriter:
    """Partitioned JSONL writer: ``<base>/<source>/dt=YYYY-MM-DD/<run>.jsonl``."""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._manifests: dict[str, set[str]] = {}

    def _load_manifest(self, source_id: str) -> set[str]:
        if source_id in self._manifests:
            return self._manifests[source_id]
        path = self._base / source_id / "manifest.jsonl"
        hashes: set[str] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    hashes.add(line.strip())
        self._manifests[source_id] = hashes
        return hashes

    def has_hash(self, source_id: str, content_hash: str) -> bool:
        return content_hash in self._load_manifest(source_id)

    def write(self, records: list[RawRecord]) -> int:
        """Append new (unseen) records; return count actually written."""
        if not records:
            return 0
        first = records[0]
        source_id = first.source
        partition_date: date = first.fetched_at.date()
        manifest = self._load_manifest(source_id)
        new_records = [r for r in records if r.content_hash not in manifest]
        if not new_records:
            return 0
        partition = self._base / source_id / f"dt={partition_date.isoformat()}"
        partition.mkdir(parents=True, exist_ok=True)
        target = partition / f"{first.fetch_run_id}.jsonl"
        with target.open("a", encoding="utf-8") as fh:
            for rec in new_records:
                fh.write(rec.model_dump_json() + "\n")
                manifest.add(rec.content_hash)
        mpath = self._base / source_id / "manifest.jsonl"
        mpath.parent.mkdir(parents=True, exist_ok=True)
        with mpath.open("a", encoding="utf-8") as mh:
            for rec in new_records:
                mh.write(rec.content_hash + "\n")
        return len(new_records)
