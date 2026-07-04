"""FetchContext: dependency-injection container passed to every connector."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from ews_ingest.core.entities import EntityResolver
from ews_ingest.core.http import HttpClient, RatePolicy
from ews_ingest.core.landing import LandWriter
from ews_ingest.core.scrape import Scraper

__all__ = ["FetchContext"]


@dataclass
class FetchContext:
    """Everything a connector needs to fetch + land records (no globals)."""

    http: HttpClient
    scraper: Scraper
    writer: LandWriter
    resolver: EntityResolver
    logger: logging.Logger
    run_id: str
    rate_policy: RatePolicy
    since: date | None = None
