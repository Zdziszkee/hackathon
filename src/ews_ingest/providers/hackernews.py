"""Hacker News (Algolia Search API) transport — free, no key."""

from __future__ import annotations

import time
from typing import Any

from ews_ingest.core.http import HttpClient, RatePolicy

BASE = "https://hn.algolia.com/api/v1"

__all__ = ["search"]


def search(
    http: HttpClient,
    policy: RatePolicy,
    *,
    query: str,
    hits_per_page: int = 50,
    days_back: int = 365,
) -> dict[str, Any]:
    """Search HN stories by query, restricted to the last ``days_back`` days.

    Returns the raw Algolia response (dict with ``hits`` list).
    """
    cutoff_ts = int(time.time()) - days_back * 86400
    url = f"{BASE}/search"
    params: dict[str, str | int] = {
        "query": query,
        "hitsPerPage": hits_per_page,
        "numericFilters": f"created_at_i>{cutoff_ts}",
    }
    return http.get_json(url, policy=policy, params=params)
