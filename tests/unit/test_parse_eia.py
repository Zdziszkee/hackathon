"""Tests for EIA commodity connector parse() (spec §5)."""

from __future__ import annotations

import json
from pathlib import Path

from ews_ingest.core.models import RawFormat
from ews_ingest.sources.commodity.eia import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "eia_brent.json"


def test_parse_wraps_response_as_one_record() -> None:
    raw = json.loads(FIXTURE.read_text())
    specs = parse(raw)
    assert len(specs) == 1
    assert "response" in specs[0].payload
    assert specs[0].raw_format == RawFormat.JSON


def test_parse_empty() -> None:
    specs = parse({})
    assert len(specs) == 1
    assert specs[0].payload == {}
