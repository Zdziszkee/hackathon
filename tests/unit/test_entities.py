"""Tests for the YAML entity resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from ews_ingest.core.entities import YamlEntityResolver

ENTITIES_YAML = (
    Path(__file__).resolve().parents[2] / "src" / "ews_ingest" / "config" / "entities.yaml"
)


@pytest.fixture
def resolver() -> YamlEntityResolver:
    return YamlEntityResolver.from_yaml(ENTITIES_YAML)


def test_loads_expected_universe(resolver: YamlEntityResolver) -> None:
    ents = resolver.all()
    assert len(ents) == 19


def test_ticker_lookup(resolver: YamlEntityResolver) -> None:
    assert resolver.find_ticker("UPS") is not None
    assert resolver.find_ticker("XOM") is not None
    assert resolver.find_ticker("NOPE") is None


def test_cik_lookup(resolver: YamlEntityResolver) -> None:
    ent = resolver.find_ticker("DAL")
    assert ent is not None
    assert ent.cik == "0000027904"


def test_sector_in_extra(resolver: YamlEntityResolver) -> None:
    ent = resolver.find_ticker("CVX")
    assert ent is not None
    assert ent.extra_ids.get("sector") == "petrochemical"


def test_empty_resolver_when_missing(tmp_path: Path) -> None:
    r = YamlEntityResolver.from_yaml(tmp_path / "nope.yaml")
    assert r.all() == []
    assert r.find_ticker("X") is None


def test_all_three_sectors_present(resolver: YamlEntityResolver) -> None:
    sectors = {e.extra_ids.get("sector") for e in resolver.all()}
    assert {"transport_logistics", "airlines", "petrochemical"} <= sectors
