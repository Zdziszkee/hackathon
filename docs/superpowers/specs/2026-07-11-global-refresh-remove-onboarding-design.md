# Global Refresh + Remove Hardcoded Companies + Remove Portfolio Onboarding — Design Spec

**Date:** 2026-07-11
**Status:** User-approved design (spec written; awaiting user review of this doc)
**Scope:** Single feature iteration. Removes legacy complexity while delivering one global "refetch everything" mechanism.
**Approach chosen:** Approach 1 (extract/reuse core run path for full refresh; full removal of targeted onboarding).

## Problem

The dashboard has:
- Hardcoded prototype companies in `src/ews_ingest/config/entities.yaml` that auto-seed `data/companies/companies.json` on first run via `CompanyStore.seed_from_yaml` + `_ensure_company_store_bootstrap`.
- Per-company "↻" refresh buttons that trigger targeted `PortfolioOnboarding` for a single ticker (using single-entity resolver).
- `PortfolioOnboarding` (and `OnboardingTask`) logic duplicated in spirit between dashboard Add/Refresh and the CLI `onboard <TICKER>` command.
- No single "refresh everything" action; refreshes are either per-company (dashboard) or per-source (CLI `run`).

User wants:
- Remove **all** hardcoded companies (clean empty start; user populates only via Add form).
- Remove per-company refresh buttons.
- One global refresh button that refetches latest data for **everything** (all enabled sources).
- On Add, also refetch everything (no targeted per-ticker).
- Remove `PortfolioOnboarding` entirely (dashboard + CLI `onboard` subcommand) to simplify.

## Goal

- Portfolio always starts empty (no auto-seed from yaml).
- One global "Refresh all data" button (in Companies section header) that runs every enabled source (PER_ENTITY sources now cover all current companies via full resolver; aggregates/news/macro etc. run once).
- Add ticker also triggers the same full refresh.
- Delete `PortfolioOnboarding` / `OnboardingTask` / related async per-ticker machinery + CLI `onboard` command.
- Delete `entities.yaml` + all seeding/bootstrap/fallback code.
- Keep `run <source_id>` and dynamic `companies.json` as the core mechanisms.
- Simplify `app.py` significantly.

## Non-Goals (YAGNI)

- Keep any form of targeted per-ticker refresh (user explicitly wants full refetch on add).
- Preserve CLI `onboard` subcommand.
- Detailed per-source progress panels for the global run (lightweight status is sufficient).
- New public API or CLI command for "refresh all".
- Changing how individual sources are implemented or their scopes.

## Architecture

### High-level data flow (global refresh + Add)

```
Add ticker (or global button click)
  ├─ CompanyStore.add_ticker(ticker)  → writes data/companies/companies.json
  ├─ bust_inputs_cache()
  └─ trigger_full_refresh()  [bg thread/task]
       └─ for every enabled source_id:
            services = make_services_from_env()  # loads fresh companies.json
            ctx = build_context(...)             # full resolver
            source = get_source(sid)
            for rec in source.fetch(ctx): ...    # per-entity sources auto-cover all cos
            writer.write(batch)
       (on completion: next dashboard render sees fresh landing data)
```

- `PER_ENTITY` / `FACILITY` sources iterate `ctx.resolver.all()` (now the live portfolio).
- `SECTOR_AGGREGATE` / `MANIFEST` / `UNIVERSE` etc. run once.
- Matches "full run of every enabled source".

### Module changes

- **Delete:** `src/ews_ingest/config/entities.yaml`
- **Delete / remove:** `src/ews_ingest/dashboard/onboarding.py` (entire module + `OnboardingTask`, etc.)
- **dashboard/company_store.py**: remove `seed_from_yaml()` method + seeding annotations.
- **dashboard/app.py**:
  - Remove all onboarding imports, session keys (`_SESSION_TASKS_KEY`, etc.), `_ensure_session_tasks`, `_running_loop`, `_on_refresh_clicked`, `_schedule_onboarding`, `_render_onboarding_panels_fragment`, `_bust_onboarding_session`, `_ensure_company_store_bootstrap`.
  - Remove per-company refresh buttons from `_render_company_cards`.
  - Add global refresh button in Companies section header.
  - On successful Add: after `add_ticker` + bust, call `trigger_full_refresh()` then `st.rerun()`.
  - Introduce lightweight `trigger_full_refresh()` (or call a shared helper).
- **cli.py**:
  - Remove `cmd_onboard` and its handler.
  - Remove `onboard` subparser + `--async` arg from `main()`.
  - Simplify `_default_entities_path()`: only json path; no yaml fallback. Empty list if missing.
- **dashboard/services.py** (or new small `dashboard/refresh.py` for cleanliness):
  - Add `trigger_full_refresh()` (or `run_all_enabled_sources()`) that iterates `registry.all_source_ids()`, checks enabled/env, builds ctx with full resolver, runs fetch+land.
  - Reuse logic from `cli.cmd_run` / `build_context` / writer (extract if needed for DRY).
- **Other**:
  - `config.py` / `core/entities.py`: `load_entities_file` can stay (supports json); yaml usage removed from call sites.
  - Tests: remove `tests/unit/test_onboarding.py` and references. Update any tests assuming yaml seed.
  - `AGENTS.md`: update CLI section (no more onboard), remove yaml fallback notes, document new global refresh behavior.

### Why full refresh on Add is acceptable

- User explicitly chose this to enable removing the onboarding machinery.
- New ticker is immediately in the json → full run will pick it up via the resolver.
- Trade-off accepted: adding one company now refreshes the whole portfolio (simpler code, "everything" is always fresh).

## Component / UX Design

- Global button: `st.button("↻ Refresh all data", key="global_refresh", ...)` placed in the "Companies" header area (after the section title markdown, near the Add form).
- Disabled while running (simple `st.session_state` flag).
- On completion / next interaction, indicators update automatically because they read landing zone.
- Optional lightweight feedback: `st.toast("Full refresh started")` or a short `st.status` context manager around the bg task scheduling.
- No per-company buttons or per-ticker progress panels.
- "No companies yet" empty state remains.
- Add form behavior: success message + auto full refresh + rerun.

## Error Handling & Edge Cases

- Per-source failures in full refresh: log (as before), continue with other sources. Overall status can be "partial" but we keep it simple (no new complex task objects).
- Missing env for a source: skip (same as validate / run).
- Empty portfolio on global refresh: runs non-per-entity sources only (per-entity sources with empty resolver produce nothing).
- Concurrent refreshes: last one wins for landing data (idempotent writes).
- CLI `run <sid>` remains unchanged and is the escape hatch for specific sources.
- Companies added via direct json edit are picked up on next full refresh or dashboard load.

## Testing Strategy

- Unit: `CompanyStore` load/add/remove still works with pure json (existing tests).
- Dashboard signals / compute tests: update any that seeded via yaml.
- Remove entire `test_onboarding.py`.
- Manual / integration: start with empty `data/companies/companies.json`, Add ticker → verify data lands for its sources + aggregates, global button re-runs everything.
- CLI: `list` / `validate` / `run` still work; `onboard` removed (update help/tests if any).
- Verify no yaml fallback paths remain (grep + type checks).

## Migration / Backwards Compatibility

- Existing `data/companies/companies.json` is preserved (users keep their portfolio).
- If `companies.json` is absent → empty portfolio (new default).
- `entities.yaml` deleted — no longer shipped.
- Old `onboard` CLI users must switch to dashboard Add + global refresh, or use `run <sid>` after manual json edit.
- No data loss; landing zone is append-only.

## Open Questions (none after clarifications)

All resolved via user answers:
- Hardcoded removal: full delete + code purge.
- Global = full run of every enabled source.
- On Add = full refetch.
- Full removal of onboarding (incl. CLI).

## Files Touched (summary)

**Delete:**
- src/ews_ingest/config/entities.yaml
- src/ews_ingest/dashboard/onboarding.py (or strip to nothing)
- tests/unit/test_onboarding.py (or the bulk of it)

**Edit:**
- src/ews_ingest/dashboard/app.py (biggest change — remove ~150+ lines of onboarding UI/logic, add global button + call site)
- src/ews_ingest/dashboard/company_store.py (remove seed method)
- src/ews_ingest/cli.py (remove onboard command + simplify default path)
- src/ews_ingest/dashboard/services.py (add full-refresh trigger)
- AGENTS.md
- Various test files (seed references)
- pyproject / other? (none expected)

## Verification Steps (post-implementation)

1. `uv run ruff check . && uv run ruff format --check . && uv run ty check`
2. `uv run pytest tests/unit -q` (minus removed onboarding tests)
3. Manual: `uv run --env-file .env streamlit run src/ews_ingest/dashboard/app.py` — start empty, Add ticker, click global refresh, verify data.
4. CLI: `uv run --env-file .env python -m ews_ingest list/validate/run <sid>` still work.
5. No references to deleted yaml or onboarding in code/docs.

This design is complete, minimal, and directly implements the user's "go" direction.
