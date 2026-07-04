"""Tests for GDACS alerts parse() (spec extension)."""

from __future__ import annotations

from pathlib import Path

from ews_ingest.sources.weather.noaa_gdacs import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "gdacs_alerts.rss"


def test_parse_returns_one_record_per_alert() -> None:
    text = FIXTURE.read_text()
    specs = parse(text)
    assert len(specs) == 2
    titles = [s.payload.get("title") for s in specs]
    assert "Saudi Arabia: Tropical Cyclone (2024-01-15)" in titles
    assert specs[0].raw_format.value == "json"


def test_parse_empty_feed() -> None:
    assert parse("<rss><channel></channel></rss>") == []
