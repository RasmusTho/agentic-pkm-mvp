State: SoT v5.5 baseline (practical contributor guide; if steps drift, update this file or defer explicitly to DEV_WORKFLOW/CI).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Contributing

## Toolchain
- Python: see `docs/PYTHON_VERSION_POLICY.md` (CI smoke currently uses 3.12; local dev may be newer).
- venv + pip (repo supports editable installs via `pyproject.toml`).
- Docker and Docker Compose
- Postgres (used for DB outbox + store in runtime mode)
- Optional: Ollama for local LLMs

## Setup
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then pip install -e ".[dev]"; fi

## Running tests
- Default quick run:
  - `make smoke`
- Deeper runs:
  - see `docs/TESTING.md` and `docs/DEV_WORKFLOW.md`

## Branching and commits
- Branch format: feature/<slug>, chore/<slug>, fix/<slug>
- Conventional commits: feat:, fix:, docs:, chore:, refactor:, test:
- Keep PRs small, include a test when possible

## Code style
- ruff for linting
- mypy for typing
- pytest for tests
- Deterministic functions for agents; no non-reproducible sleeps or random seeds

## Database
- Store schema is managed via Alembic migrations in `app/alembic/`.
- DB outbox table is ensured at runtime by `app/services/outbox.py:bootstrap()` (not via Alembic).

## Review checklist
- Tests pass locally
- New/changed events are documented under docs/EVENTS.md
- Agent input/output contract documented in docs/AGENTS.md
