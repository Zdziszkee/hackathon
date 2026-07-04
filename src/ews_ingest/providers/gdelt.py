"""GDELT v2 transport (no key)."""

from __future__ import annotations

from ews_ingest.core.http import HttpClient, RatePolicy

BASE = "https://api.gdeltproject.org/api/v2"

__all__ = ["doc_search", "timeline_tone", "timeline_volume"]

# Distress keyword set used across petrochem + transport sectors.
DISTRESS_KEYWORDS = (
    "bankruptcy",
    "layoffs",
    "default",
    "restructuring",
    "downgrade",
    "insolvency",
)


def doc_search(
    http: HttpClient,
    policy: RatePolicy,
    *,
    query: str,
    params: dict[str, str | int] | None = None,
) -> dict[str, object]:
    url = f"{BASE}/doc/doc"
    merged: dict[str, str | int] = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": 250,
        "timespan": "3d",
    }
    if params:
        merged.update(params)
    return http.get_json(url, policy=policy, params=merged)


def timeline_tone(
    http: HttpClient,
    policy: RatePolicy,
    *,
    query: str,
    timespan: str = "6months",
) -> dict[str, object]:
    url = f"{BASE}/timeline/timeline"
    params: dict[str, str | int] = {
        "timeline": "tone",
        "query": query,
        "format": "json",
        "timespan": timespan,
    }
    return http.get_json(url, policy=policy, params=params)


def timeline_volume(
    http: HttpClient,
    policy: RatePolicy,
    *,
    query: str,
    timespan: str = "6months",
) -> dict[str, object]:
    url = f"{BASE}/timeline/timeline"
    params: dict[str, str | int] = {
        "timeline": "vol",
        "query": query,
        "format": "json",
        "timespan": timespan,
    }
    return http.get_json(url, policy=policy, params=params)
