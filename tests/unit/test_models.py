"""Tests for RawRecord/Identifiers models and UTC helper."""

from __future__ import annotations

from datetime import UTC

from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType, utc_now


def test_identifiers_defaults() -> None:
    ident = Identifiers(name="Acme")
    assert ident.cik is None
    assert ident.ticker is None
    assert ident.usdot is None
    assert ident.epa_frs_id is None
    assert ident.extra_ids == {}


def test_identifiers_ignores_unknown_keys() -> None:
    # Identifiers has extra="ignore"; unknown keys are dropped silently.
    ident = Identifiers.model_validate({"name": "A", "unexpected": 1})
    assert ident.name == "A"
    assert "unexpected" not in ident.extra_ids


def test_identifiers_free_form_sector_via_extra_ids() -> None:
    # Sector is a free-form string from Yahoo; carried only in extra_ids.
    ident = Identifiers.model_validate({"ticker": "AAPL", "extra_ids": {"sector": "Technology"}})
    assert ident.extra_ids["sector"] == "Technology"
    # No typed ``sector`` field on the model.
    assert not hasattr(ident, "sector")


def test_raw_record_roundtrip() -> None:
    now = utc_now()
    rec = RawRecord(
        source="test.x",
        source_type=SourceType.API,
        fetched_at=now,
        fetch_run_id="r1",
        payload={"k": 1},
        raw_format=RawFormat.JSON,
        content_hash="deadbeef",
        entities=[Identifiers(ticker="ACME")],
    )
    cloned = RawRecord.model_validate_json(rec.model_dump_json())
    assert cloned.source == "test.x"
    assert cloned.entities[0].ticker == "ACME"


def test_utc_now_has_tz() -> None:
    assert utc_now().tzinfo is UTC


def test_source_type_values() -> None:
    assert SourceType.API.value == "api"
    assert RawFormat.JSON.value == "json"
