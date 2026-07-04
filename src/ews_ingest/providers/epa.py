"""EPA transport: ECHO (enforcement), TRI (releases), FRS (facility IDs). No key."""

from __future__ import annotations

from ews_ingest.core.http import HttpClient, RatePolicy

ECHO_REST = "https://ofmpub.epa.gov/echo/echo_rest_services"
TRI_EFSERVICE = "https://enviro.epa.gov/enviro/efservice"
FRS_QUERY = "https://frsquery.epa.gov"

__all__ = ["echo_rest", "frs_facility", "tri_table"]

NAICS_325 = "325"
NAICS_484 = "484"


def echo_rest(
    http: HttpClient,
    policy: RatePolicy,
    *,
    service: str,
    params: dict[str, str | int],
) -> dict[str, object]:
    url = f"{ECHO_REST}.{service}"
    merged: dict[str, str | int] = dict(params)
    merged.setdefault("output", "JSON")
    return http.get_json(url, policy=policy, params=merged)


def tri_table(
    http: HttpClient,
    policy: RatePolicy,
    *,
    table: str,
    params: dict[str, str | int] | None = None,
) -> list[object]:
    url = f"{TRI_EFSERVICE}/{table}/JSON"
    return http.get_json_list(url, policy=policy, params=params)


def frs_facility(http: HttpClient, policy: RatePolicy, *, registry_id: str) -> dict[str, object]:
    url = f"{FRS_QUERY}/frs_rest_services.get_facility"
    params: dict[str, str | int] = {"p_regis_id": registry_id, "output": "JSON"}
    return http.get_json(url, policy=policy, params=params)
