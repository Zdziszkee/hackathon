"""Integration tests — gated by EWS_RUN_INTEGRATION=1 (hit live network)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import ews_ingest.sources  # noqa: F401 - triggers registration
from ews_ingest.config import Services, build_context, make_services
from ews_ingest.core.entities import YamlEntityResolver
from ews_ingest.core.models import Identifiers
from ews_ingest.core.registry import get_source

pytestmark = pytest.mark.integration
_ENABLED = bool(os.environ.get("EWS_RUN_INTEGRATION"))


def _services(landing_dir: Path) -> Services:
    return make_services(
        landing_dir=landing_dir,
        entities_path=Path("src/ews_ingest/config/entities.yaml"),
        sources_path=Path("src/ews_ingest/config/sources.yaml"),
    )


def _one_entity_resolver(ent: Identifiers) -> YamlEntityResolver:
    return YamlEntityResolver([ent])


@pytest.mark.skipif(not _ENABLED, reason="set EWS_RUN_INTEGRATION=1 to run live tests")
def test_yahoo_fetch_one_ticker(tmp_path: Path) -> None:
    services = _services(tmp_path)
    ctx = build_context(services, "credit_market.yahoo", run_id="int")
    ctx.resolver = _one_entity_resolver(Identifiers(ticker="AAPL", name="Apple Inc."))
    src = get_source("credit_market.yahoo")
    assert any(True for _ in src.fetch(ctx))


@pytest.mark.skipif(not _ENABLED, reason="set EWS_RUN_INTEGRATION=1 to run live tests")
def test_gdelt_sector_query_smoke(tmp_path: Path) -> None:
    services = _services(tmp_path)
    ctx = build_context(services, "news.gdelt", run_id="int2")
    ctx.resolver = _one_entity_resolver(Identifiers(name="XPO Inc"))
    src = get_source("news.gdelt")
    # Network may legitimately return no hits; just ensure no exception.
    list(src.fetch(ctx))


@pytest.mark.skipif(not _ENABLED, reason="set EWS_RUN_INTEGRATION=1 to run live tests")
def test_google_news_rss_smoke(tmp_path: Path) -> None:
    services = _services(tmp_path)
    ctx = build_context(services, "news.google_news_rss", run_id="int3")
    ctx.resolver = _one_entity_resolver(Identifiers(name="XPO Inc"))
    src = get_source("news.google_news_rss")
    # Network may legitimately return no hits; just ensure no exception.
    list(src.fetch(ctx))
