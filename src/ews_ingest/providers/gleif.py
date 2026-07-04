"""GLEIF transport (no key): Level 1 (who-is-who) + Level 2 (who-owns-whom)."""

from __future__ import annotations

from ews_ingest.core.http import HttpClient, RatePolicy

BASE = "https://api.gleif.org/api/v1"

__all__ = ["lei_record", "lei_records_page", "rr_records_for_lei", "rr_records_page"]


def lei_record(http: HttpClient, policy: RatePolicy, lei: str) -> dict[str, object]:
    url = f"{BASE}/lei-records/{lei}"
    return http.get_json(url, policy=policy)


def lei_records_page(
    http: HttpClient,
    policy: RatePolicy,
    *,
    page_size: int = 100,
    page_number: int = 1,
    legal_name: str | None = None,
) -> dict[str, object]:
    url = f"{BASE}/lei-records"
    params: dict[str, str | int] = {"page[size]": page_size, "page[number]": page_number}
    if legal_name:
        params["filter[entity.legalName]"] = legal_name
    return http.get_json(url, policy=policy, params=params)


def rr_records_page(
    http: HttpClient,
    policy: RatePolicy,
    *,
    page_size: int = 100,
    page_number: int = 1,
) -> dict[str, object]:
    url = f"{BASE}/rr-records"
    params: dict[str, str | int] = {"page[size]": page_size, "page[number]": page_number}
    return http.get_json(url, policy=policy, params=params)


def rr_records_for_lei(
    http: HttpClient,
    policy: RatePolicy,
    lei: str,
) -> dict[str, object]:
    url = f"{BASE}/rr-records"
    params: dict[str, str | int] = {"filter[relationship.startingNode.id]": lei}
    return http.get_json(url, policy=policy, params=params)
