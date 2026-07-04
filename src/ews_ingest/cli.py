"""Command-line interface: ``python -m ews_ingest run <source_id>``."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ews_ingest import sources as _sources  # noqa: F401 - triggers registration
from ews_ingest.config import Services, build_context, check_env, make_services
from ews_ingest.core.models import RawRecord
from ews_ingest.core.registry import all_source_ids, get_source

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


def _services_from_env() -> Services:
    landing_dir = Path(os.environ.get("EWS_LANDING_DIR", "./data/landing"))
    base = Path(__file__).resolve().parent
    return make_services(
        landing_dir=landing_dir,
        entities_path=base / "config" / "entities.yaml",
        sources_path=base / "config" / "sources.yaml",
        sec_user_agent=os.environ.get("SEC_USER_AGENT"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ews_ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list registered sources")
    sub.add_parser("validate", help="check sources.yaml + env vars")
    run = sub.add_parser("run", help="fetch + land a source")
    run.add_argument("source_id")
    args = parser.parse_args(argv)
    services = _services_from_env()
    handlers: dict[str, Handler] = {
        "list": cmd_list,
        "validate": cmd_validate,
        "run": cmd_run,
    }
    return handlers[args.cmd](args, services)
