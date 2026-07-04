"""Tests for JsonlLandWriter idempotency and partitioning."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ews_ingest.core.landing import JsonlLandWriter
from ews_ingest.core.models import RawFormat, RawRecord, SourceType


def _rec(source: str, payload: dict[str, object]) -> RawRecord:
    return RawRecord(
        source=source,
        source_type=SourceType.API,
        fetched_at=datetime.now(UTC),
        fetch_run_id="run1",
        payload=payload,
        raw_format=RawFormat.JSON,
        content_hash="h_" + str(payload["k"]),
        entities=[],
    )


def test_write_then_dedup(tmp_path: Path) -> None:
    writer = JsonlLandWriter(tmp_path)
    assert writer.write([_rec("src.a", {"k": "1"})]) == 1
    # Re-write identical content -> skipped (idempotent).
    assert writer.write([_rec("src.a", {"k": "1"})]) == 0
    # New content -> written.
    assert writer.write([_rec("src.a", {"k": "2"})]) == 1


def test_has_hash_reflects_manifest(tmp_path: Path) -> None:
    writer = JsonlLandWriter(tmp_path)
    writer.write([_rec("src.a", {"k": "1"})])
    assert writer.has_hash("src.a", "h_1")
    assert not writer.has_hash("src.a", "h_999")


def test_per_source_manifest_isolation(tmp_path: Path) -> None:
    writer = JsonlLandWriter(tmp_path)
    writer.write([_rec("src.a", {"k": "1"})])
    # Same hash under a different source is not considered present.
    assert not writer.has_hash("src.b", "h_1")
    assert writer.write([_rec("src.b", {"k": "1"})]) == 1


def test_partitioned_path(tmp_path: Path) -> None:
    writer = JsonlLandWriter(tmp_path)
    writer.write([_rec("src.a", {"k": "1"})])
    partition = tmp_path / "src.a"
    assert (partition / "manifest.jsonl").exists()
    assert any(partition.glob("dt=*"))


def test_empty_write_is_noop(tmp_path: Path) -> None:
    writer = JsonlLandWriter(tmp_path)
    assert writer.write([]) == 0
    assert not (tmp_path / "nonexistent").exists()
