# Agentic PKM — SoT v4.2 (MVP Ingestion)

This repository contains an agent-first, LangGraph-based MVP ingestion pipeline for an AI-assisted Second Brain.
The Source of Truth (SoT) is Postgres (AMG/SetDB) with `pgvector` for embeddings. Obsidian is the human surface; Git is the ground truth; YAML frontmatter is the contract.

## Goals (MVP Ingestion)
- Run end-to-end on a small corpus: Ingestor → Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer → Reviewer → SetEvaluator → Projector.
- Write audit/trace for every step (a `trace_id` follows each object).
- Build BM25 + pgvector index and verify chunk provenance (object id + offsets).
- Reviewer: auto-promote `seed → note` at `confidence ≥ 0.7`, otherwise emit feedback.
- Projector: mirror only the whitelist (maturity, trust, aliases, related, parent, canonical, sets, scope, relevance_score). Core-6 stays untouched.

## Architecture
- Agents are built on LangGraph and share a minimal PER loop (Plan → Execute → Reflect).
- AMG/SetDB in Postgres 16: objects, chunks, embeddings, relations, sets, membership, decisions, audit.
- Events (in-proc): `ingest.*`, `curation.*`. Agents consume/emit events; an orchestrator remains thin.
- File-first: Markdown + YAML frontmatter; Core-6 is stored in DB payload and projected to files (whitelist only).

See detailed design in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quickstart

### Prerequisites
- Python 3.11+
- Docker and Docker Compose
- Optional: Ollama for local LLMs: `llama3.1:8b` (general), `deepseek-r1:8b` (reasoning)

### Run Postgres
```bash
docker compose -f docker-compose.yaml up -d postgres
mkdir -p docs

cat > README.md <<'EOF'
# Agentic PKM — SoT v4.2 (MVP Ingestion)
This repository contains an agent-first, LangGraph-based MVP ingestion pipeline for an AI-assisted Second Brain.
The Source of Truth (SoT) is Postgres (AMG/SetDB) with pgvector for embeddings. Obsidian is the human surface; Git is the ground truth; YAML frontmatter is the contract.

## Goals (MVP Ingestion)
- Run end-to-end on a small corpus: Ingestor → Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer → Reviewer → SetEvaluator → Projector.
- Write audit/trace for every step (a trace_id follows each object).
- Build BM25 + pgvector index and verify chunk provenance (object id + offsets).
- Reviewer: auto-promote seed → note at confidence ≥ 0.7, otherwise emit feedback.
- Projector: mirror only the whitelist (maturity, trust, aliases, related, parent, canonical, sets, scope, relevance_score). Core-6 stays untouched.

## Architecture
- Agents are built on LangGraph and share a minimal PER loop (Plan → Execute → Reflect).
- AMG/SetDB in Postgres 16: objects, chunks, embeddings, relations, sets, membership, decisions, audit.
- Events (in-proc): ingest.*, curation.*. Agents consume/emit events; an orchestrator remains thin.
- File-first: Markdown + YAML frontmatter; Core-6 is stored in DB payload and projected to files (whitelist only).

See detailed design in docs/ARCHITECTURE.md.

## Quickstart
### Prerequisites
- Python 3.11+
- Docker and Docker Compose
- Optional: Ollama for local LLMs: llama3.1:8b (general), deepseek-r1:8b (reasoning)

### Run Postgres
docker compose -f docker-compose.yaml up -d postgres

### Database migration
export DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app"
PYTHONPATH="$(pwd)" alembic upgrade head

### Run tests
PYTHONPATH="$(pwd)" DATABASE_URL="postgresql+psycopg://app:app@127.0.0.1:15432/app" pytest -q

### Local LLMs (optional)
brew install ollama
ollama serve &
ollama pull llama3.1:8b
ollama pull deepseek-r1:8b
export LLM_PROVIDER=ollama
export LLM_MODEL=llama3.1:8b
export LLM_REASONING_MODEL=deepseek-r1:8b

## Repository Layout
app/
  agents/
    normalizer/
    classifier/
    chunker/
    deduper/
    citation_checker/
    indexer/
    reviewer/
    set_evaluator/
    projector/
    runner.py
  search/
    bm25_lite.py
    embeddings.py
    vector_index.py
  alembic/
docs/
  ARCHITECTURE.md
tests/
  agents/
  e2e/

## Development Principles
- Human-first
- Separation of trust (own/imported/AI-generated)
- Observability & provenance
- Reflexivity (reflections, scorecards, feedback loops)
- TDD

## License
MIT
