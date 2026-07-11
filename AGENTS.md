# AGENTS.md

## Documentation First

Before doing anything for the first time in this repo (or when touching opencode integration, Streamlit UI patterns, or new libraries), fetch the latest docs using the ctx7 tool to choose the most idiomatic option:

npx ctx7@latest library opencode "..." 
# or visit https://context7.com/docs/clients/opencode

## Project

Python 3.14 project managed with `uv` (uv.lock + pyproject.toml). `src/ews_ingest/` layout; hatchling build.

## Setup

- `uv python install 3.14 && uv sync --all-extras`
- `cp .env.example .env` (never commit `.env`)
- `export UV_ENV_FILE=.env` (or `--env-file .env` per-command)

## Verification (lint → format → type → test)

- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Type: `uv run ty check`
- All checks: `uv run ruff check . && uv run ruff format --check . && uv run ty check`
- Unit tests: `uv run pytest tests/unit -q`
- Single test: `uv run pytest tests/unit/test_foo.py`
- Integration (live net): `EWS_RUN_INTEGRATION=1 uv run --env-file .env pytest -m integration ...`

CI (.github/workflows/ci.yml) runs the checks + unit tests only.

## CLI

`uv run --env-file .env python -m ews_ingest <cmd>`

- `list` — all registered source_ids
- `validate` — sources.yaml + env vars
- `run <source_id>` — fetch + land records
- `onboard <TICKER> [--async]` — resolve ticker then run its per-entity sources (background if --async)

See src/ews_ingest/cli.py for details. SEC_USER_AGENT always required.

## Dashboard

`uv run --env-file .env streamlit run src/ews_ingest/dashboard/app.py`

- Reads JSONL from `data/landing/` (EWS_LANDING_DIR); demo values when empty.
- Indicators: auto-discover `Provider: SignalProvider` instances under `src/ews_ingest/dashboard/signals/` (pkgutil). Bind role → source_id in `src/ews_ingest/config/indicators.yaml`.
- Companies: dashboard mutates `data/companies/companies.json`; falls back to `src/ews_ingest/config/entities.yaml`.

## Adding ingestion sources

- Place connector in `src/ews_ingest/sources/<category>/foo.py`
- `@register_source("cat.foo", scope=Scope.PER_ENTITY)` (see Scope in core/protocol.py) on class with `fetch(self, ctx: FetchContext) -> Iterator[RawRecord]`
- All subpackages auto-imported by `src/ews_ingest/sources/__init__.py`
- `uv run python -m ews_ingest.tools.gen_sources_yaml` to regenerate `config/sources.yaml` (edit `_OVERRIDES` in the generator for host/rps/env/backfill)
- Add env keys to `.env.example` + sources.yaml via generator
- Wire into dashboard via indicators.yaml (and optional new signal)

sources.yaml is generated; run generator (or `--check`) after changes. See core/registry.py and sources/ examples.

## Style

- Ruff + ty rules are errors (see `[tool.ruff.lint]`, `[tool.ty.rules] all = "error"` in pyproject.toml).
- Type ignores: `ty: ignore[<code>]` only (`respect-type-ignore-comments = false`).
- Per-file-ignores relax tests, dashboard, cli, tools (pyproject.toml:79).
