"""Dynamic company store backed by the shared SQLite DB (table `companies`).

Replaces the static ``config/entities.yaml`` with a runtime-extensible list.
Add uses ticker resolution (SEC + sector lookup) and persists to DB.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from threading import RLock

from ews_ingest.core.http import HttpClient, RatePolicy
from ews_ingest.core.models import Identifiers
from ews_ingest.dashboard.db import HistoricalStore
from ews_ingest.dashboard.yahoo_sector import SectorLookup, SectorLookupError

__all__ = ["CompanyStore", "TickerResolutionError"]

_log = logging.getLogger("ews_ingest.dashboard.company_store")

_SEC_RATE_POLICY = RatePolicy(host="www.sec.gov", rps=8.0, burst=1, retries=3)

_LANDING_TICKERS_SOURCE = "universe.sec_company_tickers"


class TickerResolutionError(ValueError):
    """Raised when a ticker cannot be resolved to a CIK by any available source."""


def _sic_from_value(sic: object) -> str | None:
    """Coerce a SEC submissions SIC field (scalar OR list) to a str."""
    if isinstance(sic, list) and sic:
        return str(sic[0])
    if isinstance(sic, (str, int)):
        return str(sic)
    return None


class CompanyStore:
    """SQLite-backed portfolio (migrated from JSON).

    Companies are now stored in the same SQLite DB as historical records
    (table "companies") to simplify the stack to a single storage backend.

    The in-memory / resolver format remains ``Identifiers``.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        http: HttpClient | None = None,
        landing_lookup: Callable[[str], list[dict[str, object]]] | None = None,
        sector_lookup: SectorLookup | None = None,
    ) -> None:
        self._db_path = db_path
        self._http = http
        self._lock = RLock()
        # Landing zone lookup...
        self._landing_lookup = landing_lookup
        self._sector_lookup = sector_lookup
        # Internal store for persistence (same DB file as records)
        self._hist = HistoricalStore(db_path)

    @property
    def path(self) -> Path:
        """The DB path used for this store."""
        return self._db_path

    # ------------------------------------------------------------------ load
    def load(self) -> list[Identifiers]:
        """Read companies from the SQLite DB (empty list if none)."""
        return self._hist.list_companies()

    # -------------------------------------------------------------- mutations
    def add_ticker(self, ticker: str) -> Identifiers:
        """Resolve + persist a company by stock ticker (uppercased).

        Resolution priority:
        1. Already in the store → return the existing entry (idempotent re-add).
        2. Universe tickers from SQLite (populated by universe.sec_company_tickers source).
        3. Live SEC lookup.

        Sector is fetched dynamically via the injected ``sector_lookup``
        (default: Yahoo Finance ``quoteSummary``). Failures are caught —
        the company is still added; the signal layer renders
        "unavailable" for sector-routed indicators when the sector is
        missing. Country defaults to ``US`` for SEC-listed US public
        filers.

        Raises :class:`TickerResolutionError` when the ticker cannot be resolved
        by any available source.
        """
        ticker = ticker.strip().upper()
        if not ticker:
            msg = "ticker must not be empty"
            raise TickerResolutionError(msg)
        with self._lock:
            existing = self._find_in_store(ticker)
            if existing is not None:
                return existing
            cik, name = self._resolve_ticker(ticker)
            sector_extras = self._fetch_sector_extras(ticker)
            entity = Identifiers(
                ticker=ticker,
                cik=cik,
                name=name,
                extra_ids={**sector_extras, "country": "US"},
            )
            self._persist_append(entity)
            return entity

    def remove_ticker(self, ticker: str) -> bool:
        """Drop the company with this ticker (case-insensitive). Returns whether
        a row was actually removed."""
        ticker = ticker.strip().upper()
        with self._lock:
            return self._hist.remove_company(ticker)

    # --------------------------------------------------------------- helpers
    def _find_in_store(self, ticker: str) -> Identifiers | None:
        for e in self.load():
            if (e.ticker or "").upper() == ticker:
                return e
        return None

    def _resolve_ticker(self, ticker: str) -> tuple[str, str]:
        """Return ``(cik_zero_padded, name)`` for ``ticker``.

        Prefer universe tickers from SQLite (populated from sec_company_tickers source);
        fall back to landed data or live SEC lookup.
        """
        cik, name = self._resolve_from_universe(ticker)
        if cik is None and self._http is not None:
            cik, name = self._resolve_from_sec(ticker)
        if cik is None or name is None:
            msg = f"Could not resolve ticker {ticker!r} to a CIK + name"
            raise TickerResolutionError(msg)
        return cik, name

    def _resolve_from_universe(self, ticker: str) -> tuple[str | None, str | None]:
        # Prefer SQL universe (populated when universe.sec_company_tickers records written)
        if self._hist:
            u = self._hist.get_universe_ticker(ticker)
            if u and u.get("cik"):
                cik = str(u["cik"])
                if cik.isdigit():
                    cik = cik.zfill(10)
                return cik, u.get("name")
        # Fallback to legacy landing lookup if provided
        if self._landing_lookup is None:
            return None, None
        for row in self._landing_lookup(_LANDING_TICKERS_SOURCE):
            if str(row.get("ticker", "")).upper() != ticker:
                continue
            cik_raw = row.get("cik")
            if cik_raw in (None, ""):
                continue
            cik = str(cik_raw)
            if cik.isdigit():
                cik = cik.zfill(10)
            name = str(row.get("name") or "")
            return cik, name or None
        return None, None

    def _resolve_from_sec(self, ticker: str) -> tuple[str | None, str | None]:
        if self._http is None:
            return None, None
        try:
            # ``sec.tickers_exchange`` already normalizes both the legacy dict
            # shape AND the new (2025) ``{fields, data}`` row-array shape into a
            # flat list of dicts with ``cik``/``ticker``/``name`` keys.
            from ews_ingest.providers import sec as sec_api

            rows = sec_api.tickers_exchange(self._http, _SEC_RATE_POLICY)
        except Exception as exc:
            _log.info("SEC company_tickers lookup failed for %s: %s", ticker, exc)
            return None, None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("ticker", "")).upper() != ticker:
                continue
            cik = str(row.get("cik") or "")
            if not cik.isdigit():
                continue
            return cik.zfill(10), str(row.get("name") or "")
        return None, None

    def _derive_sector(self, _cik: str) -> str:  # kept for back-compat with tests
        """Deprecated: prefer the constructor-injected ``sector_lookup``.

        Returns ``""`` (no sector) since the central SIC→sector mapping
        was removed. Kept so existing tests don't break; will be deleted
        in a follow-up.
        """
        return ""

    def _fetch_sector_extras(self, ticker: str) -> dict[str, str]:
        """Call the injected :class:`SectorLookup` and merge into extras.

        Any failure (no lookup, lookup error, empty result) returns an
        empty dict — the company is still added; sector-routed
        indicators will render "unavailable".
        """
        if self._sector_lookup is None:
            return {}
        try:
            result = self._sector_lookup.lookup(ticker)
        except SectorLookupError as exc:
            _log.info("sector lookup failed for %s: %s", ticker, exc)
            return {}
        return dict(result.extra_ids)

    def _sic_from_landing(self, cik: str) -> str | None:  # kept for back-compat
        """Deprecated: SIC→sector mapping is gone. Returns the raw SIC
        from landed submissions records (or ``None``) for callers that
        need it (e.g. industry signal).
        """
        if self._landing_lookup is None:
            return None
        for row in self._landing_lookup("company_financials.submissions"):
            raw_entities = row.get("entities")
            entities = raw_entities if isinstance(raw_entities, list) else []
            for ent in entities:
                if not isinstance(ent, dict):
                    continue
                if str(ent.get("cik") or "") == cik:
                    return _sic_from_value(row.get("sic"))
            raw_payload = row.get("payload")
            payload = raw_payload if isinstance(raw_payload, dict) else None
            if payload and str(payload.get("cik") or "") == cik:
                sic = payload.get("sic") or payload.get("sicCode")
                return _sic_from_value(sic)
        return None

    def _sic_from_submissions_live(self, cik: str) -> str | None:  # back-compat
        if self._http is None:
            return None
        try:
            from ews_ingest.providers import sec as sec_api

            raw = sec_api.submissions(self._http, _SEC_RATE_POLICY, cik)
        except Exception as exc:
            _log.info("SEC submissions lookup failed for CIK=%s: %s", cik, exc)
            return None
        return _sic_from_value(raw.get("sicDescription") or raw.get("sic") or raw.get("sicCode"))

    # --------------------------------------------------------------- persist (now via SQLite)
    def _persist_append(self, entity: Identifiers) -> None:
        self._hist.upsert_company(entity)
