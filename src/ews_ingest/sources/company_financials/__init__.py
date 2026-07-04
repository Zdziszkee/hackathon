"""Category 1 — Company Financials (SEC). Importing registers all connectors."""

from __future__ import annotations

from ews_ingest.sources.company_financials import (  # noqa: F401
    company_facts,
    concept_frames,
    dera_bulk,
    fulltext_search,
    submissions,
)
