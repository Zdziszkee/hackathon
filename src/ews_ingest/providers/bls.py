"""BLS transport (free API key: BLS_API_KEY). v2 public API, GET per-series."""

from __future__ import annotations

from ews_ingest.core.http import HttpClient, RatePolicy

BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data"

__all__ = ["series_data", "series_data_bulk"]

# High-value BLS series for the named sectors.
PPI_SERIES = {
    "petrochem_325110": "PCU325110325110",
    "general_freight_484121": "PCU484121484121",
}
CPI_SERIES = {
    "motor_fuel": "CUSR0000SETB01",
    "transport_services": "CUSR0000SETG",
}
CES_SERIES = {
    "chemical_mfg": "CES313251110001",
    "trucking": "CES434840000001",
}


def series_data(
    http: HttpClient,
    policy: RatePolicy,
    *,
    series_id: str,
    start_year: str | None = None,
    end_year: str | None = None,
) -> dict[str, object]:
    url = f"{BASE}/{series_id}"
    params: dict[str, str | int] = {}
    if start_year:
        params["startyear"] = start_year
    if end_year:
        params["endyear"] = end_year
    return http.get_json(url, policy=policy, params=params or None)


def series_data_bulk(
    http: HttpClient,
    policy: RatePolicy,
    *,
    series_ids: list[str],
    start_year: str | None = None,
    end_year: str | None = None,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for sid in series_ids:
        out.append(
            series_data(http, policy, series_id=sid, start_year=start_year, end_year=end_year)
        )
    return out
