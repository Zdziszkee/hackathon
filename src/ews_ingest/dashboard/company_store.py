"""Dynamic company store: persistent JSON-backed portfolio the dashboard can edit.

Replaces the static ``config/entities.yaml`` universe with a runtime-extensible
list keyed by ticker. Adding a company only needs a ticker — the store resolves
CIK + legal name + SIC-derived sector from SEC EDGAR (either from the landed
``universe.sec_company_tickers`` dataset, or a live EDGAR lookup if no record
has landed yet).

Decoupling from the ingestion layer is preserved:

* the store lives in ``dashboard/`` (UI concern), persists to a JSON file the
  ingestion layer also reads via ``config.py::_load_entities`` — both sides
  agree on the file format but neither imports the other;
* the SEC onboarding calls reuse the existing :mod:`ews_ingest.providers.sec`
  transport — no new provider, no new source;
* sector derivation reuses the canonical SIC→sector map shared with the
  ``industry`` signal so the rest of the pipeline keeps working unchanged.

The JSON schema is identical to ``entities.yaml`` (one ``Identifiers`` per
entry) so existing loaders / tests treat both transparently.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any

from ews_ingest.core.http import HttpClient, RatePolicy
from ews_ingest.core.models import Identifiers
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
    """JSON-backed portfolio the dashboard edits and the ingestion layer reads.

    The on-disk format is a JSON array of ``Identifiers``-shaped dicts::

        [{"ticker": "UPS", "cik": "0001090727", "name": "UNITED PARCEL SERVICE",
          "extra_ids": {"sector": "transport_logistics", "country": "US"}}, ...]

    This is byte-identical (semantically) to ``entities.yaml`` so the existing
    loaders and tests treat either path without branching on the format.
    """

    def __init__(
        self,
        path: Path,
        *,
        http: HttpClient | None = None,
        landing_lookup: Callable[[str], list[dict[str, object]]] | None = None,
        sector_lookup: SectorLookup | None = None,
    ) -> None:
        self._path = path
        self._http = http
        self._lock = RLock()
        # Landing zone lookup: ``ticker -> list[landed payload row]``. Optional
        # so this module can be constructed in tests without an ingestion layer.
        self._landing_lookup = landing_lookup
        # Optional sector lookup (Yahoo Finance ``quoteSummary``). When
        # omitted, companies are added without a sector — the signal layer
        # renders "unavailable" for sector-routed indicators.
        self._sector_lookup = sector_lookup

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------ load
    def load(self) -> list[Identifiers]:
        """Read every company from the JSON file (empty list if absent)."""
        if not self._path.exists():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _log.warning("companies file %s is corrupt — treating as empty", self._path)
            return []
        if not isinstance(raw, list):
            return []
        return [Identifiers.model_validate(entry) for entry in raw]

    # -------------------------------------------------------------- mutations
    def add_ticker(self, ticker: str) -> Identifiers:
        """Resolve + persist a company by stock ticker (uppercased).

        Resolution priority:
        1. Already in the store → return the existing entry (idempotent re-add).
        2. Landed ``universe.sec_company_tickers`` JSONL records.
        3. Live SEC ``company_tickers.json`` lookup.

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
            entities = self.load()
            kept = [e for e in entities if (e.ticker or "").upper() != ticker]
            removed = len(kept) != len(entities)
            if removed:
                self._persist_all(kept)
            return removed

    # --------------------------------------------------------------- helpers
    def _find_in_store(self, ticker: str) -> Identifiers | None:
        for e in self.load():
            if (e.ticker or "").upper() == ticker:
                return e
        return None

    def _resolve_ticker(self, ticker: str) -> tuple[str, str]:
        """Return ``(cik_zero_padded, name)`` for ``ticker``.

        Prefer landed ``universe.sec_company_tickers`` JSONL (no API key
        required, kept in sync by the existing ingestion connector); fall back
        to a live SEC ``company_tickers.json`` lookup when nothing has landed.
        """
        cik, name = self._resolve_from_landing(ticker)
        if cik is None and self._http is not None:
            cik, name = self._resolve_from_sec(ticker)
        if cik is None or name is None:
            msg = f"Could not resolve ticker {ticker!r} to a CIK + name"
            raise TickerResolutionError(msg)
        return cik, name

    def _resolve_from_landing(self, ticker: str) -> tuple[str | None, str | None]:
        if self._landing_lookup is None:
            return None, None
        for row in self._landing_lookup(_LANDING_TICKERS_SOURCE):
            if str(row.get("ticker", "")).upper() != ticker:
                continue
            cik_raw = row.get("cik")
            if cik_raw in (None, ""):
                continue
            cik = str(cik_raw)
            # Landings may carry either a zero-padded string or an int cik.
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

    # --------------------------------------------------------------- persist
    def _persist_append(self, entity: Identifiers) -> None:
        entities = self.load()
        entities.append(entity)
        self._persist_all(entities)

    def _persist_all(self, entities: list[Identifiers]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: list[dict[str, Any]] = [e.model_dump(mode="json") for e in entities]
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self._path)
