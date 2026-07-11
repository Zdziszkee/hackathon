"""SQLite-backed store for historical records and last update tracking.

The dashboard uses this as the source of truth for metrics/indicators.
Ingestion (datasources) feed it independently.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

__all__ = ["HistoricalStore", "make_historical_store"]


class HistoricalStore:
    """Simple SQLite store for time-series records from sources.

    Records are stored with ticker for per-company queries.
    Supports idempotency via content_hash.
    """

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False so the (cached) connection can be used
        # from Streamlit's script execution threads (different from import time).
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                ticker TEXT,
                fetched_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                run_id TEXT,
                UNIQUE(source_id, content_hash)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ticker_src_time "
            "ON records (ticker, source_id, fetched_at)"
        )
        self._conn.commit()

    def write_records(
        self, source_id: str, ticker: str | None, records: list[dict[str, Any]]
    ) -> int:
        """Insert new records, skip duplicates by hash. Return count written."""
        if not records:
            return 0
        written = 0
        for rec in records:
            try:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO records
                    (source_id, ticker, fetched_at, payload, content_hash, run_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        ticker,
                        rec.get("fetched_at"),
                        json.dumps(rec.get("payload", {})),
                        rec.get("content_hash"),
                        rec.get("run_id"),
                    ),
                )
                if self._conn.total_changes > 0:
                    written += 1
            except Exception:  # noqa: S112
                continue  # ignore bad record
        self._conn.commit()
        return written

    def get_last_update(self, ticker: str, source_id: str | None = None) -> str | None:
        """Return ISO timestamp of latest record for ticker (optionally filtered by source)."""
        if source_id:
            row = self._conn.execute(
                "SELECT max(fetched_at) FROM records WHERE ticker = ? AND source_id = ?",
                (ticker, source_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT max(fetched_at) FROM records WHERE ticker = ?", (ticker,)
            ).fetchone()
        return row[0] if row and row[0] else None

    def get_historical(
        self, ticker: str, source_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return recent records for ticker."""
        if source_id:
            rows = self._conn.execute(
                """
                SELECT fetched_at, payload, source_id FROM records
                WHERE ticker = ? AND source_id = ?
                ORDER BY fetched_at DESC LIMIT ?
                """,
                (ticker, source_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT fetched_at, payload, source_id FROM records
                WHERE ticker = ?
                ORDER BY fetched_at DESC LIMIT ?
                """,
                (ticker, limit),
            ).fetchall()
        return [
            {
                "fetched_at": r["fetched_at"],
                "payload": json.loads(r["payload"]),
                "source_id": r["source_id"],
            }
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()


def make_historical_store(db_path: Path | None = None) -> HistoricalStore:
    if db_path is None:
        db_path = Path("data/ews.db")
    return HistoricalStore(db_path)
