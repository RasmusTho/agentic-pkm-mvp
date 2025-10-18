# Agentic PKM API

FastAPI backend plus LangGraph agent pieces for the "Second-Brain" project.  
The service exposes `/items` CRUD, `/context` for repo memory, `/health` for readiness, `/version` for build info, and a callable agent graph via `run_agent.py`.

## Getting Started
1. Create and activate a virtual environment (`python -m venv .venv && source .venv/bin/activate`).
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy the sample environment: `cp .env.example .env` and adjust `DATABASE_URL` if needed.
4. Run the API: `uvicorn app.main:app --reload`.

### Database
- Default configuration expects a local Postgres DSN. For quick experiments you can export `DATABASE_URL=sqlite+pysqlite:///./storage/dev.db`.
- Alembic is configured under `app/alembic/`; run migrations with `alembic -c app/alembic.ini upgrade head`.

### Agent CLI
- Run the workflow with `python run_agent.py --task summarize --input "demo text"`.
- `--dry-run` previews the payload without executing; `--profile` selects `work|home|creative`.
- `--input -` reads text from stdin, otherwise pass the content directly.

### API Endpoints
- `GET /health` returns aggregated readiness details for the SQL DB, DuckDB store, and provenance log.
- `GET /version` returns `{"version": settings.app_version}` (override via env).
- `GET /context` streams repo memory for the agent.
- `GET /items`, `POST /items` provide basic demo CRUD.

## Testing
- Execute `pytest` (VS Code picks this up automatically via `.vscode/settings.json`).
- Tests rely on an in-memory SQLite database and do not require external services.

## Quality Gates
- Ruff and mypy configs live in `ruff.toml` and `mypy.ini`; install dev deps via `pip install -r dev-requirements.txt`.
- CI (`.github/workflows/ci.yml`) runs Ruff → mypy → pytest on pushes and pull requests.

## Debugging
- `DEBUGPY=1` enables the debugpy listener; by default it binds to port `15678`.
- Use the **Attach to API (debugpy)** VS Code configuration after starting the server.

## Project Memory
- Alignment, guardrails, and next steps live in `docs/ALIGNMENT.md`.
- Agent/system context is stored under `data/context/`.
- Operational runbooks (versioning, storage rotation) live in `docs/OPERATIONS.md`.
- Deep-dive architecture, API, and workflow notes are in `docs/PROJECT_OVERVIEW.md`.
