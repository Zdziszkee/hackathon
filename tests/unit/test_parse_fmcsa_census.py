"""Tests for FMCSA Census parse() (spec §6): NAICS-484 filtering + USDOT keys."""

from __future__ import annotations

from pathlib import Path

from ews_ingest.sources.transport.fmcsa_census import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "fmcsa_census_sample.csv"


def test_parse_keeps_naics_484_only() -> None:
    text = FIXTURE.read_text()
    specs = parse(text)
    # Rows: 100 (484121 keep), 101 (484122 keep), 102 (325110 drop), 103 (488111 drop).
    assert len(specs) == 2
    assert {s.entities[0].usdot for s in specs} == {"100", "101"}


def test_parse_carries_usdot_identifier() -> None:
    specs = parse(FIXTURE.read_text())
    ent = specs[0].entities[0]
    assert ent.usdot == "100"
    assert ent.name == "Acme Trucking LLC"


def test_parse_skips_rows_without_usdot() -> None:
    text = "USDOT_NUMBER,NAME,NAICS_CODE\n,Blank Co,484121\n101,Real Co,484121\n"
    specs = parse(text)
    assert len(specs) == 1
    assert specs[0].entities[0].usdot == "101"


def test_parse_empty_csv() -> None:
    assert parse("USDOT_NUMBER,NAME,NAICS_CODE\n") == []
