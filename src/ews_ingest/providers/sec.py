"""SEC EDGAR transport (no API key; descriptive User-Agent required)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

from ews_ingest.core.http import HttpClient, RatePolicy

DATA_BASE = "https://data.sec.gov"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
FILES_BASE = "https://www.sec.gov/files"
DERA_BASE = "https://www.sec.gov/dera/data/financial-statement-data-sets"

__all__ = [
    "company_facts",
    "concept",
    "dera_listing",
    "frames",
    "fulltext_search",
    "submissions",
    "tickers_exchange",
]


def _cik10(cik: str) -> str:
    return cik.lstrip("0").zfill(10)


def company_facts(http: HttpClient, policy: RatePolicy, cik: str) -> dict[str, object]:
    url = f"{DATA_BASE}/api/xbrl/companyfacts/CIK{_cik10(cik)}.json"
    return http.get_json(url, policy=policy)


def submissions(http: HttpClient, policy: RatePolicy, cik: str) -> dict[str, object]:
    url = f"{SUBMISSIONS_BASE}/CIK{_cik10(cik)}.json"
    return http.get_json(url, policy=policy)


def concept(
    http: HttpClient,
    policy: RatePolicy,
    *,
    cik: str,
    concept_path: str,
    params: dict[str, str | int] | None = None,
) -> dict[str, object]:
    """``concept_path`` is ``"<taxonomy>/<tag>"`` e.g. ``"us-gaap/Assets"``."""
    url = f"{DATA_BASE}/api/xbrl/companyconcept/CIK{_cik10(cik)}/{concept_path}.json"
    return http.get_json(url, policy=policy, params=params)


def frames(
    http: HttpClient,
    policy: RatePolicy,
    tax: str,
    tag: str,
    frame: str,
) -> dict[str, object]:
    url = f"{DATA_BASE}/api/xbrl/frames/{tax}/{tag}/{frame}.json"
    return http.get_json(url, policy=policy)


def fulltext_search(
    http: HttpClient,
    policy: RatePolicy,
    *,
    q: str,
    forms: list[str] | None = None,
    date_range: str | None = None,
) -> dict[str, object]:
    url = f"{EFTS_BASE}"
    params: dict[str, str | int] = {"q": q}
    if forms:
        params["forms"] = ",".join(forms)
    if date_range:
        params["dateRange"] = date_range
    return http.get_json(url, policy=policy, params=params)


def tickers_exchange(http: HttpClient, policy: RatePolicy) -> list[dict[str, object]]:
    url = f"{FILES_BASE}/company_tickers_exchange.json"
    data = http.get_json(url, policy=policy)
    if isinstance(data, list):
        return cast("list[dict[str, object]]", [r for r in data if isinstance(r, dict)])
    # Legacy response shape: ``{"results": [{"cik":..., "ticker":..., "name":...}, ...]}``
    body = data.get("results") if isinstance(data, dict) else None
    if isinstance(body, list):
        return cast("list[dict[str, object]]", [r for r in body if isinstance(r, dict)])
    # New (2025) response shape: ``{"fields": ["cik","name","ticker","exchange"],
    # "data": [[cik, name, ticker, exchange], ...]}`` — convert to dicts so
    # downstream connectors' ``entry.get("cik")`` etc. keep working.
    fields = data.get("fields") if isinstance(data, dict) else None
    rows = data.get("data") if isinstance(data, dict) else None
    if isinstance(fields, list) and isinstance(rows, list):
        out: list[dict[str, object]] = []
        for row in rows:
            if isinstance(row, list) and len(row) == len(fields):
                out.append({str(f): v for f, v in zip(fields, row, strict=True)})
        return out
    return []


def dera_listing(http: HttpClient, policy: RatePolicy, filename: str) -> Iterator[bytes]:
    url = f"{DERA_BASE}/{filename}"
    yield from http.stream(url, policy=policy)
