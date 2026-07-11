"""Tests for the YAML entity resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from ews_ingest.core.entities import YamlEntityResolver


@pytest.fixture
def resolver(tmp_path: Path) -> YamlEntityResolver:
    # small seed for tests, no more hardcoded yaml
    yaml_path = tmp_path / "entities.yaml"
    yaml_path.write_text(
        "- ticker: UPS\n  name: United Parcel Service\n  cik: '0001090727'\n"
        "  extra_ids: {sector: transport_logistics}\n"
        "- ticker: XOM\n  name: Exxon\n  cik: '0000034088'\n"
        "  extra_ids: {sector: petrochemical}\n"
    )
    return YamlEntityResolver.from_yaml(yaml_path)


def test_loads_expected_universe(resolver: YamlEntityResolver) -> None:
    ents = resolver.all()
    assert len(ents) == 2


def test_ticker_lookup(resolver: YamlEntityResolver) -> None:
    assert resolver.find_ticker("UPS") is not None
    assert resolver.find_ticker("XOM") is not None
    assert resolver.find_ticker("NOPE") is None


def test_cik_lookup(resolver: YamlEntityResolver) -> None:
    ent = resolver.find_ticker("UPS")
    assert ent is not None
    assert ent.cik == "0001090727"


def test_sector_in_extra(resolver: YamlEntityResolver) -> None:
    ent = resolver.find_ticker("XOM")
    assert ent is not None
    assert ent.extra_ids.get("sector") == "petrochemical"


def test_empty_resolver_when_missing(tmp_path: Path) -> None:
    r = YamlEntityResolver.from_yaml(tmp_path / "nope.yaml")
    assert r.all() == []
    assert r.find_ticker("X") is None


def test_three_sectors_present(resolver: YamlEntityResolver) -> None:
    sectors = {e.extra_ids.get("sector") for e in resolver.all()}
    assert {"transport_logistics", "petrochemical"} <= sectors
