"""Tests for UN Comtrade parse() (spec extension)."""

from __future__ import annotations

import json
from pathlib import Path

from ews_ingest.sources.supply_chain.un_comtrade import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "un_comtrade.json"


def test_parse_extracts_trade_rows() -> None:
    raw = json.loads(FIXTURE.read_text())
    specs = parse(raw)
    assert len(specs) == 2
    assert "trade_row" in specs[0].payload
    assert specs[0].raw_format.value == "json"


def test_parse_empty() -> None:
    assert parse({}) == []
    assert parse({"dataset": []}) == []
