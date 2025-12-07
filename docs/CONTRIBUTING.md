State: Partially outdated relative to SoT v4.10; see DEV_WORKFLOW.md.
# Contributing

## Toolchain
- Python 3.11+
- Poetry or venv + pip
- Docker and Docker Compose
- Postgres 16 with pgvector
- Optional: Ollama for local LLMs

## Setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose -f docker-compose.yaml up -d postgres
export DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app"
PYTHONPATH="$(pwd)" alembic upgrade head

## Running tests
PYTHONPATH="$(pwd)" DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q

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
- Never edit existing migrations; write a new one
- Idempotent writes (UPSERT)
- Include trace_id in all audit rows

## Review checklist
- Tests pass locally
- New/changed events are documented under docs/EVENTS.md
- Agent input/output contract documented in docs/AGENTS.md
