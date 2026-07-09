"""Tests for the source registry."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import ews_ingest.sources  # noqa: F401 - triggers registration
from ews_ingest.core.models import RawRecord, SourceType
from ews_ingest.core.registry import all_source_ids, get_source, register_source


def test_register_and_get() -> None:
    @register_source("test.dummy")
    class DummySource:
        source_id = "test.dummy"
        source_type = SourceType.API

        def fetch(self, ctx: object) -> Iterator[RawRecord]:  # noqa: ARG002
            return iter(())

    inst = get_source("test.dummy")
    assert inst.source_id == "test.dummy"
    assert inst.source_type == SourceType.API


def test_unknown_source_raises() -> None:
    with pytest.raises(KeyError):
        get_source("does.not.exist")


def test_all_source_ids_sorted() -> None:
    assert all_source_ids() == sorted(all_source_ids())


def test_registry_has_known_high_value_sources() -> None:
    ids = set(all_source_ids())
    expected = {
        "company_financials.company_facts",
        "news.gdelt",
        "macro.fred_macro",
        "commodity.eia",
        "transport.fmcsa_census",
        "credit_market.yahoo",
    }
    assert expected <= ids
