"""Ticker autocomplete for the dashboard's add-company form.

The autocomplete is a :class:`TickerSuggest` (Protocol) with one live
implementation, :class:`SecLiveTickerSuggest`, that hits the SEC's
``company_tickers_exchange.json`` once, caches the result in memory, and
serves substring matches on every keystroke. The SEC endpoint is ~1MB /
~10K rows — cheap to fetch but not cheap to refetch per keystroke, so the
cache TTL defaults to 1 hour.

Future: a ``LandedTickerSuggest`` backed by the
``universe.sec_company_tickers`` landing zone would be a drop-in
replacement (no protocol change). The landed source avoids the live call
altogether for dashboards with no network access.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast, runtime_checkable

from ews_ingest.core.http import HttpClient, RatePolicy
from ews_ingest.core.models import Identifiers
from ews_ingest.providers import sec as sec_api

__all__ = [
    "HttpLike",
    "SecLiveTickerSuggest",
    "TickerSuggest",
    "suggest_from_rows",
]


@runtime_checkable
class HttpLike(Protocol):
    """Structural subset of :class:`HttpClient` the suggester depends on.

    Lets tests pass a stub that implements just ``get_json`` without
    inheriting the full class. The signature mirrors
    :meth:`HttpClient.get_json` exactly so a real ``HttpClient`` is also
    assignable.
    """

    def get_json(
        self,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]: ...


@runtime_checkable
class TickerSuggest(Protocol):
    """Resolve a partial ticker / company-name input to candidate matches.

    Implementations must be safe to call from a Streamlit rerun cycle
    (cheap, idempotent, thread-safe). Returning an empty list signals "no
    suggestions" — the dashboard form falls back to letting the user type
    the ticker manually and resolve via :class:`CompanyStore.add_ticker`.
    """

    def suggest(self, prefix: str, *, limit: int = 10) -> list[Identifiers]: ...


def suggest_from_rows(
    rows: Iterable[Identifiers],
    prefix: str,
    *,
    limit: int = 10,
) -> list[Identifiers]:
    """Pure search over a pre-loaded row list — reusable in tests and in
    landed-data implementations.

    Ranking:

    1. **Ticker prefix matches first** (user typed the start of the ticker).
    2. **Ticker substring matches** (needle anywhere in ticker).
    3. **Name substring matches** (case-insensitive).
    4. Within each tier, alphabetical by ticker for stable ordering.

    All matching is case-insensitive.
    """
    needle = prefix.strip().lower()
    if not needle:
        # Empty prefix — return a stable alphabetical prefix of the universe
        # (rows without a ticker are filtered out — they can't be suggested).
        with_ticker = [r for r in rows if r.ticker]
        with_ticker.sort(key=lambda r: r.ticker or "")
        return with_ticker[:limit]

    ticker_prefix: list[Identifiers] = []
    ticker_substr: list[Identifiers] = []
    name_substr: list[Identifiers] = []
    for row in rows:
        ticker = (row.ticker or "").lower()
        name = (row.name or "").lower()
        if not ticker:
            continue
        if ticker.startswith(needle):
            ticker_prefix.append(row)
        elif needle in ticker:
            ticker_substr.append(row)
        elif needle in name:
            name_substr.append(row)
    ticker_prefix.sort(key=lambda r: r.ticker or "")
    ticker_substr.sort(key=lambda r: r.ticker or "")
    name_substr.sort(key=lambda r: r.name or "")
    return (ticker_prefix + ticker_substr + name_substr)[:limit]


class SecLiveTickerSuggest:
    """Live SEC company-tickers lookup, cached in-memory with a TTL.

    The SEC endpoint at ``https://www.sec.gov/files/company_tickers_exchange.json``
    returns ~10K rows of ``{cik, ticker, name, exchange}`` and is refreshed
    a few times per day. We fetch it once per ``cache_ttl`` and serve all
    keystrokes from the cached list. Network failures during a refresh
    propagate the stale cache rather than clearing it — the next call
    retries the fetch.
    """

    _DEFAULT_TTL = timedelta(hours=1)
    _POLICY = RatePolicy(host="www.sec.gov", rps=8.0, burst=1, retries=3)

    def __init__(self, http: HttpLike, *, cache_ttl: timedelta | None = None) -> None:
        # The constructor accepts the structural :class:`HttpLike` so tests
        # can inject a stub with just ``get_json``. A real ``HttpClient``
        # satisfies the protocol structurally.
        self._http = http
        self._cache_ttl = cache_ttl if cache_ttl is not None else self._DEFAULT_TTL
        self._lock = threading.Lock()
        self._cache: list[Identifiers] | None = None
        self._fetched_at: datetime | None = None

    def suggest(self, prefix: str, *, limit: int = 10) -> list[Identifiers]:
        rows = self._ensure_fresh()
        return suggest_from_rows(rows, prefix, limit=limit)

    def invalidate(self) -> None:
        """Force the next call to refetch (used by tests)."""
        with self._lock:
            self._cache = None
            self._fetched_at = None

    def _ensure_fresh(self) -> list[Identifiers]:
        with self._lock:
            if self._cache is not None and self._fetched_at is not None:
                age = datetime.now(UTC) - self._fetched_at
                if age < self._cache_ttl:
                    return self._cache
            try:
                rows = self._fetch()
            except Exception:
                # Network error during refresh: serve the stale cache if
                # we have one (better than an empty dropdown); otherwise
                # re-raise so the caller can show an "unavailable" hint.
                if self._cache is not None:
                    return self._cache
                raise
            self._cache = rows
            self._fetched_at = datetime.now(UTC)
            return rows

    def _fetch(self) -> list[Identifiers]:
        # The SEC provider requires a real ``HttpClient`` (rate-limit hooks
        # are checked). Tests inject a stub via the ``Any`` constructor, so
        # we cast at the boundary.
        client = cast(HttpClient, self._http)
        rows = sec_api.tickers_exchange(client, self._POLICY)
        out: list[Identifiers] = []
        for row in rows:
            ticker = row.get("ticker")
            cik = row.get("cik")
            if not ticker or cik in (None, ""):
                continue
            cik_str = str(cik)
            cik_str = cik_str.zfill(10) if cik_str.isdigit() else cik_str
            name = row.get("name")
            out.append(
                Identifiers(
                    cik=cik_str,
                    ticker=str(ticker).upper(),
                    name=str(name) if name else None,
                )
            )
        return out
