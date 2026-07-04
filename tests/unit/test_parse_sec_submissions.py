"""Tests for SEC Submissions parse() (spec §1): CIK/ticker crosswalk."""

from __future__ import annotations

import json
from pathlib import Path

from ews_ingest.sources.company_financials.submissions import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sec_submissions_ups.json"


def test_parse_extracts_cik_and_ticker() -> None:
    raw = json.loads(FIXTURE.read_text())
    specs = parse(raw)
    assert len(specs) == 1
    ent = specs[0].entities[0]
    assert ent.cik == "0001090727"
    assert ent.ticker == "UPS"


def test_parse_missing_tickers_field() -> None:
    specs = parse({"cik": "1"})
    assert len(specs) == 1
    assert specs[0].entities[0].ticker is None
    assert specs[0].entities[0].cik == "0000000001"
