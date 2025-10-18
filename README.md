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

## Architecture Snapshot
```
              +---------------------------+
              |        API Clients        |
              +-------------+-------------+
                            |
                        HTTP (REST)
                            |
                  +---------v----------+
                  |   FastAPI app/     |
                  |  - routers (items) |
                  |  - health/version  |
                  |  - context loader  |
                  +----+----+----+-----+
                       |    |    |
          SQLAlchemy    |    |    | LangGraph
            Session     |    |    v
                       |    |  +---------+
                       |    |  | agent/  |
                       |    |  | nodes   |
                       |    |  | graph   |
                       |    |  +----+----+
                       |    |       |
                       |    |   provenance
                       |    |       v
                       |    |  +-----------+
                       |    |  | storage/  |
                       |    |  | agent.duckdb
                       |    |  +-----------+
                       |    |
                       |    +----------------------+
                       |                           |
                +------v------+          +---------v---------+
                |  Postgres   |          | data/context/*.json|
                | (DATABASE_URL)         | + docs memory     |
                +-------------+          +-------------------+
```

## Versioning
- Use `python scripts/bump_version.py <new_version>` (add `--dry-run` to preview) to update `settings.app_version` plus related docs.
- Create annotated tags with `python scripts/tag_release.py [--dry-run|--push]`; tag names default to `v<version>`.
- Record notable changes in the decision log after tagging.

## Maintenance
- Rotate DuckDB/provenance artifacts with `python scripts/rotate_storage.py [--dry-run]` (archives land in `storage/archive/`).
- Auth + rate limiting roadmap is captured in `docs/AUTH_RATE_LIMITING.md`.

## Observability
- Structured JSON logs configured via `app/observability.py`; use standard logging levels (`INFO` default).
- Enable Prometheus metrics by setting `METRICS_ENABLED=1`; `/metrics` endpoint becomes available (consider securing behind reverse proxy).
- Optional local stack: see `docs/OBSERVABILITY_STACK.md` for Docker Compose (Prometheus + Grafana).

## Containerized Dev
- Build & run API + dependencies via Docker Compose:

```bash
docker compose up --build
```

- Services: FastAPI (`http://localhost:8000`), Postgres (`localhost:5432`), Redis (`localhost:6379`).
- Compose reads `.env`; override `DATABASE_URL`/`API_KEY` there as needed.

## Developer Workflow
- Run `pre-commit install` to activate local hooks (ruff, mypy, pytest) before committing.

## Upcoming API Contracts
These specs guide the next implementation milestone:

### `POST /ingest`
Request payload:
```json
{
  "source": {"type": "file|url|text", "path": "...", "url": "...", "text": "..."},
  "tags": ["topic/ai", "project/second-brain"],
  "notes": "optional"
}
```
Response payload:
```json
{
  "ok": true,
  "title": "Foo",
  "path": "vault/Foo.md",
  "tags": ["topic/ai"],
  "chunks": [{"id": "chunk-1", "text": "...", "size": 800}]
}
```

### `GET /recall?q=...&k=5`
Response payload:
```json
{
  "query": "...",
  "results": [
    {"path": "vault/Foo.md", "title": "Foo", "score": 0.83, "snippet": "...", "tags": ["topic/ai"]}
  ]
}
```
