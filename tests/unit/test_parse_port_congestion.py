"""Tests for World Bank port congestion parse() (spec extension)."""

from __future__ import annotations

import json
from pathlib import Path

from ews_ingest.sources.supply_chain.port_congestion import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "worldbank_port_traffic.json"


def test_parse_extracts_rows_from_response() -> None:
    raw = json.loads(FIXTURE.read_text())
    specs = parse(raw)
    assert len(specs) == 3
    assert "row" in specs[0].payload
    assert specs[0].raw_format.value == "json"


def test_parse_empty() -> None:
    assert parse([]) == []
    assert parse([{}]) == []
