"""BTS transport: Socrata-style data.bts.gov + TranStats bulk files. No key."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.http import HttpClient, RatePolicy

DATA_BTS = "https://data.bts.gov/resource"
TRANSTATS = "https://transtats.bts.gov"

__all__ = ["socrata", "transtats_bulk_stream", "transtats_bulk_url"]

# Socrata resource IDs (4x4) for key BTS datasets.
RESOURCES: dict[str, str] = {
    "ftsi": "b5nx-4t5r",  # Freight Transportation Services Index
    "t100_segment": "xpc5-4hui",  # T-100 segment data (placeholder id)
    "air_consumer": "upne-bx7j",  # Air Travel Consumer Report (placeholder id)
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
