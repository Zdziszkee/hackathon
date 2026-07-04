"""Tests for FRED credit-spread connector parse() (spec §3)."""

from __future__ import annotations

import json
from pathlib import Path

from ews_ingest.core.models import RawFormat
from ews_ingest.core.records import RecordInput
from ews_ingest.sources.credit_market.fred_credit import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fred_credit_spread.json"


def test_parse_wraps_response_as_one_record() -> None:
    raw = json.loads(FIXTURE.read_text())
    specs = parse(raw)
    assert len(specs) == 1
    assert "observations" in specs[0].payload
    assert specs[0].raw_format == RawFormat.JSON


def test_parse_empty_returns_one_wrapping_record() -> None:
    specs = parse({})
    assert len(specs) == 1
    expected = RecordInput(payload={}, raw_format=RawFormat.JSON)
    assert specs[0].payload == expected.payload
    assert specs[0].raw_format == expected.raw_format
