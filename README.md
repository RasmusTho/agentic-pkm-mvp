# Agentic PKM API

FastAPI backend plus LangGraph agent pieces for the "Second-Brain" project.  
The service exposes `/items` CRUD, `/context` for repo memory, `/health` for readiness, `/version` for build info, and a callable agent graph via `run_agent.py`.

## Getting Started
1. Create and activate a virtual environment (`python -m venv .venv && source .venv/bin/activate`).
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy the sample environment: `cp .env.example .env` and adjust `DB_DSN` (keep `VECTOR_BACKEND=pgvector`).
4. Run the API: `uvicorn app.main:app --reload --port 8000` (Docker publishes 18000→8000).

### Database
- The service targets Postgres with the `pgvector` extension. Point `DB_DSN` at your instance (Docker Compose provides `postgres://app:app@postgres:5432/app`).
- Apply schema changes with Alembic: `alembic -c app/alembic.ini upgrade head` (creates the `objects` + `embeddings` tables and FTS artifacts).

### Agent CLI
- Kör sammanfattningar med `python run_agent.py --task summarize --input "demo text"`.
- `--task recall --input "query"` nyttjar hybrid-sökningen (Postgres FTS + pgvector) och skriver ut toppträffarna.
- `--dry-run` visar payloaden utan att exekvera; `--profile` styr guardrails (`work|home|creative`).
- `--input -` läser från stdin, annars passas texten direkt.

### API Endpoints
- `GET /health` kontrollerar Postgres-anslutning, DuckDB-provenance och svarar `503` på avvikelser.
- `GET /version` returnerar `{"version": settings.app_version}`.
- `GET /context` strömmar agentens kontext (`data/context/*.json`).
- `POST /ingest` tar `{id?, kind?, source_ref?, payload, text}` och skriver metadata + embeddings till Postgres (`objects`/`embeddings`).
- `POST /search` accepterar `{query_text?, query_embedding?, k}` och kör FTS, vektorsök eller hybrid (Reciprocal Rank Fusion).
- `GET /items`, `POST /items` erbjuder enkel CRUD-demo (SQLite i tester, Postgres i drift).

### Search Architecture
- **Storage**: `objects` (UUID PK, JSONB payload, genererad `search_vector`) + `embeddings` (pgvector, refererar `objects.id`).
- **FTS**: `search_ft(query, k)` använder `plainto_tsquery('english', ...)` och GIN-indexet på `search_vector`.
- **Vector**: `PgVectorIndex` kapslar psycopg-anrop (`ivfflat`, `lists=100`); JSONB-filter stöds via `payload @> ...`.
- **Hybrid**: `search_hybrid` hämtar top-K från FTS + vektor och kombinerar dem med Reciprocal Rank Fusion (`1/(60+rank)` per lista).
- **Backends**: `VECTOR_BACKEND=pgvector` (enda stödda backend i nuläget).

### Migration from Chroma
1. Stoppa tjänsten (`docker compose down`).
2. Ta bort gamla Chroma-volymer (`rm -rf storage/chroma` om de finns).
3. Uppdatera `.env` till `DB_DSN`, `VECTOR_BACKEND` (ska vara `pgvector`) och `EMBED_MODEL`.
4. Kör Alembic: `alembic -c app/alembic.ini upgrade head`.
5. Starta stacken (`docker compose up -d`) och re-ingesta källor via nya `/ingest`.

## Testing
- Execute `pytest` (VS Code picks this up automatically via `.vscode/settings.json`).
- Enhetstesterna stubbar pgvector-indexet och kräver inga externa tjänster.

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
- Services: FastAPI (`http://localhost:18000`), Postgres (`localhost:15432`), Redis (`localhost:6379`).
- Compose läser `.env`; justera `DB_DSN`, `VECTOR_BACKEND` (lämna som `pgvector`), `API_KEY` m.fl. där.

## Developer Workflow
- Run `pre-commit install` to activate local hooks (ruff, mypy, pytest) before committing.

## API Contracts & Roadmap
Aktuell funktionalitet och kommande steg:

### `POST /ingest`
Request payload:
```json
{
  "id": "3f0b4f86-...",
  "kind": "note",
  "source_ref": "obsidian/inbox/foo.md",
  "payload": {"title": "Foo", "tags": ["topic/ai"]},
  "text": "Alpha beta gamma"
}
```
Response payload:
```json
{
  "ok": true,
  "object_id": "3f0b4f86-...",
  "dimensions": 1536,
  "model": "openai/text-embedding-3-large"
}
```

### `POST /search`
Request payload:
```json
{
  "query_text": "alpha",
  "query_embedding": [0.12, 0.34, ...],
  "k": 10
}
```
Response payload:
```json
{
  "hits": [
    {
      "object_id": "3f0b4f86-...",
      "score": 0.0331,
      "payload": {"title": "Foo", "text": "Alpha beta gamma"}
    }
  ]
}
```

### Nästa steg
- Behåll pgvector som default; utvärdera alternativa backends (t.ex. Qdrant) först när krav på prestanda kräver det.
- Experimentera med olika `ivfflat` parametrar (`lists`, `probes`) och utöka benchmarkscriptet.
- Lägg till streaming- eller batchingstrategier för bulk-ingest om behov uppstår.
