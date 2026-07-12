"""HTTP client with per-host rate limiting and retry/backoff."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

__all__ = ["HttpClient", "RatePolicy"]

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RatePolicy:
    """Per-host fair-use policy."""

    host: str
    rps: float = 1.0
    burst: int = 1
    retries: int = 3
    backoff_base: float = 1.0
    backoff_cap: float = 30.0


class _HostLimiter:
    """Reservation-based (GCRA) per-host rate limiter."""

    def __init__(self, rps: float, burst: int) -> None:
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._burst = max(1, burst)
        self._next_available = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            # Allow an initial burst by clamping the next-available floor.
            floor = now - (self._burst - 1) * self._interval
            self._next_available = max(self._next_available, floor)
            wait = max(0.0, self._next_available - now)
            self._next_available = self._next_available + self._interval
        if wait > 0:
            time.sleep(wait)


class HttpClient:
    """Thin sync wrapper over :mod:`httpx` honoring per-host rate policies."""

    def __init__(self, *, timeout: float = 30.0, sec_user_agent: str | None = None) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "ews-ingest/0.1 (+contact@example.com)"},
        )
        self._limiters: dict[str, _HostLimiter] = {}
        self._sec_user_agent = sec_user_agent or "ews-ingest contact@example.com"

    def _limiter(self, policy: RatePolicy) -> _HostLimiter:
        limiter = self._limiters.get(policy.host)
        if limiter is None:
            limiter = _HostLimiter(policy.rps, policy.burst)
            self._limiters[policy.host] = limiter
        return limiter

    @property
    def sec_user_agent(self) -> str:
        """The descriptive User-Agent required for sec.gov/data.sec.gov hosts."""
        return self._sec_user_agent

    def acquire(self, policy: RatePolicy) -> None:
        """Acquire a rate-limit token for ``policy.host`` (blocks if needed).

        Exposed so other transports (e.g. :class:`~ews_ingest.core.scrape.Scraper`)
        can share this client's per-host limiters without reaching into internals.
        """
        self._limiter(policy).acquire()

    def _headers_for(self, url: str, headers: dict[str, str] | None) -> dict[str, str]:
        merged = dict(headers or {})
        if "sec.gov" in url:
            merged.setdefault("User-Agent", self._sec_user_agent)
        elif "yahoo.com" in url or "query1.finance" in url:
            # Yahoo unofficial APIs often 401 or block without a realistic UA
            merged.setdefault("User-Agent", "Mozilla/5.0 (compatible; ews-ingest/0.1)")
        return merged

    def _sleep(self, policy: RatePolicy, attempt: int) -> None:
        delay = min(policy.backoff_cap, policy.backoff_base * (2**attempt))
        time.sleep(delay)

    def request(
        self,
        method: str,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Issue a request with rate-limit + retry; raise on non-2xx after retries."""
        merged_headers = self._headers_for(url, headers)
        attempt = 0
        while True:
            self._limiter(policy).acquire()
            try:
                resp = self._client.request(method, url, params=params, headers=merged_headers)
            except httpx.TransportError:
                if attempt >= policy.retries:
                    raise
                self._sleep(policy, attempt)
                attempt += 1
                continue
            if resp.status_code in _RETRY_STATUS and attempt < policy.retries:
                resp.close()
                self._sleep(policy, attempt)
                attempt += 1
                continue
            resp.raise_for_status()
            return resp

    def get_json(
        self,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        resp = self.request("GET", url, policy=policy, params=params, headers=headers)
        try:
            data = resp.json()
        except ValueError:
            # Some APIs (notably GDELT v2) return an HTML rate-limit/error body
            # with HTTP 200 instead of JSON. Treat that as an empty dict so
            # callers can degrade gracefully without a hard crash.
            return {"_decode_error": "non-json", "_body_excerpt": resp.text[:200]}
        if not isinstance(data, dict):
            return {"_raw": data}
        return data

    def get_json_list(
        self,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> list[object]:
        resp = self.request("GET", url, policy=policy, params=params, headers=headers)
        try:
            data = resp.json()
        except ValueError:
            # Like :meth:`get_json`: tolerate a non-JSON error body (rate limit,
            # HTML error page) by returning an empty list rather than crashing.
            return []
        if isinstance(data, list):
            return data
        return [data]

    def get_text(
        self,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        resp = self.request("GET", url, policy=policy, params=params, headers=headers)
        return resp.text

    def get_bytes(
        self,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        resp = self.request("GET", url, policy=policy, params=params, headers=headers)
        return resp.content

    def stream(
        self,
        url: str,
        *,
        policy: RatePolicy,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Iterator[bytes]:
        """Stream a (potentially large) download; no retry on partial failure."""
        merged_headers = self._headers_for(url, headers)
        self._limiter(policy).acquire()
        with self._client.stream(
            "GET", url, params=params, headers=merged_headers, timeout=120.0
        ) as response:
            response.raise_for_status()
            yield from response.iter_bytes()

    def close(self) -> None:
        self._client.close()
