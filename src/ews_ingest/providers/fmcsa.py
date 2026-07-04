"""FMCSA transport: bulk Safe Data files + SAFER HTML snapshot."""

from __future__ import annotations

from collections.abc import Iterator

from ews_ingest.core.http import HttpClient, RatePolicy

SAFE_DATA_BASE = "https://ai.fmcsa.dot.gov/SafeDataFiles"
SAFER_BASE = "https://safer.fmcsa.dot.gov"

__all__ = [
    "census_stream",
    "census_url",
    "li_insurance_stream",
    "mcmis_crash_stream",
    "safer_snapshot_url",
]

BULK_FILES: dict[str, str] = {
    "census_all": "CENSUS_All.csv",
    "census_property": "CENSUS_Property.csv",
    "census_passenger": "CENSUS_Passenger.csv",
    "li_insurance": "INS_All.csv",
    "mcmis_crash": "Crash_All.csv",
    "mcmis_inspection": "Inspection_All.csv",
    "new_entrant": "NewEntrant_All.csv",
    "oos_orders": "OutofService_All.csv",
}


def census_stream(http: HttpClient, policy: RatePolicy, filename: str) -> Iterator[bytes]:
    url = f"{SAFE_DATA_BASE}/{filename}"
    yield from http.stream(url, policy=policy)


def census_url(filename: str) -> str:
    return f"{SAFE_DATA_BASE}/{filename}"


def li_insurance_stream(http: HttpClient, policy: RatePolicy) -> Iterator[bytes]:
    url = f"{SAFE_DATA_BASE}/{BULK_FILES['li_insurance']}"
    yield from http.stream(url, policy=policy)


def mcmis_crash_stream(http: HttpClient, policy: RatePolicy) -> Iterator[bytes]:
    url = f"{SAFE_DATA_BASE}/{BULK_FILES['mcmis_crash']}"
    yield from http.stream(url, policy=policy)


def safer_snapshot_url(usdot: str) -> str:
    return f"{SAFER_BASE}/CompanySnapshot.aspx?dot={usdot}"
