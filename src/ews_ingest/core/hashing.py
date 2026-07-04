"""Stable content hashing for landing-zone idempotency."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def content_hash(payload: Mapping[str, object]) -> str:
    """Return a SHA-256 hex digest of a payload, independent of key order."""
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
