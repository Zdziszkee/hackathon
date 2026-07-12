"""SQLite-backed store for historical records and last update tracking.

The dashboard uses this as the source of truth for metrics/indicators.
Ingestion (datasources) feed it independently.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ews_ingest.core.models import Identifiers

logger = logging.getLogger(__name__)

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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                ticker TEXT PRIMARY KEY,
                cik TEXT,
                name TEXT,
                extra_ids TEXT NOT NULL DEFAULT '{}',
                added_at TEXT
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS universe_tickers (
                ticker TEXT PRIMARY KEY,
                cik TEXT,
                name TEXT,
                fetched_at TEXT
            )
            """
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

        # Mirror universe tickers into dedicated table for SQL resolution
        if source_id == "universe.sec_company_tickers":
            for rec in records:
                p = rec.get("payload") or {}
                tk = str(p.get("ticker") or "").upper()
                if tk:
                    with contextlib.suppress(Exception):
                        self.upsert_universe_ticker(
                            tk,
                            str(p.get("cik")) if p.get("cik") is not None else None,
                            p.get("name"),
                            rec.get("fetched_at"),
                        )
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
        ts = row[0] if row and row[0] else None
        logger.debug("get_last_update ticker=%s source=%s -> %s", ticker, source_id, ts)
        return ts

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

    # ------------------------------------------------------------------
    # Companies (portfolio) stored in the same DB for stack simplification
    # ------------------------------------------------------------------

    def list_companies(self) -> list[Identifiers]:
        """Return all companies from the DB as Identifiers."""
        rows = self._conn.execute(
            "SELECT ticker, cik, name, extra_ids FROM companies ORDER BY ticker"
        ).fetchall()
        out: list[Identifiers] = []
        for r in rows:
            extra = json.loads(r["extra_ids"] or "{}")
            out.append(
                Identifiers(
                    ticker=r["ticker"],
                    cik=r["cik"] or None,
                    name=r["name"] or None,
                    extra_ids=extra,
                )
            )
        return out

    def upsert_company(self, identifier: Identifiers) -> None:
        """Insert or replace a company (used by CompanyStore on add)."""
        added_at = datetime.now(UTC).isoformat()
        extra = json.dumps(identifier.extra_ids or {})
        self._conn.execute(
            """
            INSERT OR REPLACE INTO companies (ticker, cik, name, extra_ids, added_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (identifier.ticker or "").upper(),
                identifier.cik,
                identifier.name,
                extra,
                added_at,
            ),
        )
        self._conn.commit()

    def remove_company(self, ticker: str) -> bool:
        """Remove company by ticker. Returns True if removed."""
        t = (ticker or "").upper()
        cur = self._conn.execute("DELETE FROM companies WHERE ticker = ?", (t,))
        self._conn.commit()
        return cur.rowcount > 0

    def get_company(self, ticker: str) -> Identifiers | None:
        """Fetch one company if present."""
        t = (ticker or "").upper()
        row = self._conn.execute(
            "SELECT ticker, cik, name, extra_ids FROM companies WHERE ticker = ?",
            (t,),
        ).fetchone()
        if not row:
            return None
        extra = json.loads(row["extra_ids"] or "{}")
        return Identifiers(
            ticker=row["ticker"],
            cik=row["cik"] or None,
            name=row["name"] or None,
            extra_ids=extra,
        )

    # ------------------------------------------------------------------
    # Universe tickers (master CIK/ticker list from sec_company_tickers)
    # ------------------------------------------------------------------

    def upsert_universe_ticker(
        self, ticker: str, cik: str | None, name: str | None, fetched_at: str | None = None
    ) -> None:
        """Insert or replace a universe ticker entry."""
        t = (ticker or "").upper()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO universe_tickers (ticker, cik, name, fetched_at)
            VALUES (?, ?, ?, ?)
            """,
            (t, cik, name, fetched_at),
        )
        self._conn.commit()

    def get_universe_ticker(self, ticker: str) -> dict[str, Any] | None:
        """Return universe entry for ticker if present."""
        t = (ticker or "").upper()
        row = self._conn.execute(
            "SELECT ticker, cik, name FROM universe_tickers WHERE ticker = ?",
            (t,),
        ).fetchone()
        if not row:
            return None
        return {
            "ticker": row["ticker"],
            "cik": row["cik"],
            "name": row["name"],
        }

    def list_universe_tickers(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT ticker, cik, name FROM universe_tickers ORDER BY ticker"
        ).fetchall()
        return [{"ticker": r["ticker"], "cik": r["cik"], "name": r["name"]} for r in rows]

    def close(self) -> None:
        self._conn.close()


def make_historical_store(db_path: Path | None = None) -> HistoricalStore:
    if db_path is None:
        db_path = Path("data/ews.db")
    return HistoricalStore(db_path)
