"""HTML scraper for true web-scraping targets (spec: use scrapling).

Uses scrapling's fetchers directly, matching the spec's instruction that scrapling
is for ``Scrape`` targets (HTML pages with no official API/feed; possibly
JS-rendered or protected by anti-bot systems like Cloudflare Turnstile).
Three fetch modes cover the spectrum:

- ``FetchMode.HTTP`` (default): :class:`Fetcher.get` — fast HTTP requests with
  browser TLS-fingerprint impersonation. Sufficient for static-HTML targets
  (IR sites, press releases, state DOL, ISM, ATA, CSB). No browser binaries
  required on import; uses ``curl_cffi``.
- ``FetchMode.STEALTH``: :class:`StealthyFetcher.fetch` — anti-bot bypass +
  optional JS rendering via a real Chrome browser. Use for Cloudflare-protected
  or JS-heavy sources. Requires a system Chrome (``real_chrome=True``) —
  on Ubuntu 26.04 playwright's bundled chromium isn't built, so we drive the
  system Google Chrome instead (verified working: Chrome 149).
- ``FetchMode.DYNAMIC``: :class:`DynamicFetcher.fetch` — full Playwright-driven
  browser automation for the heaviest dynamic pages.

Per-host rate limiting stays central: connectors call :meth:`Scraper.fetch_html`
which acquires a token from the shared :class:`HttpClient` limiter before
invoking the scrapling fetcher, so throttling/respect for ``sec.gov`` stays in
one place. The mandated descriptive ``User-Agent`` header is forwarded to
scrapling for ``sec.gov``/``data.sec.gov``/``efts.sec.gov`` hosts.

httpx remains the transport for ``API``/``Bulk file`` sources
(:class:`HttpClient`); scrapling stays the transport for ``Scrape`` sources
(:class:`Scraper`).
"""

from __future__ import annotations

from enum import StrEnum

from scrapling.fetchers import DynamicFetcher, Fetcher, StealthyFetcher

from ews_ingest.core.http import HttpClient, RatePolicy

__all__ = ["FetchMode", "Scraper"]


class FetchMode(StrEnum):
    """Which scrapling fetcher to use for an HTML target."""

    HTTP = "http"  # Fetcher.get (TLS-impersonated HTTP, no browser)
    STEALTH = "stealth"  # StealthyFetcher.fetch (anti-bot, JS render, real Chrome)
    DYNAMIC = "dynamic"  # DynamicFetcher.fetch (full browser automation)


class Scraper:
    """Fetch HTML via scrapling's fetchers; reuse shared HttpClient rate limits."""

    def __init__(
        self,
        http: HttpClient,
        *,
        timeout: int = 30,
        use_real_chrome: bool = True,
    ) -> None:
        self._http = http
        self._timeout = timeout
        self._use_real_chrome = use_real_chrome

    def _headers_for(self, url: str, headers: dict[str, str] | None) -> dict[str, str] | None:
        merged = dict(headers) if headers else {}
        if "sec.gov" in url:
            merged.setdefault("User-Agent", self._http.sec_user_agent)
        return merged or None

    def fetch_html(
        self,
        url: str,
        *,
        policy: RatePolicy,
        headers: dict[str, str] | None = None,
        mode: FetchMode = FetchMode.HTTP,
        network_idle: bool = False,
    ) -> object:
        """Return a scrapling parsed response (``Response``/``Adaptor``) for ``url``.

        Parameters
        ----------
        mode:
            Which scrapling fetcher to use (see :class:`FetchMode`).
        network_idle:
            For ``STEALTH``/``DYNAMIC`` modes only — wait for network-idle
            before returning (useful for JS-rendered content).
        """
        self._http.acquire(policy)
        scraped_headers = self._headers_for(url, headers)
        if mode is FetchMode.HTTP:
            page = Fetcher.get(
                url,
                timeout=self._timeout,
                headers=scraped_headers,
            )
        elif mode is FetchMode.STEALTH:
            page = StealthyFetcher.fetch(
                url,
                headless=True,
                real_chrome=self._use_real_chrome,
                network_idle=network_idle,
                timeout=self._timeout,
                extra_headers=scraped_headers,
            )
        elif mode is FetchMode.DYNAMIC:
            page = DynamicFetcher.fetch(
                url,
                headless=True,
                real_chrome=self._use_real_chrome,
                network_idle=network_idle,
                timeout=self._timeout,
                extra_headers=scraped_headers,
            )
        else:  # pragma: no cover - exhaustively handled by the enum
            ex = f"unsupported fetch mode: {mode!r}"
            raise ValueError(ex)
        return page
