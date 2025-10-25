# Agentic PKM – SoT v4.2 (MVP)

Production-minded personal knowledge system with agentic ingestion, LangGraph PER loops, hybrid search, and pgvector.

Quickstart

1) Runtime
- macOS (M-series) or Linux
- Docker and Docker Compose
- Python 3.14
- Optional: Ollama for local LLMs

2) Install
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

3) Database
docker compose -f docker-compose.yaml up -d postgres
export DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app"
PYTHONPATH="$(pwd)" alembic upgrade head

4) Local LLM (optional)
brew install ollama
OLLAMA_FLASH_ATTENTION="1" OLLAMA_KV_CACHE_TYPE="q8_0" ollama serve
ollama pull llama3.1:8b
ollama pull deepseek-r1:8b
export LLM_PROVIDER=ollama
export LLM_MODEL="llama3.1:8b"
export LLM_REASONING_MODEL="deepseek-r1:8b"

5) Run tests
PYTHONPATH="$(pwd)" env DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q

6) API (optional)
docker compose up -d api
Default: http://localhost:18000

Core concepts
- AMG/SetDB in Postgres: objects, chunks, embeddings, relations, decisions, audit
- Core-6 payload on objects: id, type, title, created, updated, origin
- Hybrid search: BM25-lite and embeddings (pgvector)
- LangGraph agents with PER loops: Normalizer, Classifier, Chunker, Deduper, CitationChecker, Indexer, Reviewer, SetEvaluator, Projector
- Event choreography: ingest.* and curation.*
- Governance: trust, maturity, provenance, promotion gates

## Promotion flow (Reviewer → SetEvaluator → Projector)

1. **Reviewer** computes trust and writes review decisions (allow/block), audit entries, and episodic memories.
2. **SetEvaluator** aggregates signals (citations, dedupe, embedding density) and writes `evaluate` decisions.
3. **Projector** reads the latest evaluation; when `promote=true` it inserts membership into the target set.

**Idempotency:**
`membership` enforces `UNIQUE (set_id, object_id)`.
Projector uses insert-or-ignore logic and emits both audit and episodic memory.

**Operational note:**
Legacy duplicates are purged automatically in the migration.

### Backfill hygiene job

Use the backfill job to close historical gaps (chunks, embeddings, review/evaluate decisions, projection):

```
PYTHONPATH="$(pwd)" DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" \
python -m app.jobs.backfill --limit 200 --trace-id job-backfill-001 --set-name "published"
```

With the repo’s Makefile:

```
DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" make backfill
```

Views for observability (`view_objects_missing_chunks`, `view_chunks_missing_embeddings`, `view_objects_missing_review`, `view_objects_ready_for_projection`) surface remaining gaps and should be empty after a successful run.

Docs
- docs/ARCHITECTURE.md
- docs/SYSTEM_OVERVIEW.md
- docs/SETTINGS.md
- docs/DATA_GOVERNANCE.md
- docs/VERSIONING.md

Status (MVP)
- Normalizer: done
- Classifier: done
- Chunker: done
- Deduper: done
- CitationChecker: done
- Indexer: done
- Reviewer: todo
- SetEvaluator: todo
- Projector: todo
- E2E: done
