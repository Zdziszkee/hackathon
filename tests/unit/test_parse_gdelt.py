"""Tests for GDELT doc-search parse() (spec §2)."""

from __future__ import annotations

import json
from pathlib import Path

from ews_ingest.sources.news.gdelt import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gdelt_articles.json"


def test_parse_returns_one_record_per_article() -> None:
    raw = json.loads(FIXTURE.read_text())
    specs = parse(raw)
    assert len(specs) == 2
    assert specs[0].raw_format.value == "json"
    assert "article" in specs[0].payload


def test_parse_empty() -> None:
    assert parse({}) == []


def test_parse_no_articles_key() -> None:
    assert parse({"other": 1}) == []
