"""Runtime data models shared across the ingestion layer."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Identifiers",
    "RawFormat",
    "RawRecord",
    "SourceType",
]


class SourceType(StrEnum):
    """How a source is accessed on the wire."""

    API = "api"
    BULK_FILE = "bulk_file"
    RSS = "rss"
    SCRAPE = "scrape"


class RawFormat(StrEnum):
    """On-disk representation of a fetched payload."""

    JSON = "json"
    CSV = "csv"
    HTML = "html"
    XML = "xml"
    PDF = "pdf"
    TEXT = "text"
    WARC = "warc"


class Identifiers(BaseModel):
    """Cross-source entity keys carried on every record for later joins.

    Sector / industry are free-form strings stored under ``extra_ids`` and
    populated dynamically (e.g. by :mod:`ews_ingest.dashboard.yahoo_sector`
    at add time). No central vocabulary — see the architecture notes.
    """

    model_config = ConfigDict(extra="ignore")

    cik: str | None = None
    ticker: str | None = None
    usdot: str | None = None
    epa_frs_id: str | None = None
    name: str | None = None
    extra_ids: dict[str, str] = Field(default_factory=dict)


class RawRecord(BaseModel):
    """A single normalized raw observation written to the landing zone."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_type: SourceType
    fetched_at: datetime
    fetch_run_id: str
    payload: dict[str, object]
    raw_format: RawFormat
    content_hash: str
    entities: list[Identifiers] = Field(default_factory=list)
    url: str | None = None
    extra: dict[str, object] = Field(default_factory=dict)


def utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(UTC)
