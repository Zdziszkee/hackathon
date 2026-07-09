"""Source configuration (sources.yaml) + service/context wiring."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ews_ingest.core.context import FetchContext
from ews_ingest.core.entities import YamlEntityResolver
from ews_ingest.core.http import HttpClient, RatePolicy
from ews_ingest.core.landing import JsonlLandWriter
from ews_ingest.core.models import Identifiers, SourceType
from ews_ingest.core.scrape import Scraper

__all__ = [
    "Services",
    "SourceConfig",
    "build_context",
    "check_env",
    "load_entities_file",
    "load_sources",
    "make_services",
]


class SourceConfig(BaseModel):
    """One entry from ``config/sources.yaml``."""

    model_config = ConfigDict(extra="ignore")

    source_id: str
    source_type: SourceType = SourceType.API
    host: str
    rps: float = 1.0
    burst: int = 1
    retries: int = 3
    enabled: bool = True
    backfill: str = "5y"
    env_required: list[str] = Field(default_factory=list)

    def rate_policy(self) -> RatePolicy:
        return RatePolicy(
            host=self.host,
            rps=self.rps,
            burst=self.burst,
            retries=self.retries,
        )


def load_sources(path: Path) -> dict[str, SourceConfig]:
    """Load all source entries, indexed by ``source_id``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = cast(list[dict[str, object]], raw)
    out: dict[str, SourceConfig] = {}
    for entry in entries:
        cfg = SourceConfig.model_validate(entry)
        out[cfg.source_id] = cfg
    return out


def check_env(cfg: SourceConfig) -> list[str]:
    """Return the list of required-but-unset env vars for a source."""
    return [var for var in cfg.env_required if not os.environ.get(var, "")]


@dataclass
class Services:
    """Long-lived shared services reused across fetch runs."""

    http: HttpClient
    scraper: Scraper
    writer: JsonlLandWriter
    resolver: YamlEntityResolver
    logger: logging.Logger
    sources: dict[str, SourceConfig]


def load_entities_file(path: Path) -> list[Identifiers]:
    """Read a company universe from a JSON or YAML file.

    Both formats share the same ``Identifiers`` schema (an array of
    ``Identifiers``-shaped dicts). The dashboard persists companies to JSON
    (:mod:`ews_ingest.dashboard.company_store`); the legacy ``entities.yaml``
    is supported for backfill and integration tests.
    """
    if not path.exists():
        return []
    if path.suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get("companies") if "companies" in raw else raw
    if not isinstance(raw, list):
        return []
    entries = cast(list[dict[str, object]], raw)
    return [Identifiers.model_validate(entry) for entry in entries]


def make_services(
    *,
    landing_dir: Path,
    entities_path: Path,
    sources_path: Path,
    sec_user_agent: str | None = None,
) -> Services:
    """Build the shared service bundle from config paths + env.

    ``entities_path`` may point to either ``entities.yaml`` (legacy, hand-curated)
    or ``companies.json`` (dynamic, edited from the dashboard). The on-disk
    schema is identical so both go through :func:`load_entities_file`.
    """
    logger = logging.getLogger("ews_ingest")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    http = HttpClient(sec_user_agent=sec_user_agent)
    return Services(
        http=http,
        scraper=Scraper(http),
        writer=JsonlLandWriter(landing_dir),
        resolver=YamlEntityResolver(load_entities_file(entities_path)),
        logger=logger,
        sources=load_sources(sources_path),
    )


def build_context(
    services: Services,
    source_id: str,
    run_id: str,
    since: date | None = None,
) -> FetchContext:
    """Construct a per-run :class:`FetchContext` from shared services."""
    cfg = services.sources.get(source_id)
    if cfg is None:
        # Source not yet in sources.yaml: use a per-source default policy so the
        # system is runnable before the registry is fully populated.
        default_policy = RatePolicy(host=source_id, rps=1.0, burst=1, retries=2)
        return FetchContext(
            http=services.http,
            scraper=services.scraper,
            writer=services.writer,
            resolver=services.resolver,
            logger=services.logger,
            run_id=run_id,
            rate_policy=default_policy,
            since=since,
        )
    return FetchContext(
        http=services.http,
        scraper=services.scraper,
        writer=services.writer,
        resolver=services.resolver,
        logger=services.logger,
        run_id=run_id,
        rate_policy=cfg.rate_policy(),
        since=since,
    )
