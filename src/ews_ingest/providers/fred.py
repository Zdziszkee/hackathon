"""FRED transport (free API key: FRED_API_KEY)."""

from __future__ import annotations

from ews_ingest.core.http import HttpClient, RatePolicy

BASE = "https://api.stlouisfed.org/fred"

__all__ = ["series_info", "series_observations"]

CREDIT_SPREADS = ("BAMLH0A0HYM2", "BAMLC0A4CBBB", "AAA", "BAA")
CASS_FREIGHT = ("FRGSHPUSM649NCIS", "FRGEXPUSM649NCIS")


def series_observations(
    http: HttpClient,
    policy: RatePolicy,
    *,
    series_id: str,
    api_key: str,
    params: dict[str, str | int] | None = None,
) -> dict[str, object]:
    url = f"{BASE}/series/observations"
    merged: dict[str, str | int] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    if params:
        merged.update(params)
    return http.get_json(url, policy=policy, params=merged)


def series_info(
    http: HttpClient,
    policy: RatePolicy,
    *,
    series_id: str,
    api_key: str,
) -> dict[str, object]:
    url = f"{BASE}/series"
    params: dict[str, str | int] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    return http.get_json(url, policy=policy, params=params)
