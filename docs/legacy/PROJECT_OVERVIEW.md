State: Legacy (archived).
> **DEPRECATED (WS)** This document reflects a previous iteration (FastAPI/SQLAlchemy/LangGraph integrated). It is kept for reference. The WS overview is in docs/legacy/OVERVIEW_WS.md and policies in data/context/*.yaml.

# Project Overview

## Architecture
- **FastAPI service (`app/`)** exposes HTTP endpoints and orchestrates persistence through SQLAlchemy.
- **Database layer** uses `app/db.py` with SQLAlchemy ORM bound to the `DATABASE_URL` setting. Alembic migrations live under `app/alembic/`.
- **Agent workflow (`app/agent/`)** leverages LangGraph to hydrate context, reason over snippets, and log provenance.
- **Context memory (`data/context/`)** stores system, project, and preference JSON files consumed by `/context` and the agent.
- **Storage** assets include:
  - `storage/agent.duckdb` for structured provenance/context material.
  - `provenance.jsonl` for append-only run metadata.

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

## HTTP API
- `GET /` – simple service heartbeat.
- `GET /health` – readiness report covering SQL database, DuckDB access, and provenance log writability.
- `GET /version` – returns the current application version derived from `settings.app_version`.
- `GET /context` – serves repository memory (system, projects, preferences).
- `POST /items` / `GET /items` – demo CRUD endpoints managed via `app/api/items.py`.

## Command Line Agent
- Entry-point: `run_agent.py`.
- Flags: `--task`, `--input`, `--profile`, `--dry-run`.
- CLI interacts with `app.agent.graph.invoke`, which compiles a LangGraph state machine checkpointed in SQLite.

## Development Workflow
- **Virtual env**: `.venv` (activate and install via `requirements.txt` + `dev-requirements.txt`).
- **Tooling**:
  - `ruff` for linting/format, configured in `ruff.toml`.
  - `mypy` for static typing, configured in `mypy.ini`.
  - `pytest` for integration/unit tests under `tests/`.
- **Pre-commit**: run `pre-commit install` to enable local ruff/mypy/pytest hooks.
- **CI**: `.github/workflows/ci.yml` runs Ruff → mypy → pytest on pushes and pull requests.

## Operations
- Version bump, release tagging, storage rotation, auth, and observability guidance is captured i `docs/OPERATIONS.md`.
- Use `python scripts/bump_version.py <new_version>` (with `--dry-run` support) to update versions, then `python scripts/tag_release.py` to annotate releases.
- Archive DuckDB/provenance data via `python scripts/rotate_storage.py [--dry-run]` which writes timestamped artifacts under `storage/archive/`.
- Health and readiness behaviours are centralised in `app/health.py`.
- Structured logging + Prometheus metrics toggles live i `app/observability.py` (`METRICS_ENABLED=1` to expose `/metrics`).
- Lokal Docker-stack (Prometheus + Grafana) finns beskriven i `docs/OBSERVABILITY_STACK.md`.
- Kör API+Postgres+Redis via `docker-compose.yaml` för en självbärande dev-basad (se README för instruktioner).
- Future roadmap (auth, observability, automation) tracked in `docs/legacy/ALIGNMENT.md` and `data/context/projects.json`.

## Information Flow (MVP)
```
  Source Input
    (pdf/url/text)
         |
         v
  Parse & Chunk (Docling/LLM)
         |
         v
  Triage Agent (trust = provisional/reviewed)
         |
         +--> if provisional --> stage chunk preview (no main index)
         |
         v
  Frontmatter Builder (YAML v0.2 – intents & emergent tags)
         |
         v
  Vault Writer (Obsidian Markdown)
         |
         +--> Reflection Queue (/storage/reflect) vid låg klarhet
         |
    [Optional human review -> trust=reviewed]
         |
         v
  Hybrid Index (Postgres FTS + pgvector)
         |
         v
  Recall Agent (top-k, cites, snippet)
```

### Ingestion Pipeline (Detaljer)
- **Ingress**: `POST /ingest` accepterar `{id?, kind?, source_ref?, payload, text}` och dirigeras till `app/search/service.py::ingest_object`.
- **Lifecycle hooks**: `normalize_payload` fyller `object_type`, `system_intent`, `emergent_tags` och triggar reflektion (`/storage/reflect/*.json`) samt uppdaterar analytics/loggar.
- **Synthesis relationer**: `synthesis_note`-poster loggar relationer `type="synthesizes"` i `logs/relations.jsonl`.
- **Storage**: `objects` (JSONB + `search_vector`) och `embeddings` (pgvector) i Postgres uppdateras idempotent (`ON CONFLICT` vid samma `id`).
- **Embedding**: standarden är en deterministisk hashing-funktion (1536-dimensioner) – byt ut mot extern modell via tjänstlagret när API-nycklar finns.
- **Benchmarks**: kör `python scripts/bench.py --count 2000 --k 10` efter större importer för att mäta p50/p95-latens.

### Search Service (MVP)
- `/search` förenar Postgres-FTS (`search_ft`) med pgvector-sök via Reciprocal Rank Fusion.
- Resultatet returnerar `object_id`, `score` och hela JSONB-payloaden – downstream-klienter ansvarar för rendering.
- CLI-stödet (`run_agent.py --task recall`) använder samma sökväg och presenterar toppträffar + citat.
- Alternativa backends (t.ex. Qdrant) utvärderas först om pgvector visar sig otillräckligt; tills dess hålls kodbasen pgvector-fokuserad.

## Getting Started Recap
1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt -r dev-requirements.txt`
3. `cp .env.example .env` and adjust settings.
4. `uvicorn app.main:app --reload` to launch the API.
5. `pytest`, `ruff check .`, and `mypy app tests` to validate.
