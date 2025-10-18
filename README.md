# Agentic PKM API

FastAPI backend plus LangGraph agent pieces for the "Second-Brain" project.  
The service exposes simple CRUD for `/items`, a `/context` endpoint that returns repo memory, and a callable agent graph via `run_agent.py`.

## Getting Started
1. Create and activate a virtual environment (`python -m venv .venv && source .venv/bin/activate`).
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy the sample environment: `cp .env.example .env` and adjust `DATABASE_URL` if needed.
4. Run the API: `uvicorn app.main:app --reload`.

### Database
- Default configuration expects a local Postgres DSN. For quick experiments you can export `DATABASE_URL=sqlite+pysqlite:///./storage/dev.db`.
- Alembic is configured under `app/alembic/`; run migrations with `alembic -c app/alembic.ini upgrade head`.

### Agent CLI
- Invoke the agent workflow with `python run_agent.py`.
- Upcoming work: add CLI flags (`--task`, `--input`, `--dry-run`) as noted in `docs/ALIGNMENT.md`.

## Testing
- Execute `pytest` (VS Code picks this up automatically via `.vscode/settings.json`).
- Tests rely on an in-memory SQLite database and do not require external services.

## Debugging
- `DEBUGPY=1` enables the debugpy listener; by default it binds to port `15678`.
- Use the **Attach to API (debugpy)** VS Code configuration after starting the server.

## Project Memory
- Alignment, guardrails, and next steps live in `docs/ALIGNMENT.md`.
- Agent/system context is stored under `data/context/`.
