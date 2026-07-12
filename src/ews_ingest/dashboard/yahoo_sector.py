"""Yahoo Finance sector + industry lookup.

Resolves a ticker to the free-form ``sector`` (and optionally ``industry``)
strings Yahoo Finance reports via its unofficial ``quoteSummary`` endpoint.
The result is stored on the company's ``extra_ids`` dict (no central
vocabulary — see :mod:`ews_ingest.dashboard.signals` for how the signal
layer reads it).

Yahoo's ``quoteSummary`` is free, no key, and stable for years but
unofficial. The implementation:

* Caches in-memory keyed by ticker (no TTL — sectors don't change).
* Raises :class:`SectorLookupError` on HTTP / parse failure. The caller
  (``CompanyStore.add_ticker``) catches the error and persists the
  company with ``extra_ids["sector"] = ""``; the signal layer renders
  "unavailable" for the industry card in that case.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from ews_ingest.core.http import RatePolicy
from ews_ingest.core.models import Identifiers

__all__ = [
    "HttpLike",
    "SecLiveYahooSector",
    "SectorLookup",
    "SectorLookupError",
    "parse_asset_profile",
]


class SectorLookupError(RuntimeError):
    """Raised when the sector lookup fails (HTTP / parse / unexpected shape)."""


@runtime_checkable
class SectorLookup(Protocol):
    """Resolve a ticker to a partial :class:`Identifiers` carrying a sector.

    Implementations must be safe to call from a synchronous request
    cycle (cheap, idempotent, thread-safe). The returned identifier has
    ``extra_ids["sector"]`` set when the lookup succeeds; the caller
    merges the result into the canonical entity.
    """

    def lookup(self, ticker: str) -> Identifiers: ...


@runtime_checkable
class HttpLike(Protocol):
    """Structural subset of :class:`HttpClient` the sector lookup needs.

    Mirrors :class:`ews_ingest.dashboard.ticker_suggest.HttpLike` so
    tests can share a single stub across the ticker-autocomplete and
    sector-lookup paths.
    """

    def get_json(
        self,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]: ...


def parse_asset_profile(payload: object) -> Identifiers:
    """Extract ``sector`` (and ``industry``) from a Yahoo ``quoteSummary`` response.

    The endpoint returns ``{"quoteSummary": {"result": [{"assetProfile":
    {"sector": "Technology", "industry": "Consumer Electronics"}, ...}]}}``.
    We tolerate missing keys and any of the wrapper layers being absent
    (the older 2024 shape and the newer 2025 shape).
    """
    if not isinstance(payload, dict):
        msg = "payload is not a dict"
        raise SectorLookupError(msg)
    quote_summary = payload.get("quoteSummary")
    if not isinstance(quote_summary, dict):
        msg = "no quoteSummary in payload"
        raise SectorLookupError(msg)
    results = quote_summary.get("result")
    if not isinstance(results, list) or not results:
        msg = "no result array in quoteSummary"
        raise SectorLookupError(msg)
    first = results[0]
    if not isinstance(first, dict):
        msg = "first result is not a dict"
        raise SectorLookupError(msg)
    profile = first.get("assetProfile")
    if not isinstance(profile, dict):
        msg = "no assetProfile in result"
        raise SectorLookupError(msg)
    sector = profile.get("sector")
    industry = profile.get("industry")
    extras: dict[str, str] = {}
    if isinstance(sector, str) and sector.strip():
        extras["sector"] = sector.strip()
    if isinstance(industry, str) and industry.strip():
        extras["industry"] = industry.strip()
    return Identifiers(
        ticker=None,
        name=None,
        extra_ids=extras,
    )


class SecLiveYahooSector:
    """Live Yahoo Finance sector lookup, cached in-memory with no TTL."""

    _POLICY = RatePolicy(
        host="query1.finance.yahoo.com",
        rps=2.0,
        burst=1,
        retries=1,
        backoff_base=0.2,
        backoff_cap=1.0,
    )
    _BASE_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary"

    def __init__(self, http: HttpLike) -> None:
        # The constructor accepts the structural :class:`HttpLike` so tests
        # can inject a stub with just ``get_json``. A real
        # ``HttpClient`` satisfies the protocol structurally.
        self._http = http
        self._lock = threading.Lock()
        self._cache: dict[str, Identifiers] = {}

    def lookup(self, ticker: str) -> Identifiers:
        """Return a partial :class:`Identifiers` with ``extra_ids["sector"]``.

        On any failure raises :class:`SectorLookupError`; the caller
        decides whether to swallow it (we usually do — partial data is
        better than refusing to add the ticker).
        """
        key = ticker.strip().upper()
        if not key:
            msg = "ticker must not be empty"
            raise SectorLookupError(msg)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            url = f"{self._BASE_URL}/{key}?modules=assetProfile"
            payload = self._http.get_json(url, policy=self._POLICY)
        except Exception as exc:
            msg = f"yahoo sector lookup failed for {ticker!r}: {exc}"
            # Cache the failure (empty) so we don't hammer the endpoint again.
            empty = Identifiers(ticker=None, name=None, extra_ids={})
            with self._lock:
                self._cache[key] = empty
            raise SectorLookupError(msg) from exc
        if not isinstance(payload, dict):
            msg = f"yahoo returned non-dict payload for {ticker!r}"
            raise SectorLookupError(msg)
        result = parse_asset_profile(payload)
        # Cache both success and (empty) failure. Failures (e.g. 401) are
        # now fast because we avoid repeated slow network roundtrips.
        with self._lock:
            self._cache[key] = result
        return result

    def invalidate(self, ticker: str | None = None) -> None:
        """Drop one ticker (or all) from the cache (used by tests)."""
        with self._lock:
            if ticker is None:
                self._cache.clear()
            else:
                self._cache.pop(ticker.strip().upper(), None)
