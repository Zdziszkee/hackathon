"""Record builder helper to reduce connector boilerplate."""

from __future__ import annotations

from dataclasses import dataclass, field

from ews_ingest.core.context import FetchContext
from ews_ingest.core.hashing import content_hash
from ews_ingest.core.models import Identifiers, RawFormat, RawRecord, SourceType, utc_now

__all__ = ["RecordInput", "build_record"]


@dataclass
class RecordInput:
    """Inputs needed to mint a :class:`RawRecord` from a fetched payload."""

    payload: dict[str, object]
    raw_format: RawFormat
    entities: list[Identifiers] = field(default_factory=list)
    url: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


def build_record(
    ctx: FetchContext,
    source_id: str,
    source_type: SourceType,
    spec: RecordInput,
) -> RawRecord:
    """Construct a timestamped, hashed :class:`RawRecord` from ``spec``."""
    return RawRecord(
        source=source_id,
        source_type=source_type,
        fetched_at=utc_now(),
        fetch_run_id=ctx.run_id,
        payload=spec.payload,
        raw_format=spec.raw_format,
        content_hash=content_hash(spec.payload),
        entities=list(spec.entities),
        url=spec.url,
        extra=dict(spec.extra),
    )
