"""EIA transport (free API key: EIA_API_KEY)."""

from __future__ import annotations

from ews_ingest.core.http import HttpClient, RatePolicy

BASE = "https://api.eia.gov/v2"

__all__ = ["data", "route_metadata"]

# Route paths for high-value petroleum series.
ROUTES: dict[str, list[str]] = {
    "wti_spot": ["petroleum", "pri", "spt", "data"],
    "brent_spot": ["petroleum", "pri", "spt", "data"],
    "ulsd_diesel": ["petroleum", "pri", "spt", "data"],
    "jet_fuel": ["petroleum", "pri", "spt", "data"],
    "henry_hub_gas": ["natural-gas", "pri", "sum", "data"],
    "refinery_utilization": ["petroleum", "sum", "snd", "data"],
}


def data(
    http: HttpClient,
    policy: RatePolicy,
    *,
    api_key: str,
    route: list[str],
    params: dict[str, str | int] | None = None,
) -> dict[str, object]:
    url = f"{BASE}/{'/'.join(route)}/data/"
    merged: dict[str, str | int] = {
        "api_key": api_key,
        "frequency": "daily",
        "data[0]": "value",
    }
    if params:
        merged.update(params)
    return http.get_json(url, policy=policy, params=merged)


def route_metadata(
    http: HttpClient,
    policy: RatePolicy,
    *,
    api_key: str,
    route: list[str],
) -> dict[str, object]:
    url = f"{BASE}/{'/'.join(route)}/"
    params: dict[str, str | int] = {"api_key": api_key}
    return http.get_json(url, policy=policy, params=params)
