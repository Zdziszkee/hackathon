"""EPA transport: Envirofacts DMAP REST (TRI/FRS) + ECHO. No key.

Envirofacts migrated from ``enviro.epa.gov/enviro/efservice`` to the DMAP REST
data service at ``data.epa.gov/dmapservice``. Tables are addressed as
``{program}.{table}`` (e.g. ``tri.tri_facility``); filters are path segments.
"""

from __future__ import annotations

from ews_ingest.core.http import HttpClient, RatePolicy

ECHO_REST = "https://ofmpub.epa.gov/echo/echo_rest_services"  # legacy; retired
DMAP = "https://data.epa.gov/dmapservice"
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
    """Fetch rows from a TRI DMAP table (paged manifest-style).

    ``table`` is the DMAP table path e.g. ``tri.tri_facility``. ``params`` may
    carry ``rows_first``/``rows_last`` for paging (defaults 1:100).
    """
    first = int(params.get("rows_first", 1)) if params else 1
    last = int(params.get("rows_last", 100)) if params else 100
    url = f"{DMAP}/{table}/{first}:{last}/JSON"
    return http.get_json_list(url, policy=policy)


def frs_facility(http: HttpClient, policy: RatePolicy, *, registry_id: str) -> dict[str, object]:
    url = f"{FRS_QUERY}/frs_rest_services.get_facility"
    params: dict[str, str | int] = {"p_regis_id": registry_id, "output": "JSON"}
    return http.get_json(url, policy=policy, params=params)
