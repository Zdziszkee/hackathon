"""BTS transport: Socrata-style data.bts.gov + TranStats bulk files. No key."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.http import HttpClient, RatePolicy

DATA_BTS = "https://data.transportation.gov/resource"
TRANSTATS = "https://transtats.bts.gov"

__all__ = ["socrata", "transtats_bulk_stream", "transtats_bulk_url"]

# Socrata 4x4 resource IDs on data.transportation.gov (migrated from data.bts.gov).
RESOURCES: dict[str, str] = {
    "ftsi": "bw6n-ddqk",  # Transportation Services Index & Seasonally-Adjusted Data
    "t100_segment": "xpc5-4hui",  # T-100 segment data (placeholder id)
    "air_consumer": "upne-bx7j",  # Air Travel Consumer Report (legacy id; verify)
}


def socrata(
    http: HttpClient,
    policy: RatePolicy,
    *,
    resource_id: str,
    params: dict[str, str | int] | None = None,
) -> list[object]:
    url = f"{DATA_BTS}/{resource_id}.json"
    return http.get_json_list(url, policy=policy, params=params)


def transtats_bulk_url(filename: str) -> str:
    return f"{TRANSTATS}/PRELIMINARY_DOWNLOAD/{filename}"


def transtats_bulk_stream(http: HttpClient, policy: RatePolicy, filename: str) -> Iterator[bytes]:
    yield from http.stream(transtats_bulk_url(filename), policy=policy)
