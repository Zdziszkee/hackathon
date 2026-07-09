"""Tests for the Yahoo Finance sector lookup."""

from __future__ import annotations

from typing import Any

import pytest

from ews_ingest.dashboard.yahoo_sector import (
    SecLiveYahooSector,
    SectorLookup,
    SectorLookupError,
    parse_asset_profile,
)

# --- pure parser ----------------------------------------------------------

# --- pure parser ----------------------------------------------------------


def test_parse_asset_profile_standard_shape() -> None:
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "assetProfile": {
                        "sector": "Technology",
                        "industry": "Consumer Electronics",
                    }
                }
            ]
        }
    }
    result = parse_asset_profile(payload)
    assert result.extra_ids == {
        "sector": "Technology",
        "industry": "Consumer Electronics",
    }


def test_parse_asset_profile_only_sector() -> None:
    payload = {"quoteSummary": {"result": [{"assetProfile": {"sector": "Financial Services"}}]}}
    assert parse_asset_profile(payload).extra_ids == {"sector": "Financial Services"}


def test_parse_asset_profile_empty_sector_excluded() -> None:
    payload = {
        "quoteSummary": {"result": [{"assetProfile": {"sector": "  ", "industry": "Banks"}}]}
    }
    # Whitespace-only sector is treated as missing.
    assert parse_asset_profile(payload).extra_ids == {"industry": "Banks"}


def test_parse_asset_profile_missing_quote_summary_raises() -> None:
    with pytest.raises(SectorLookupError, match="no quoteSummary"):
        parse_asset_profile({})


def test_parse_asset_profile_missing_result_raises() -> None:
    with pytest.raises(SectorLookupError, match="no result array"):
        parse_asset_profile({"quoteSummary": {}})


def test_parse_asset_profile_missing_asset_profile_raises() -> None:
    with pytest.raises(SectorLookupError, match="no assetProfile"):
        parse_asset_profile({"quoteSummary": {"result": [{}]}})


def test_parse_asset_profile_empty_result_array_raises() -> None:
    with pytest.raises(SectorLookupError, match="no result array"):
        parse_asset_profile({"quoteSummary": {"result": []}})


# --- live impl with a stub HTTP client -------------------------------------


class _StubHttp:
    """Duck-typed HttpClient substitute for sector-lookup tests."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.calls: list[str] = []

    def get_json(self, url: str, **_: Any) -> Any:
        self.calls.append(url)
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _standard_payload(sector: str = "Technology") -> dict[str, object]:
    return {
        "quoteSummary": {
            "result": [
                {
                    "assetProfile": {
                        "sector": sector,
                        "industry": "Consumer Electronics",
                    }
                }
            ]
        }
    }


def test_lookup_returns_partial_identifier_with_sector() -> None:
    http = _StubHttp(_standard_payload("Financial Services"))
    lookup = SecLiveYahooSector(http)
    result = lookup.lookup("JPM")
    assert result.extra_ids["sector"] == "Financial Services"
    # The returned identifier is a stub — no name/cik/ticker carried.
    assert result.ticker is None
    assert result.cik is None


def test_lookup_caches_result_across_calls() -> None:
    http = _StubHttp(_standard_payload())
    lookup = SecLiveYahooSector(http)
    first = lookup.lookup("AAPL")
    second = lookup.lookup("AAPL")
    assert first.extra_ids == second.extra_ids
    assert len(http.calls) == 1


def test_lookup_does_not_cache_empty_results() -> None:
    """An empty payload (no sector) is re-tried on the next call."""
    empty = {"quoteSummary": {"result": [{}]}}
    http = _StubHttp(empty)
    lookup = SecLiveYahooSector(http)
    with pytest.raises(SectorLookupError):
        lookup.lookup("AAPL")
    with pytest.raises(SectorLookupError):
        lookup.lookup("AAPL")
    assert len(http.calls) == 2


def test_lookup_propagates_network_failure() -> None:
    http = _StubHttp(RuntimeError("network down"))
    lookup = SecLiveYahooSector(http)
    with pytest.raises(SectorLookupError, match="network down"):
        lookup.lookup("AAPL")


def test_lookup_uppercases_ticker() -> None:
    http = _StubHttp(_standard_payload())
    lookup = SecLiveYahooSector(http)
    result = lookup.lookup("aapl")
    assert result.extra_ids["sector"] == "Technology"
    assert http.calls == [
        "https://query1.finance.yahoo.com/v10/finance/quoteSummary/AAPL?modules=assetProfile"
    ]


def test_lookup_empty_ticker_raises() -> None:
    http = _StubHttp(_standard_payload())
    lookup = SecLiveYahooSector(http)
    with pytest.raises(SectorLookupError, match="must not be empty"):
        lookup.lookup("   ")


def test_lookup_invalidate_specific_ticker() -> None:
    http = _StubHttp(_standard_payload())
    lookup = SecLiveYahooSector(http)
    lookup.lookup("AAPL")
    lookup.invalidate("AAPL")
    lookup.lookup("AAPL")
    assert len(http.calls) == 2


def test_lookup_invalidate_all() -> None:
    http = _StubHttp(_standard_payload())
    lookup = SecLiveYahooSector(http)
    lookup.lookup("AAPL")
    lookup.lookup("MSFT")
    lookup.invalidate()
    lookup.lookup("AAPL")
    lookup.lookup("MSFT")
    assert len(http.calls) == 4


def test_satisfies_protocol() -> None:
    http = _StubHttp(_standard_payload())
    lookup: SectorLookup = SecLiveYahooSector(http)
    assert isinstance(lookup, SectorLookup)


def test_lookup_non_dict_payload_raises() -> None:
    """``get_json`` must return a dict; if a stub returns a non-dict
    (shouldn't happen for our usage) the lookup raises clearly."""
    http = _StubHttp({"foo": "bar"})  # not a quoteSummary wrapper
    lookup = SecLiveYahooSector(http)
    with pytest.raises(SectorLookupError):
        lookup.lookup("AAPL")
