"""Tests for SEC Company Facts parse() (spec §1)."""

from __future__ import annotations

import json
from pathlib import Path

from ews_ingest.sources.company_financials.company_facts import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sec_companyfacts.json"


def test_parse_wraps_document_as_single_record() -> None:
    raw = json.loads(FIXTURE.read_text())
    specs = parse(raw)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.raw_format.value == "json"
    assert "facts" in spec.payload
    assert spec.entities == []


def test_parse_empty_payload_yields_one_record() -> None:
    specs = parse({})
    assert len(specs) == 1
    assert specs[0].payload == {}
