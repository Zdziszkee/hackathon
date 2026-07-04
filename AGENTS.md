# AGENTS.md

## Project

Python project managed with `uv`, targeting Python 3.14.

## Commands

- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Type check: `uv run ty check`
- All checks: `uv run ruff check . && uv run ruff format --check . && uv run ty check`

## Style

Strict typing. Rules enabled as errors in `[tool.ty.rules]` and `[tool.ruff.lint]` in `pyproject.toml`.

Type-checker ignores: use `ty: ignore[code]` (not `type: ignore` — that is disabled).