"""Service wiring for the Streamlit dashboard.

The companies list is **always read fresh** from the SQLite DB
(table `companies` under EWS_DB_PATH or ./data/ews.db) so that
stocks added/removed in the UI survive full program restarts and
appear instantly on next launch.

Other readers (landing, http, store, suggest) are cached (lru) until
an explicit :func:`bust_inputs_cache`.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from ews_ingest.config import Services, SourceConfig, build_context, check_env, make_services
from ews_ingest.core.entities import YamlEntityResolver
from ews_ingest.core.hashing import content_hash
from ews_ingest.core.http import HttpClient
from ews_ingest.core.models import RawFormat, RawRecord, SourceType, utc_now
from ews_ingest.core.protocol import Scope
from ews_ingest.core.registry import all_source_ids, get_source, pick_sources
from ews_ingest.dashboard.bindings import IndicatorBindings, load_bindings
from ews_ingest.dashboard.companies import Company
from ews_ingest.dashboard.company_store import CompanyStore
from ews_ingest.dashboard.db import HistoricalStore
from ews_ingest.dashboard.env import EnvResolver
from ews_ingest.dashboard.landing import LandingReader
from ews_ingest.dashboard.signals import SignalContext
from ews_ingest.dashboard.ticker_suggest import SecLiveTickerSuggest, TickerSuggest
from ews_ingest.dashboard.yahoo_sector import SecLiveYahooSector, SectorLookup

logger = logging.getLogger(__name__)

__all__ = [
    "CONFIG_DIR",
    "Inputs",
    "bust_inputs_cache",
    "get_bindings",
    "get_inputs",
    "make_company_store",
    "make_env_resolver",
    "make_historical_store",
    "make_http_client",
    "make_landing_reader",
    "make_sector_lookup",
    "make_services_from_env",
    "make_signal_ctx",
    "make_ticker_suggest",
    "trigger_refresh",
]


CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# Inputs the dashboard needs on every render. Returned as a frozen
# tuple so it's hashable and easy to unpack at the call site.
Inputs = tuple[
    list[Company],
    LandingReader,
    EnvResolver,
    CompanyStore,
    TickerSuggest,
]


# ---------------------------------------------------------------------------
# Low-level factories
# ---------------------------------------------------------------------------


def make_http_client() -> HttpClient:
    return HttpClient(sec_user_agent=os.environ.get("SEC_USER_AGENT"))


def make_env_resolver() -> EnvResolver:
    sources_path = CONFIG_DIR / "sources.yaml"
    required = {sid: tuple(cfg.env_required) for sid, cfg in _load_sources(sources_path).items()}
    return EnvResolver.from_required_map(required)


def _load_sources(path: Path) -> dict[str, SourceConfig]:
    # Imported lazily to keep import graph clean.
    from ews_ingest.config import load_sources  # noqa: PLC0415

    return load_sources(path)


def make_landing_reader() -> LandingReader:
    return LandingReader(Path(os.environ.get("EWS_LANDING_DIR", "./data/landing")))


def make_historical_store() -> HistoricalStore:
    db_path = Path(os.environ.get("EWS_DB_PATH", "./data/ews.db"))
    return HistoricalStore(db_path)


def trigger_refresh(ticker: str | None = None, *, blocking: bool = False) -> None:  # noqa: C901, PLR0915
    """Trigger refresh for a company (or global if None).

    When ``ticker`` given, only runs PER_ENTITY / FACILITY sources (the ones
    that can produce per-borrower records) using a single-entity resolver.
    Writes both to landing and to HistoricalStore (for last-update timestamps).

    If blocking=True run sync (for add/refresh UX so data is present on next
    render); else fire a daemon thread.
    """

    def _run() -> None:  # noqa: C901, PLR0912, PLR0915
        services = make_services_from_env()
        hist = make_historical_store()
        logger.debug("trigger_refresh starting for ticker=%s blocking=%s", ticker, blocking)
        if ticker:
            # only the sources that actually attach to a company
            source_ids = pick_sources(scopes={Scope.PER_ENTITY, Scope.FACILITY})
        else:
            source_ids = list(all_source_ids())
        logger.debug("sources for refresh: %s", source_ids)
        for sid in source_ids:
            ctx = None
            try:
                cfg = services.sources.get(sid)
                if not cfg or not cfg.enabled:
                    continue
                if check_env(cfg):
                    logger.debug("skipping %s: missing env", sid)
                    continue
                ctx = build_context(services, sid, "force-" + (ticker or "global"))
                logger.debug("fetching source %s for %s", sid, ticker or "global")
                if ticker:
                    # find the company from SQLite (single source of truth)
                    for ident in hist.list_companies():
                        if (ident.ticker or "").upper() == ticker.upper():
                            ctx.resolver = YamlEntityResolver([ident])
                            break
                source = get_source(sid)
                batch_size = 100
                batch: list[RawRecord] = []
                for rec in source.fetch(ctx):
                    batch.append(rec)
                    if len(batch) >= batch_size:
                        services.writer.write(batch)
                        for r in batch:
                            hist.write_records(
                                sid,
                                ticker,
                                [
                                    {
                                        "fetched_at": r.fetched_at.isoformat(),
                                        "payload": r.payload,
                                        "content_hash": r.content_hash,
                                        "run_id": r.fetch_run_id,
                                    }
                                ],
                            )
                        batch = []
                if batch:
                    services.writer.write(batch)
                    for r in batch:
                        hist.write_records(
                            sid,
                            ticker,
                            [
                                {
                                    "fetched_at": r.fetched_at.isoformat(),
                                    "payload": r.payload,
                                    "content_hash": r.content_hash,
                                    "run_id": r.fetch_run_id,
                                }
                            ],
                        )
                    logger.debug(
                        "wrote batch of %d records for sid=%s ticker=%s",
                        len(batch),
                        sid,
                        ticker,
                    )
            except Exception as exc:
                logger.warning(
                    "per-entity refresh for %s failed on %s: %s",
                    ticker or "global",
                    sid,
                    exc,
                )
                if ticker and ("429" in str(exc) or "Too Many Requests" in str(exc)):
                    logger.warning("rate limit (429) detected for sid=%s ticker=%s", sid, ticker)
                    try:
                        now = utc_now()
                        rid = f"rate-{int(now.timestamp())}"
                        run_id = getattr(ctx, "run_id", rid) if ctx else rid
                        err_payload: dict[str, object] = {
                            "_rate_limited": True,
                            "message": str(exc)[:200],
                        }
                        rec = RawRecord(
                            source=sid,
                            source_type=SourceType.API,
                            fetched_at=now,
                            fetch_run_id=run_id,
                            payload=err_payload,
                            raw_format=RawFormat.JSON,
                            content_hash=content_hash(err_payload),
                            entities=[],
                        )
                        services.writer.write([rec])
                        hist.write_records(
                            sid,
                            ticker,
                            [
                                {
                                    "fetched_at": now.isoformat(),
                                    "payload": err_payload,
                                    "content_hash": rec.content_hash,
                                    "run_id": run_id,
                                }
                            ],
                        )
                        logger.info("wrote _rate_limited marker for sid=%s ticker=%s", sid, ticker)
                    except Exception:
                        logger.debug("rate limit marker write failed", exc_info=False)
                continue

        # after the for sid loop for this ticker's refresh run
        if ticker:
            try:
                now = utc_now()
                run_id = f"complete-{int(now.timestamp())}"
                payload: dict[str, object] = {"_refresh_complete": True}
                hist.write_records(
                    "_refresh_complete",
                    ticker,
                    [
                        {
                            "fetched_at": now.isoformat(),
                            "payload": payload,
                            "content_hash": content_hash(payload),
                            "run_id": run_id,
                        }
                    ],
                )
                logger.debug(
                    "_refresh_complete marker written for ticker=%s (all sources done)",
                    ticker,
                )
            except Exception:
                logger.debug("failed to write refresh complete marker for %s", ticker)

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()
    logger.debug("trigger_refresh dispatched for %s", ticker or "global")


def make_ticker_suggest(http: HttpClient | None = None) -> TickerSuggest:
    return SecLiveTickerSuggest(http or make_http_client())


def make_sector_lookup(http: HttpClient | None = None) -> SectorLookup:
    return SecLiveYahooSector(http or make_http_client())


def landing_lookup_factory(
    landing: LandingReader,
) -> Callable[[str], list[dict[str, object]]]:
    """Adapter: ``source_id -> list[{"payload":..., "entities":[...]}]``.

    Lets :class:`CompanyStore` resolve tickers/SICs from landed JSONL without
    taking a direct dependency on :mod:`ews_ingest.dashboard.landing`.
    """

    def _lookup(source_id: str) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for rec in landing.read(source_id).records:
            out.append(
                {
                    **dict(rec.payload),
                    "entities": [e.model_dump(mode="json") for e in rec.entities],
                }
            )
        return out

    return _lookup


def make_company_store(
    landing: LandingReader,
    http: HttpClient | None = None,
    sector_lookup: SectorLookup | None = None,
) -> CompanyStore:
    """An HttpClient is only needed for live SEC ticker/SIC enrichment fallback.
    We construct one lazily so the dashboard still boots if SEC_USER_AGENT is
    unset (resolution then falls back to landed data + final SEC lookup uses
    the client's default agent).
    """
    if http is None:
        http = make_http_client()
    db_path = Path(os.environ.get("EWS_DB_PATH", "./data/ews.db"))
    return CompanyStore(
        db_path,
        http=http,
        landing_lookup=landing_lookup_factory(landing),
        sector_lookup=sector_lookup,
    )


def make_signal_ctx(
    landing: LandingReader, env: EnvResolver, historical: HistoricalStore | None = None
) -> SignalContext:
    return SignalContext(
        bindings=get_bindings(),
        landing=landing,
        env_present=env.is_present,
        missing_env=env.missing_for,
        historical=historical,
    )


def make_services_from_env() -> Services:
    """Build a :class:`Services` bundle rooted at the env-configured paths.

    Companies are loaded from the DB (not a file path).
    """
    db_path = Path(os.environ.get("EWS_DB_PATH", "./data/ews.db"))
    hist = HistoricalStore(db_path)
    entities = hist.list_companies()

    return make_services(
        landing_dir=Path(os.environ.get("EWS_LANDING_DIR", "./data/landing")),
        entities_path=CONFIG_DIR / "entities.yaml",  # may not exist
        sources_path=CONFIG_DIR / "sources.yaml",
        sec_user_agent=os.environ.get("SEC_USER_AGENT"),
        entities=entities or None,
    )


# ---------------------------------------------------------------------------
# Process-wide caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_cached_inputs() -> tuple[LandingReader, EnvResolver, CompanyStore, TickerSuggest]:
    """Cached heavy parts; companies list is always read fresh from DB (via store.load) below."""
    landing = make_landing_reader()
    http = make_http_client()
    sector_lookup = make_sector_lookup(http=http)
    store = make_company_store(landing, http=http, sector_lookup=sector_lookup)
    env = make_env_resolver()
    suggest = make_ticker_suggest(http=http)
    return landing, env, store, suggest


def get_inputs() -> Inputs:
    """Always returns fresh companies list from the SQLite DB (migrated from JSON).
    Other readers are cached until bust_inputs_cache().
    """
    landing, env, store, suggest = _get_cached_inputs()
    idents = store.load()  # now DB-backed via CompanyStore (list[Identifiers])
    companies = [Company(identifiers=i) for i in idents]
    return (companies, landing, env, store, suggest)


def bust_inputs_cache() -> None:
    """Force re-creation of cached readers/store on next get_inputs().
    (The companies list is always freshly loaded from disk regardless.)
    """
    _get_cached_inputs.cache_clear()


@lru_cache(maxsize=1)
def get_bindings() -> IndicatorBindings:
    return load_bindings(CONFIG_DIR / "indicators.yaml")
