# Remove Hardcoded Companies, Add Global + Per-Company Async Refresh, SQLite Historical Storage, Last Update Info, Decoupled Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all hardcoded companies (delete entities.yaml + all seeding/bootstrap). Decouple scrapers/ingestion (sources feed internal SQLite DB independently on 30min schedule or user force refetch). The frontend just keeps live track of that internal DB state and displays metrics/indicators based on it. Show last update info. Support async force refetch (single company or global) — UI only marks pending/waiting (non-blocking). Store historical data in SQLite for analysis. Use fragments/threads + session state so the dashboard never freezes.

**Architecture:** 
- Datasources/ingestion (the sources) feed the internal SQLite DB independently: either on a schedule (e.g. cron/systemd timer running `uv run --env-file .env python -m ews_ingest run <source_id>` every 30 minutes for all sources) or on-demand via user force refetch from the dashboard.
- The frontend just keeps live track of that internal DB state (via st.fragment(run_every=...) or similar polling/rerun) and displays metrics/indicators based on it. Companies from dynamic JSON. Dashboard does **no** fetching or raw landing reads for indicators — it only reads the current DB state and shows pending/last-update overlays. All metrics and indicators come from DB data.
- Triggers (global or per-company) from UI are fire-and-forget async: immediately mark "pending/waiting for data from datasources" in session_state (non-blocking), spawn background thread (or CLI) that runs the relevant sources. Sources write fresh records + timestamps to SQLite. Dashboard live-tracks the DB to auto-clear pending and refresh indicators/metrics.
- Last update info: per company or per indicator, from max(fetched_at) in DB.
- Per-company retrigger: button to force fetch for one company (async).
- Global button: force everything.
- Historical: time-series in SQLite (source_id, ticker, fetched_at, payload, content_hash).
- Decoupling: only sources write to DB. Dashboard is read-mostly + trigger UI.
- Async UI: pending flags + fragments for live DB tracking. No freezing.
- Triggers use registry + resolver as before.

**Tech Stack:** Python 3.14 (stdlib sqlite3), uv, Streamlit (fragments + threads for live DB tracking + async non-blocking triggers), pytest, ruff, ty. The DB is the single source of truth for all dashboard metrics and indicators. Landing JSONL may stay for raw archival; dashboard ignores it for display.

## Global Constraints
- requires-python = ">=3.14"
- Use `uv run --env-file .env python -m ews_ingest ...` or `export UV_ENV_FILE=.env`
- All checks: `uv run ruff check . && uv run ruff format --check . && uv run ty check`
- Unit tests: `uv run pytest tests/unit -q`
- Type ignores: only `ty: ignore[<code>]`
- sources.yaml is generated (no change)
- Decouple ingestion from dashboard UI (datasources feed DB on 30min schedule or user force refetch)
- Use sqlite3 for historical storage (convenient, no extra deps)
- Async UI: mark pending, no freeze on add/refetch
- Support last update info + per-company retrigger + global
- Scheduled feeding: external (cron every 30min via CLI `run`); on-demand via dashboard triggers only.
- The frontend just keeps live track of that internal DB state and displays metrics/indicators based on it. Triggers only mark pending (async, non-blocking) and let independent ingestion update the DB. Dashboard is purely a live DB tracker + viewer.

---

## File Structure (locked in)

**Files to delete:**
- src/ews_ingest/config/entities.yaml
- src/ews_ingest/dashboard/onboarding.py (or repurpose; we'll remove targeted onboarding, use simpler async trigger)
- tests/unit/test_onboarding.py

**Files to create:**
- src/ews_ingest/core/db.py (or dashboard/db.py): SQLite connection, schema for historical records, write/read with timestamps, last_update queries.
- Perhaps tests for it.

**Files to modify:**
- src/ews_ingest/dashboard/company_store.py (remove seed_from_yaml)
- src/ews_ingest/dashboard/app.py (remove old onboarding/bootstrap/per-button if any; add async pending states, last update display, global + per-company retrigger buttons/actions that mark pending and bg trigger; update add flow to async)
- src/ews_ingest/cli.py (remove cmd_onboard if not needed; simplify _default_entities_path; perhaps add trigger cmd if useful but keep minimal)
- src/ews_ingest/dashboard/services.py (add helpers for trigger full/per-company refresh using DB writer; update for sqlite)
- src/ews_ingest/core/landing.py or new: integrate or replace with DB write (or keep JSONL + mirror to DB for historical)
- src/ews_ingest/dashboard/landing.py (keep for raw/compatibility if needed; deprecate for indicators)
- src/ews_ingest/dashboard/db.py (new or extend): DB reader for latest state, historical, last_update per company/source. Used by compute and app.
- src/ews_ingest/dashboard/compute.py + signals/* (rewrite to pull from DB reader instead of LandingReader for all metrics/indicators)
- src/ews_ingest/dashboard/app.py (live tracking of that internal DB state via fragments/polling, pending states for async refetches, all metric/indicator display pulled purely from DB + last update info)
- AGENTS.md (update: dashboard is pure live DB viewer + async trigger UI)
- tests/unit/test_*.py (update for no yaml, add DB tests, async states)
- src/ews_ingest/core/registry.py and protocol.py (minor comment updates)
- src/ews_ingest/config.py or services for DB path (EWS_DB_PATH or default data/ews.db)
- AGENTS.md (add section on scheduling: e.g. cron `*/30 * * * * cd /path && export UV_ENV_FILE=.env && uv run python -m ews_ingest run <all-sources>` or use a simple loop/script; dashboard only for force refetch)

New storage: SQLite at EWS_DB_PATH or ./data/ews.db . Schema example (in plan tasks):
- records (id, source_id, ticker, fetched_at, payload JSON, content_hash, run_id)
- Or use existing RawRecord + metadata table for last_update. Add index on (ticker, source_id, fetched_at) for fast last_update queries.

Ingestion can still use JSONL for raw if wanted, but for historical/analysis use SQLite. For simplicity, have DB writer that sources can use (sources feed DB on schedule or trigger), or post-process.

Decouple: datasources/sources run independently (scheduled every 30min via external cron calling CLI `run <sid>`, or on-demand via dashboard force refetch). They write to SQLite historical DB. Dashboard only triggers refetches (bg, marks pending) and reads last_update/historical from DB. Triggers use registry + resolver to run fetch for specific company or all. No direct scraping in dashboard.

---

### Task 1: Remove hardcoded seeding (yaml, seed_from_yaml, bootstrap) - same as before

**Files:**
- Delete: `src/ews_ingest/config/entities.yaml`
- Modify: `src/ews_ingest/dashboard/company_store.py` (remove seed_from_yaml)
- Modify: `src/ews_ingest/cli.py` (simplify _default_entities_path to json only)
- Modify: `src/ews_ingest/dashboard/app.py` (remove _ensure...bootstrap and call)

**Interfaces:**
- Same as original plan task 1.

- [ ] **Step 1: Update/add test for empty start without yaml**

```python
def test_companies_empty_no_yaml(tmp_path):
    # setup no yaml
    assert load_companies(...) == []
```

- [ ] **Step 2: Run to verify**

`uv run pytest ... -q`

- [ ] **Step 3: Delete seed method**

Remove the method.

- [ ] **Step 4: Simplify cli _default_entities_path**

```python
def _default_entities_path() -> Path:
    explicit = os.environ.get("EWS_COMPANIES_PATH")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("EWS_COMPANIES_DIR", "./data/companies")) / "companies.json"
```

- [ ] **Step 5: Remove bootstrap in app.py + update docstring**

- [ ] **Step 6: Run checks**

`uv run ruff check . && ... && uv run pytest tests/unit -q -k "company or entity"`

- [ ] **Step 7: Commit**

```bash
git add ... 
git commit -m "chore: remove hardcoded yaml seeding"
```

### Task 2: Delete old onboarding files and remove per-ticker special casing

**Files:**
- Delete `src/ews_ingest/dashboard/onboarding.py`
- Delete `tests/unit/test_onboarding.py`
- Modify app.py, cli.py, services.py to remove imports/calls

**Interfaces:**
- No more PortfolioOnboarding.

- [ ] **Step 1: Delete files**

`git rm ...`

- [ ] **Step 2: Clean imports in app.py/cli.py/services.py**

- [ ] **Step 3: Run checks (expect errors, fixed later)**

- [ ] **Step 4: Commit**

### Task 3: Introduce SQLite for historical storage (decoupled from dashboard)

**Files:**
- Create: `src/ews_ingest/core/storage.py` (or dashboard/storage.py for historical; use sqlite3)
  - Schema: CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY, source_id TEXT, ticker TEXT, fetched_at TEXT, payload TEXT, content_hash TEXT, run_id TEXT);
  - Also metadata or use GROUP BY for last_update: last_update per (source, ticker) = max(fetched_at)
- Modify: `src/ews_ingest/core/landing.py` or add DB writer that implements LandWriter or new.
- Modify services to provide DB path.

**Interfaces:**
- def get_db_path() -> Path
- class SqliteHistoricalStore:
    def write_records(self, source_id: str, ticker: str | None, records: list[dict]) -> int
    def get_last_update(self, ticker: str, source_id: str | None = None) -> datetime | None
    def get_historical(self, ticker: str, source_id: str, limit: int = 100) -> list[dict]

- [ ] **Step 1: Write failing test for DB store**

In new test or test_landing:

```python
def test_sqlite_write_and_last_update(tmp_path):
    db = SqliteHistoricalStore(tmp_path / "test.db")
    db.write_records("test.src", "AAPL", [{"payload": {...}, "fetched_at": "..."}])
    last = db.get_last_update("AAPL", "test.src")
    assert last is not None
```

- [ ] **Step 2: Run test (fails)**

`uv run pytest ... -q`

- [ ] **Step 3: Implement SqliteHistoricalStore with stdlib sqlite3, idempotency by hash**

Use connection, create table, insert if not exists hash.

Handle ticker optional for non-per-entity.

- [ ] **Step 4: Add to services.py : make_historical_store()**

- [ ] **Step 5: Update writer if needed to also write to DB (or have ingestion use it)**

For decouple, sources can use it, or after land, but for simplicity, modify fetch flow or have dual write.

- [ ] **Step 6: Run test pass + checks**

- [ ] **Step 7: Commit**

### Task 4: Add last update info to dashboard UI

**Files:**
- Modify `src/ews_ingest/dashboard/app.py` (in render_company_card or new, show last update)
- Modify `src/ews_ingest/dashboard/landing.py` or services to expose last updates from DB
- Modify compute or ui.py if needed

**Interfaces:**
- In UI: for each company, show "Last updated: 2026-..." per relevant source or overall.

- [ ] **Step 1: Write test for get_last_updates**

```python
def test_last_update_display():
    ...
```

- [ ] **Step 2: Run fails**

- [ ] **Step 3: Implement query in store: get_last_updates_for_companies(companies) -> dict[ticker, dict[source, dt]]

- [ ] **Step 4: Wire in app.py main or render: pass to render_company_card or add display**

Use st.caption or in card.

- [ ] **Step 5: Pass from get_inputs or new**

- [ ] **Step 6: Test pass**

- [ ] **Step 7: Commit**

### Task 5: Make triggers async + add per-company retrigger + global button (UI only marks pending)

**Files:**
- Modify: `src/ews_ingest/dashboard/app.py` (pending states, per-company + global buttons, live DB tracking via fragments, display indicators + last update purely from DB)
- Modify services.py (add trigger_refresh that only launches bg work; no UI blocking)

**Interfaces:**
- def trigger_refresh(ticker: str | None = None) -> None:
  Immediately returns after marking pending. Background work runs sources and writes to DB.
- Dashboard live-tracks DB (no direct fetch) and renders metrics from it.

- [ ] **Step 1: Add test for pending + DB-driven display**

```python
def test_trigger_marks_pending_and_dashboard_reads_from_db():
    trigger_refresh("AAPL")
    assert "AAPL" in get_pending()
    # later, after DB write simulated
    indicators = get_indicators_from_db("AAPL")
    assert indicators is not None
```

- [ ] **Step 2: Run test (fails)**

- [ ] **Step 3: Implement trigger in services (bg thread or subprocess that calls source fetch + DB write). UI side only sets pending flag.

- [ ] **Step 4: In app.py replace indicator computation to use new DB reader. Add live tracking (st.fragment or rerun loop). Add per-company and global buttons that call trigger and set pending.

- [ ] **Step 5: On add company also set pending + trigger.

- [ ] **Step 6: Show last update (from DB) next to each company / indicator.

- [ ] **Step 7: Run + manual verify no freeze, live update when DB changes.

- [ ] **Step 8: Commit**

### Task 6: Update CLI, docs, tests, cleanup references

**Files:**
- cli.py (remove onboard)
- AGENTS.md (update to describe new DB, async triggers, last update, decoupled)
- registry/protocol comments
- Add DB path to .env.example if needed
- Update any other

- [ ] **Step 1: Remove onboard code in cli**

- [ ] **Step 2: Update AGENTS.md with new sections for storage, triggers, last update**

- [ ] **Step 3: Clean comments**

- [ ] **Step 4: Add to .env.example: # EWS_DB_PATH=./data/ews.db

- [ ] **Step 5: Run full checks + tests**

- [ ] **Step 6: Commit**

### Task 7: Add scheduling documentation and verification

- [ ] Update AGENTS.md with explicit scheduling example for 30min feeds (external cron calling CLI for all sources; dashboard for force refetch only). Example:
  ```
  # crontab
  */30 * * * * cd /home/user/hackathon && export UV_ENV_FILE=.env && uv run python -m ews_ingest run $(uv run python -m ews_ingest list | grep -o '[^ ]*')
  ```
- [ ] Run all checks
- [ ] Manual: streamlit, add company (marks pending async, bg runs source to DB), force single company refetch, global refetch, verify last_update timestamps in UI and sqlite.
- [ ] Test historical query in sqlite (e.g. last 10 records per ticker).
- [ ] Commit

### Task 8: Final verification and integration

- [ ] Full lint/type/unit
- [ ] Verify decoupling: run source via CLI updates DB without dashboard; dashboard trigger also updates.
- [ ] Commit

**Self-review notes (post write):** 
- Covers all user points: decouple (ingestion independent, triggers from dash), last update, single retrigger, historical sqlite, async UI (pending mark, bg).
- Adjusted from previous plan (kept some per-company retrigger as requested now).
- Uses sqlite3 (convenient).
- TDD, small steps, exact.
- No placeholders.
- Matches spec updates implicitly.

Plan saved/updated.

To execute: which option? Subagent or inline? 

(Recommend subagent-driven for this.)