# AGENTS.md

## Project

Python project managed with `uv`, targeting Python 3.14.

## Commands

- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Type check: `uv run ty check`
- All checks: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

## Environment variables

Secrets/API keys live in `.env` (copy from `.env.example`; `.env` is gitignored, never commit it).

`uv` does not read `.env` files by default. Load it via uv's own `--env-file` support instead of
exporting vars manually or adding a dotenv dependency:

- Per command: `uv run --env-file .env python -m ews_ingest <cmd>`
- Per shell session (no flag needed afterwards): `export UV_ENV_FILE=.env`

Common commands:

- List sources: `uv run --env-file .env python -m ews_ingest list`
- Check missing env vars: `uv run --env-file .env python -m ews_ingest validate`
- Run one source: `uv run --env-file .env python -m ews_ingest run <source_id>`

## Style

Strict typing. Rules enabled as errors in `[tool.ty.rules]` and `[tool.ruff.lint]` in `pyproject.toml`.

Type-checker ignores: use `ty: ignore[code]` (not `type: ignore` — that is disabled).