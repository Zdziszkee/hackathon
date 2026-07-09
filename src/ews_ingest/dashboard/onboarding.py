"""Portfolio onboarding: auto-fetch data sources for a newly-added company.

The dashboard's add-company flow calls :meth:`PortfolioOnboarding.refresh_async`
to land landing-zone data for every per-entity source + facility source
whose secondary key the new ticker carries. The orchestrator is a thin
coordinator over the existing ingestion-layer primitives — it does not
change the connector protocol, the landing writer, or the registry.

Design choices:

* **Reuses the connector protocol** — every source is still invoked via
  ``get_source(sid).fetch(ctx)`` with a per-run :class:`FetchContext`. A
  single-entity :class:`YamlEntityResolver` makes per-entity connectors
  operate on one company.
* **Per-source try/except** — one source failing (HTTP timeout, missing
  env, rate limit) does not abort the rest. The failure is recorded on
  the :class:`OnboardingTask`.
* **Concurrency cap** — ``asyncio.Semaphore(8)`` keeps the parallel
  fetch budget below the tightest rate limit (SEC at 8 RPS).
* **Scope-based eligibility** — sources are picked via
  :func:`ews_ingest.core.registry.pick_sources` with
  ``scopes={Scope.PER_ENTITY, Scope.FACILITY}``. Sector-aggregates and
  manifests run on the regular ingestion schedule, not on add.
* **FACILITY eligibility** — a FACILITY source is only run if the
  identifier has the relevant secondary key (e.g. ``usdot`` for FMCSA
  connectors). Otherwise the source would issue a request that produces
  zero records.
* **Refresh = same call** — re-adding an existing ticker or clicking the
  per-card Refresh button triggers a fresh ``refresh_async`` (the
  :class:`JsonlLandWriter` is idempotent on ``content_hash``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import ews_ingest.sources  # noqa: F401 - triggers registration
from ews_ingest.config import Services, build_context
from ews_ingest.core.entities import YamlEntityResolver
from ews_ingest.core.http import HttpClient
from ews_ingest.core.landing import JsonlLandWriter
from ews_ingest.core.models import Identifiers, RawRecord
from ews_ingest.core.protocol import Scope
from ews_ingest.core.registry import (
    get_source,
    get_source_profile,
    pick_sources,
)

__all__ = [
    "OnboardingTask",
    "PortfolioOnboarding",
    "build_onboarding",
    "ticker_in_flight",
]

# Batch size for in-flight record flushing — matches the CLI's BATCH.
_BATCH = 500

_log = logging.getLogger("ews_ingest.dashboard.onboarding")

# Facility sources are gated on these secondary identifier fields. If the
# key is missing from the identifier, the source is skipped at eligibility
# time (it would produce zero records anyway).
_FACILITY_KEY_MAP: dict[str, str] = {
    "transport.fmcsa_safer": "usdot",
    "petrochem.epa_frs": "epa_frs_id",
    "universe.epa_tri_universe": "epa_frs_id",  # universe variant still benefits from key
}

OnboardingStatus = Literal["running", "done", "failed"]


@dataclass
class OnboardingTask:
    """Live state of one in-flight onboarding refresh.

    Designed to be cheaply cloneable into ``st.session_state`` — the
    dashboard polls this object on every rerun to render a progress
    panel and to decide whether to disable the per-card Refresh button.
    """

    task_id: str
    ticker: str
    started_at: datetime
    sector: str = ""  # free-form Yahoo sector string (or "" if not yet fetched)
    sources_total: int = 0
    sources_done: int = 0
    sources_failed: int = 0
    sources_written: int = 0
    status: OnboardingStatus = "running"
    error: str | None = None
    sources_attempted: list[str] = field(default_factory=list)
    sources_succeeded: list[str] = field(default_factory=list)
    sources_errored: list[tuple[str, str]] = field(default_factory=list)
    finished_at: datetime | None = None

    def elapsed_seconds(self) -> float:
        end = self.finished_at or datetime.now(UTC)
        return (end - self.started_at).total_seconds()

    def progress_fraction(self) -> float:
        if self.sources_total == 0:
            return 0.0
        return (self.sources_done + self.sources_failed) / self.sources_total


class PortfolioOnboarding:
    """Coordinator for "I just added a ticker — go fetch its data".

    The orchestrator owns a long-lived :class:`Services` bundle and a
    per-task :class:`FetchContext` (with a single-entity resolver so
    per-entity connectors naturally process the one company). All
    fetching is async; sync callers (the CLI) wrap with
    :func:`asyncio.run`.

    Failure model: a per-source exception increments ``sources_failed``
    and logs the error, but the rest of the eligible sources continue.
    The overall task transitions to ``status="failed"`` only if *all*
    sources failed.
    """

    def __init__(
        self,
        services: Services,
        *,
        http: HttpClient | None = None,
        concurrency: int = 8,
        writer: JsonlLandWriter | None = None,
    ) -> None:
        self._services = services
        # The ``http`` and ``writer`` overrides let tests inject fakes; the
        # CLI/dashboard paths reuse the services' own.
        self._http = http
        self._writer = writer
        self._semaphore_value = concurrency

    async def refresh_async(self, identifier: Identifiers) -> OnboardingTask:
        """Fetch + land every eligible source for ``identifier``.

        Returns the :class:`OnboardingTask` once the entire batch is done
        (synchronous with the call; useful for tests + sync CLI wrappers).
        """
        sector_label = identifier.extra_ids.get("sector", "")
        eligible = self._eligible_sources(identifier)
        task = OnboardingTask(
            task_id=uuid.uuid4().hex[:12],
            ticker=identifier.ticker or "?",
            sector=sector_label,
            started_at=datetime.now(UTC),
            sources_total=len(eligible),
        )

        if not eligible:
            task.status = "done"
            task.finished_at = datetime.now(UTC)
            return task

        run_id = task.task_id
        sem = asyncio.Semaphore(self._semaphore_value)

        async def _run_one(source_id: str) -> None:
            async with sem:
                task.sources_attempted.append(source_id)
                try:
                    count = await asyncio.to_thread(
                        self._fetch_and_land, source_id, identifier, run_id
                    )
                except Exception as exc:
                    task.sources_failed += 1
                    task.sources_errored.append((source_id, str(exc)))
                    _log.warning(
                        "onboarding fetch failed: ticker=%s source=%s err=%s",
                        identifier.ticker,
                        source_id,
                        exc,
                    )
                else:
                    task.sources_done += 1
                    task.sources_succeeded.append(source_id)
                    task.sources_written += count

        await asyncio.gather(*(_run_one(sid) for sid in eligible))

        task.status = "failed" if task.sources_done == 0 and task.sources_failed else "done"
        task.finished_at = datetime.now(UTC)
        return task

    def refresh_blocking(self, identifier: Identifiers) -> OnboardingTask:
        """Sync entry: ``asyncio.run`` the async refresh. Used by the CLI."""
        return asyncio.run(self.refresh_async(identifier))

    # -------------------------------------------------------- eligibility

    def _eligible_sources(self, identifier: Identifiers) -> list[str]:
        """Return source_ids that should be fetched for this identifier.

        Filters:

        1. Source's ``scope`` must be ``PER_ENTITY`` or ``FACILITY``.
        2. Source must be enabled in ``sources.yaml``.
        3. Required env vars for the source must be present (or the
           source would 401/403 anyway).
        4. FACILITY sources additionally require the relevant secondary
           key on the identifier (e.g. ``usdot`` for FMCSA).
        """
        picked = pick_sources(scopes={Scope.PER_ENTITY, Scope.FACILITY})
        eligible: list[str] = []
        for sid in picked:
            profile = get_source_profile(sid)
            cfg = self._services.sources.get(sid)
            if cfg is None or not cfg.enabled:
                continue
            if self._missing_env(cfg):
                continue
            if profile.scope is Scope.FACILITY:
                required_key = _FACILITY_KEY_MAP.get(sid)
                if required_key is not None and not getattr(identifier, required_key):
                    continue
            eligible.append(sid)
        return eligible

    def _missing_env(self, cfg: object) -> list[str]:
        env_required = getattr(cfg, "env_required", ()) or ()
        return [var for var in env_required if not os.environ.get(var, "")]

    # ------------------------------------------------------- per-source I/O

    def _fetch_and_land(self, source_id: str, identifier: Identifiers, run_id: str) -> int:
        """Sync helper executed in a thread — runs the connector and writes
        records. Returns the count of new records actually persisted.
        """
        cfg = self._services.sources.get(source_id)
        if cfg is None:
            msg = f"source {source_id!r} not in sources.yaml"
            raise KeyError(msg)
        # Build a per-source single-entity resolver so per-entity connectors
        # operate on the one company.
        single = YamlEntityResolver([identifier])
        ctx = build_context(self._services, source_id, run_id)
        # Swap in the single-entity resolver after build_context (which
        # uses the bundle's full resolver).
        object.__setattr__(ctx, "resolver", single)
        writer = self._writer or self._services.writer
        batch: list[RawRecord] = []
        total = 0
        for rec in get_source(source_id).fetch(ctx):
            batch.append(rec)
            if len(batch) >= _BATCH:
                total += writer.write(batch)
                batch.clear()
        if batch:
            total += writer.write(batch)
        return total


def ticker_in_flight(state: dict[str, OnboardingTask], ticker: str) -> OnboardingTask | None:
    """Return the active (or most recently completed) task for ``ticker``."""
    return state.get(ticker.upper())


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_onboarding(
    *,
    landing_dir: str | None = None,
    concurrency: int = 8,
) -> PortfolioOnboarding:
    """Build a :class:`PortfolioOnboarding` from the standard service bundle.

    Reads ``EWS_LANDING_DIR`` (default ``./data/landing``), the
    ``companies.json`` or ``entities.yaml`` path (via the same rules as
    :mod:`ews_ingest.cli`), and ``config/sources.yaml``.

    The ``landing_dir`` override exists for tests; the CLI path should
    use :func:`ews_ingest.cli._services_from_env` directly via
    :class:`PortfolioOnboarding`'s public constructor.
    """
    from ews_ingest.cli import _services_from_env  # noqa: PLC0415 - cycle

    if landing_dir is not None:
        os.environ["EWS_LANDING_DIR"] = landing_dir
    services = _services_from_env()
    return PortfolioOnboarding(services, concurrency=concurrency)
