"""Tests for content_hash: order-independence and determinism."""

from __future__ import annotations

from ews_ingest.core.hashing import content_hash


def test_hash_order_independence() -> None:
    a = {"x": 1, "y": [1, 2, 3], "z": "hi"}
    b: dict[str, object] = {"z": "hi", "x": 1, "y": [1, 2, 3]}
    assert content_hash(a) == content_hash(b)


def test_hash_deterministic() -> None:
    p = {"a": 1, "b": 2}
    assert content_hash(p) == content_hash(p)


def test_hash_differs_on_value() -> None:
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_hash_handles_nested_and_mixed() -> None:
    p1: dict[str, object] = {"n": None, "f": 1.5, "l": [True, "x"]}
    p2: dict[str, object] = {"f": 1.5, "n": None, "l": [True, "x"]}
    assert content_hash(p1) == content_hash(p2)
