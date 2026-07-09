"""Tests for the ticker-suggest autocomplete."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.ticker_suggest import (
    SecLiveTickerSuggest,
    TickerSuggest,
    suggest_from_rows,
)

# --- pure search ----------------------------------------------------------


def _row(ticker: str, name: str, cik: str = "0000000001") -> Identifiers:
    return Identifiers(cik=cik, ticker=ticker, name=name)


_ROWS = [
    _row("AAPL", "Apple Inc.", "0000320193"),
    _row("AMZN", "Amazon.com Inc.", "0001018724"),
    _row("MSFT", "Microsoft Corp", "0000789019"),
    _row("NVDA", "NVIDIA Corp", "0001045810"),
    _row("TSLA", "Tesla, Inc.", "0001318605"),
]


def test_suggest_empty_prefix_returns_alphabetical() -> None:
    out = suggest_from_rows(_ROWS, "")
    assert [r.ticker for r in out] == ["AAPL", "AMZN", "MSFT", "NVDA", "TSLA"]


def test_suggest_ticker_prefix_first() -> None:
    out = suggest_from_rows(_ROWS, "AA")
    assert [r.ticker for r in out] == ["AAPL"]


def test_suggest_ticker_substring() -> None:
    out = suggest_from_rows(_ROWS, "S")
    # Tickers containing "s" anywhere: MSFT, TSLA (case-insensitive).
    assert {r.ticker for r in out} == {"MSFT", "TSLA"}


def test_suggest_name_substring() -> None:
    out = suggest_from_rows(_ROWS, "microsoft")
    assert [r.ticker for r in out] == ["MSFT"]


def test_suggest_case_insensitive() -> None:
    out = suggest_from_rows(_ROWS, "aapl")
    assert [r.ticker for r in out] == ["AAPL"]


def test_suggest_no_match_returns_empty() -> None:
    assert suggest_from_rows(_ROWS, "ZZZZ") == []


def test_suggest_respects_limit() -> None:
    rows = [_row(f"T{i:02d}", f"Co {i}") for i in range(20)]
    out = suggest_from_rows(rows, "", limit=5)
    assert len(out) == 5


def test_suggest_skips_rows_without_ticker() -> None:
    rows = [
        _row("AAPL", "Apple"),
        Identifiers(cik="0000000000", ticker=None, name="NoTicker"),
    ]
    out = suggest_from_rows(rows, "")
    assert [r.ticker for r in out] == ["AAPL"]


# --- live impl with a stub HTTP client ------------------------------------


class _StubHttp:
    """Drop-in :class:`HttpLike` substitute for the suggester tests.

    Records every call to ``get_json`` so tests can assert caching
    behavior (the live impl must hit the network once per cache TTL, not
    per keystroke). Signature mirrors
    :meth:`HttpClient.get_json` minus the rate-policy hook (we don't
    exercise retry/backoff here).
    """

    def __init__(self, payload: list[dict[str, object]] | dict[str, object] | Exception) -> None:
        self._payload = payload
        self.calls: list[str] = []
        self.sec_user_agent = "stub@example.com"

    def get_json(
        self,
        url: str,
        *,
        policy: object = None,  # noqa: ARG002 - protocol signature
        params: dict[str, str | int] | None = None,  # noqa: ARG002
        headers: dict[str, str] | None = None,  # noqa: ARG002
    ) -> dict[str, object]:
        self.calls.append(url)
        if isinstance(self._payload, Exception):
            raise self._payload
        if isinstance(self._payload, dict):
            return self._payload
        # Wrap a list payload as the legacy SEC ``{"results": [...]}`` shape
        # so :func:`providers.sec.tickers_exchange` unwraps it for us. This
        # keeps the stub's return type matching the real
        # ``HttpClient.get_json`` signature.
        return {"results": self._payload}


def _legacy_payload() -> list[dict[str, Any]]:
    """The pre-2025 SEC ``company_tickers_exchange.json`` response shape."""
    return [
        {"cik": 320193, "ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
        {"cik": 1018724, "ticker": "AMZN", "name": "Amazon.com Inc.", "exchange": "NASDAQ"},
        {"cik": 789019, "ticker": "MSFT", "name": "Microsoft Corp", "exchange": "NASDAQ"},
    ]


def test_live_suggest_normalizes_cik_and_uppercases_ticker() -> None:
    http = _StubHttp(_legacy_payload())
    suggest = SecLiveTickerSuggest(http, cache_ttl=timedelta(minutes=5))
    out = suggest.suggest("aapl")
    assert len(out) == 1
    aapl = out[0]
    assert aapl.ticker == "AAPL"
    assert aapl.cik == "0000320193"  # zero-padded to 10
    assert aapl.name == "Apple Inc."


def test_live_suggest_caches_across_calls() -> None:
    """Multiple ``suggest`` calls within the TTL must hit the network once."""
    http = _StubHttp(_legacy_payload())
    suggest = SecLiveTickerSuggest(http, cache_ttl=timedelta(minutes=5))
    suggest.suggest("a")
    suggest.suggest("ap")
    suggest.suggest("app")
    assert len(http.calls) == 1


def test_live_suggest_refetches_after_ttl() -> None:
    http = _StubHttp(_legacy_payload())
    # TTL=0 -> every call refetches.
    suggest = SecLiveTickerSuggest(http, cache_ttl=timedelta(0))
    suggest.suggest("a")
    suggest.suggest("a")
    assert len(http.calls) == 2


def test_live_suggest_serves_stale_cache_on_network_error() -> None:
    """A network error during refresh must not nuke an existing cache."""
    http = _StubHttp(_legacy_payload())
    suggest = SecLiveTickerSuggest(http, cache_ttl=timedelta(0))
    # Warm the cache.
    assert suggest.suggest("aapl")
    # Now break the network and force a refetch.
    http._payload = RuntimeError("network down")
    out = suggest.suggest("aapl")
    assert [r.ticker for r in out] == ["AAPL"]


def test_live_suggest_raises_on_initial_failure() -> None:
    """No cache yet + network failure -> the call propagates."""
    http = _StubHttp(RuntimeError("network down"))
    suggest = SecLiveTickerSuggest(http)
    with pytest.raises(RuntimeError, match="network down"):
        suggest.suggest("aapl")


def test_live_suggest_handles_new_2025_row_shape() -> None:
    """The 2025 SEC response uses ``{fields, data}`` not a flat list."""
    new_shape: dict[str, object] = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [320193, "Apple Inc.", "AAPL", "NASDAQ"],
            [789019, "Microsoft Corp", "MSFT", "NASDAQ"],
        ],
    }
    http = _StubHttp(new_shape)
    suggest = SecLiveTickerSuggest(http, cache_ttl=timedelta(minutes=5))
    out = suggest.suggest("micro")
    assert [r.ticker for r in out] == ["MSFT"]


def test_live_suggest_skips_rows_with_no_ticker() -> None:
    payload: list[dict[str, object]] = [
        {"cik": 1, "ticker": "AAPL", "name": "Apple"},
        {"cik": 2, "ticker": "", "name": "Empty"},
        {"cik": None, "ticker": "BAD", "name": "NoCik"},
    ]
    http = _StubHttp(payload)
    suggest = SecLiveTickerSuggest(http)
    out = suggest.suggest("")
    assert [r.ticker for r in out] == ["AAPL"]


def test_live_suggest_invalidate_forces_refetch() -> None:
    http = _StubHttp(_legacy_payload())
    suggest = SecLiveTickerSuggest(http, cache_ttl=timedelta(minutes=5))
    suggest.suggest("a")
    suggest.invalidate()
    suggest.suggest("a")
    assert len(http.calls) == 2


def test_satisfies_protocol() -> None:
    """The runtime Protocol check should accept SecLiveTickerSuggest."""
    http = _StubHttp(_legacy_payload())
    suggest: TickerSuggest = SecLiveTickerSuggest(http)
    assert isinstance(suggest, TickerSuggest)
