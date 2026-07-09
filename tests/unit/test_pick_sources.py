"""Tests for the per-source picker (scope filter only; no sector vocabulary)."""

from __future__ import annotations

import pytest

import ews_ingest.sources  # noqa: F401 - triggers registration
from ews_ingest.core.protocol import Scope
from ews_ingest.core.registry import (
    all_source_ids,
    get_source_profile,
    pick_sources,
)


def test_all_sources_have_a_profile() -> None:
    """Every registered source_id has a scope set (regression check)."""
    for sid in all_source_ids():
        profile = get_source_profile(sid)
        assert profile.scope in Scope


def test_pick_filters_by_scope() -> None:
    facility = pick_sources(scopes={Scope.FACILITY})
    assert "universe.epa_tri_universe" in facility
    assert "transport.fmcsa_census" in facility
    # No PER_ENTITY sources should leak through when we restrict to FACILITY.
    assert "company_financials.company_facts" not in facility
    assert "credit_market.yahoo" not in facility


def test_pick_per_entity_and_facility_excludes_aggregates() -> None:
    """Onboarding should only run PER_ENTITY + FACILITY, not aggregates."""
    out = pick_sources(scopes={Scope.PER_ENTITY, Scope.FACILITY})
    for sid in out:
        profile = get_source_profile(sid)
        assert profile.scope in {Scope.PER_ENTITY, Scope.FACILITY}


def test_pick_per_entity_only_excludes_aggregates_and_facility() -> None:
    out = pick_sources(scopes={Scope.PER_ENTITY})
    for sid in out:
        profile = get_source_profile(sid)
        assert profile.scope == Scope.PER_ENTITY


def test_pick_no_scope_filter_returns_everything() -> None:
    out = pick_sources()
    assert len(out) == len(all_source_ids())


def test_get_source_profile_unknown_raises() -> None:
    from ews_ingest.core.registry import get_source_profile  # noqa: PLC0415 - circular

    with pytest.raises(KeyError):
        get_source_profile("does.not.exist")
