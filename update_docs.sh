set -euo pipefail

mkdir -p docs

cat > README.md <<'EOF'
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

Docs
- docs/ARCHITECTURE.md
- docs/archive/architecture/SYSTEM_OVERVIEW.md
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
EOF

cat > docs/ARCHITECTURE.md <<'EOF'
# Architecture — SoT v4.2

1. Runtime Topology
- App (Python 3.14): agents, graphs, API
- Postgres + pgvector: AMG/SetDB (objects, chunks, embeddings, relations, decisions, audit)
- LLM backends: local (Ollama) and remote (OpenAI, Azure, Anthropic) via env

2. Data Model (AMG/SetDB)
- objects(id, kind, source_ref, ts, payload jsonb, search_vector tsvector)
- chunks(id, object_id, idx, payload jsonb)
- embeddings(id, object_id, model, dim, vec vector)
- relations(src, dst, type, payload jsonb)
- decisions(id, object_id, key, value jsonb, created_at)
- audit(id, object_id, agent, action, ts, trace_id, details jsonb)
Core-6 lives under objects.payload.core6

3. Event and Graphs (LangGraph)
- Each agent is a PER loop: Plan, Execute, Reflect
- Normalizer → ingest.normalize.*
- Classifier → curation.classify.*
- Chunker → ingest.chunk.*
- Deduper → curation.dedupe.*
- CitationChecker → curation.citation.*
- Indexer → ingest.index.*
- Next: Reviewer, SetEvaluator, Projector

4. Retrieval
- BM25-lite over FTS
- Vector search over pgvector
- Hybrid: union and re-rank

5. LLM Abstraction
- app/llm/adapter.py
- LLM_PROVIDER, LLM_MODEL, LLM_REASONING_MODEL

6. Observability
- audit rows for every write
- trace_id propagated

7. Invariants
- Stable object identity by origin
- embeddings count ≥ chunk count after indexing
- Reviewer will gate promotion on trust and citations

8. Deployment
- Single node default
- Scale horizontally via idempotent writes
- Remote LLM opt-in by env
EOF

mkdir -p docs/archive/architecture

cat > docs/archive/architecture/SYSTEM_OVERVIEW.md <<'EOF'
# System Overview — SoT v4.2

Why
Turn unstructured notes into trusted, retrievable knowledge with provenance and promotion gates.

How
1. Normalize file → Core-6 and raw text
2. Classify object → type and labels
3. Chunk text → semantic chunks
4. Dedupe objects → near-duplicate collapse
5. Check citations → trust surface
6. Index chunks → embeddings in pgvector
7. Reviewer (next)
8. SetEvaluator (next)
9. Projector (next)

Contracts

Object payload.core6
id, type, title, created, updated, origin

Agent Output Envelope
event, object_id, trace_id, meta

Decisions
duplicate_of: canonical_id and score
missing_citations: count
type: value

Retrieval Modes
vector, bm25, hybrid

Trust and Promotion
Reviewer blocks when trust is low or citations missing
EOF

git add README.md docs/ARCHITECTURE.md docs/archive/architecture/SYSTEM_OVERVIEW.md
git commit -m "docs: update README and add architecture/system overview for SoT v4.2"
git push
