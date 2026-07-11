"""Service wiring for the Streamlit dashboard.

Owns the constructors for :class:`HttpClient`, :class:`LandingReader`,
:class:`CompanyStore`, the ticker suggester, the sector lookup, and the
:func:`SignalContext`. Exposes a single :func:`get_inputs` entry point
that the dashboard calls on every render — the result is cached for the
lifetime of the Streamlit process so repeated reruns don't re-parse the
JSON store or rebuild the HTTP client.

On mutating actions (Add / Remove) the cache is invalidated via
:func:`bust_inputs_cache`.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from ews_ingest.config import Services, SourceConfig, build_context, check_env, make_services
from ews_ingest.core.entities import YamlEntityResolver
from ews_ingest.core.http import HttpClient
from ews_ingest.core.models import RawRecord
from ews_ingest.core.registry import all_source_ids, get_source
from ews_ingest.dashboard.bindings import IndicatorBindings, load_bindings
from ews_ingest.dashboard.companies import Company, load_companies
from ews_ingest.dashboard.company_store import CompanyStore
from ews_ingest.dashboard.db import HistoricalStore
from ews_ingest.dashboard.env import EnvResolver
from ews_ingest.dashboard.landing import LandingReader
from ews_ingest.dashboard.signals import SignalContext
from ews_ingest.dashboard.ticker_suggest import SecLiveTickerSuggest, TickerSuggest
from ews_ingest.dashboard.yahoo_sector import SecLiveYahooSector, SectorLookup

__all__ = [
    "CONFIG_DIR",
    "Inputs",
    "bust_inputs_cache",
    "companies_path",
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
# Path helpers
# ---------------------------------------------------------------------------


def companies_path() -> Path:
    """Resolve the dynamic JSON company-store path (env-overridable)."""
    return Path(
        os.environ.get(
            "EWS_COMPANIES_PATH",
            Path(os.environ.get("EWS_COMPANIES_DIR", "./data/companies")) / "companies.json",
        )
    )


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
    # Imported lazily to avoid pulling the full config module into a
    # tight import chain (it transitively imports the CLI).
    from ews_ingest.config import load_sources  # noqa: PLC0415

    return load_sources(path)


def make_landing_reader() -> LandingReader:
    return LandingReader(Path(os.environ.get("EWS_LANDING_DIR", "./data/landing")))


def make_historical_store() -> HistoricalStore:
    db_path = Path(os.environ.get("EWS_DB_PATH", "./data/ews.db"))
    return HistoricalStore(db_path)


def trigger_refresh(ticker: str | None = None) -> None:  # noqa: C901
    """Trigger refresh for a company (or global if None) in background thread.
    Marks pending, runs sources to update DB (and landing).
    UI should watch DB for updates.
    """

    def _run() -> None:  # noqa: C901
        try:
            services = make_services_from_env()
            hist = make_historical_store()
            source_ids = list(all_source_ids())
            for sid in source_ids:
                cfg = services.sources.get(sid)
                if not cfg or not cfg.enabled:
                    continue
                if check_env(cfg):
                    continue
                ctx = build_context(services, sid, "force-" + (ticker or "global"))
                if ticker:
                    # find the company
                    for comp in load_companies(companies_path()):
                        if comp.identifiers.ticker == ticker:
                            ctx.resolver = YamlEntityResolver([comp.identifiers])
                            break
                source = get_source(sid)
                batch_size = 100
                batch: list[RawRecord] = []
                for rec in source.fetch(ctx):
                    batch.append(rec)
                    if len(batch) >= batch_size:
                        services.writer.write(batch)
                        # also to hist
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
        except Exception:  # noqa: S110
            pass  # TODO: log failure

    threading.Thread(target=_run, daemon=True).start()


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
    return CompanyStore(
        companies_path(),
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

    Used by the onboarding orchestrator — the rest of the dashboard uses
    the smaller DI pair above because :class:`CompanyStore` and the
    ticker suggester don't need the full bundle.
    """
    from ews_ingest.cli import _default_entities_path  # noqa: PLC0415 - lazy to avoid cli cycle

    return make_services(
        landing_dir=Path(os.environ.get("EWS_LANDING_DIR", "./data/landing")),
        entities_path=_default_entities_path(),
        sources_path=CONFIG_DIR / "sources.yaml",
        sec_user_agent=os.environ.get("SEC_USER_AGENT"),
    )


# ---------------------------------------------------------------------------
# Process-wide caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_inputs() -> Inputs:
    landing = make_landing_reader()
    http = make_http_client()
    sector_lookup = make_sector_lookup(http=http)
    store = make_company_store(landing, http=http, sector_lookup=sector_lookup)
    return (
        load_companies(store.path),
        landing,
        make_env_resolver(),
        store,
        make_ticker_suggest(http=http),
    )


def bust_inputs_cache() -> None:
    """Force :func:`get_inputs` to re-read the JSON store on next render."""
    get_inputs.cache_clear()


@lru_cache(maxsize=1)
def get_bindings() -> IndicatorBindings:
    return load_bindings(CONFIG_DIR / "indicators.yaml")
