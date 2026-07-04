"""Category 2 — Adverse media / sanctions / PEP (spec §2)."""

from __future__ import annotations

from ews_ingest.sources.sanctions import (  # noqa: F401
    consolidated_screening,
    eu_sanctions,
    ofac_sdn,
    opensanctions,
    un_security,
    world_bank_debarred,
)
