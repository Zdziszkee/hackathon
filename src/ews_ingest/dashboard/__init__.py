"""Streamlit portfolio-risk dashboard.

Reads landed JSONL records written by the ingestion layer and aggregates them
into per-company risk indicators. Indicators are pluggable via the
:class:`SignalProvider` protocol; bindings (role -> source_id per region) live in
``config/indicators.yaml``.
"""

from __future__ import annotations

from ews_ingest.dashboard.bindings import IndicatorBindings, load_bindings
from ews_ingest.dashboard.companies import Company, load_companies
from ews_ingest.dashboard.demo import DemoValues
from ews_ingest.dashboard.env import EnvResolver
from ews_ingest.dashboard.landing import LandingReader
from ews_ingest.dashboard.signals import SignalContext, SignalResult, list_providers

__all__ = [
    "Company",
    "DemoValues",
    "EnvResolver",
    "IndicatorBindings",
    "LandingReader",
    "SignalContext",
    "SignalResult",
    "list_providers",
    "load_bindings",
    "load_companies",
]
