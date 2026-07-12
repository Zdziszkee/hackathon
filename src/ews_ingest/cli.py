"""Command-line interface: ``python -m ews_ingest run <source_id>``."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ews_ingest import sources as _sources  # noqa: F401 - triggers registration
from ews_ingest.config import Services, build_context, check_env, make_services
from ews_ingest.core.http import HttpClient
from ews_ingest.core.models import RawRecord
from ews_ingest.core.registry import all_source_ids, get_source
from ews_ingest.dashboard.company_store import (
    CompanyStore,
    TickerResolutionError,
)
from ews_ingest.dashboard.db import HistoricalStore
from ews_ingest.dashboard.onboarding import PortfolioOnboarding

BATCH = 500

Handler = Callable[[argparse.Namespace, Services], int]


def _backfill_since(label: str) -> date | None:
    today = datetime.now(UTC).date()
    if label == "full":
        return None
    if label.endswith("y"):
        return today - timedelta(days=365 * int(label[:-1]))
    if label.endswith("mo"):
        return today - timedelta(days=30 * int(label[:-2]))
    return None


def cmd_list(_args: argparse.Namespace, services: Services) -> int:
    for sid in all_source_ids():
        cfg = services.sources.get(sid)
        mark = "x" if cfg and cfg.enabled else " "
        print(f"[{mark}] {sid}")
    return 0


def cmd_validate(_args: argparse.Namespace, services: Services) -> int:
    ok = True
    for sid in all_source_ids():
        cfg = services.sources.get(sid)
        if not cfg:
            print(f"! {sid}: not in sources.yaml")
            ok = False
            continue
        missing = check_env(cfg)
        if missing:
            print(f"! {sid}: missing env {missing}")
            ok = False
        else:
            print(f"ok {sid}")
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace, services: Services) -> int:
    sid = args.source_id
    cfg = services.sources.get(sid)
    if cfg is None:
        print(f"unknown source: {sid}", file=sys.stderr)
        return 2
    missing = check_env(cfg)
    if missing:
        print(f"missing env for {sid}: {missing}", file=sys.stderr)
        return 2
    since = _backfill_since(cfg.backfill)
    run_id = uuid.uuid4().hex[:12]
    ctx = build_context(services, sid, run_id, since)
    source = get_source(sid)
    batch: list[RawRecord] = []
    count = 0
    for rec in source.fetch(ctx):
        batch.append(rec)
        if len(batch) >= BATCH:
            count += services.writer.write(batch)
            batch.clear()
    if batch:
        count += services.writer.write(batch)
    services.logger.info("run complete: source=%s written=%d", sid, count)
    print(f"{sid}: wrote {count} records (run {run_id})")
    return 0


def cmd_onboard(args: argparse.Namespace, services: Services) -> int:
    """Resolve a ticker + run every eligible per-entity source for it.

    With ``--async`` the fetch is scheduled on the running event loop and
    the CLI returns immediately; the task continues in the background.
    Without ``--async`` the call blocks until every eligible source has
    landed (or failed). Exit codes:

    * 0 — task ran (status reported via stdout)
    * 1 — ticker could not be resolved / unknown sector
    * 2 — invalid arguments
    """
    ticker = args.ticker.strip().upper()
    if not ticker:
        print("ticker must not be empty", file=sys.stderr)
        return 2

    db_path = Path(os.environ.get("EWS_DB_PATH", "./data/ews.db"))
    http = HttpClient(sec_user_agent=os.environ.get("SEC_USER_AGENT"))
    store = CompanyStore(db_path, http=http)
    try:
        identifier = store.add_ticker(ticker)
    except TickerResolutionError as exc:
        print(f"could not resolve {ticker!r}: {exc}", file=sys.stderr)
        return 1

    onboarding = PortfolioOnboarding(services, http=http)

    if args.async_run:
        loop = asyncio.new_event_loop()

        def _runner() -> None:
            asyncio.set_event_loop(loop)
            task = loop.run_until_complete(onboarding.refresh_async(identifier))
            print(
                f"{ticker}: scheduled in background — {task.sources_total} sources "
                f"queued (run {task.task_id})."
            )

        threading.Thread(target=_runner, daemon=True).start()
        return 0

    task = onboarding.refresh_blocking(identifier)
    if task.status == "failed":
        print(
            f"{ticker}: onboarding failed ({task.error or 'no sources succeeded'}); "
            f"{task.sources_done} ok, {task.sources_failed} failed, "
            f"{task.sources_written} records written in {task.elapsed_seconds():.1f}s",
            file=sys.stderr,
        )
        return 1
    print(
        f"{ticker}: onboarding {task.status} — {task.sources_done}/{task.sources_total} "
        f"sources ok, {task.sources_written} records written in "
        f"{task.elapsed_seconds():.1f}s"
    )
    return 0


def _services_from_env() -> Services:
    landing_dir = Path(os.environ.get("EWS_LANDING_DIR", "./data/landing"))
    base = Path(__file__).resolve().parent
    db_path = Path(os.environ.get("EWS_DB_PATH", "./data/ews.db"))
    # Companies are stored in the SQLite DB.
    hist = HistoricalStore(db_path)
    entities = hist.list_companies()
    return make_services(
        landing_dir=landing_dir,
        entities_path=base / "config" / "entities.yaml",
        sources_path=base / "config" / "sources.yaml",
        sec_user_agent=os.environ.get("SEC_USER_AGENT"),
        entities=entities or None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ews_ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list registered sources")
    sub.add_parser("validate", help="check sources.yaml + env vars")
    run = sub.add_parser("run", help="fetch + land a source")
    run.add_argument("source_id")
    onboard = sub.add_parser(
        "onboard",
        help="resolve a ticker + run every eligible per-entity source",
    )
    onboard.add_argument("ticker")
    onboard.add_argument(
        "--async",
        dest="async_run",
        action="store_true",
        help="fire-and-forget: schedule the fetch in a background thread.",
    )
    args = parser.parse_args(argv)
    services = _services_from_env()
    handlers: dict[str, Handler] = {
        "list": cmd_list,
        "validate": cmd_validate,
        "run": cmd_run,
        "onboard": cmd_onboard,
    }
    return handlers[args.cmd](args, services)
