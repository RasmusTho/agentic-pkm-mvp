# Architecture — SoT v4.2 Baseline

This document captures the system-wide reference introduced with SoT v4.2. It describes runtimes, data model, LangGraph agents, queues, and invariants that remain the foundation for later extensions (including the v4.3 Obsidian integration addendum below).

## 1. Runtime Topology
- **App (Python 3.14)**: FastAPI API, LangGraph agents, background jobs.
- **Postgres + pgvector (SetDB/AMG)**: primary persistence for objects, chunks, embeddings, relations, decisions, sets, membership, audit.
- **Redis (optional)**: lightweight cache and queue bridge.
- **LLM backends**: local Ollama (llama3.1 8B, deepseek-r1 8B) and remote providers (OpenAI, Azure, Anthropic) selected via env.

### Deployment surfaces
- Docker Compose (`docker-compose.yml`) provides db, redis, api.
- Agents and jobs run inside the Python app container or locally via CLI (`app/agents/runner.py`, `app/jobs/*`).

## 2. Data Model (SetDB / AMG)
Core tables stored in Postgres:
- `objects(id UUID, kind, source_ref, payload jsonb, ts, search_vector tsvector)`
- `chunks(id UUID, object_id UUID, idx int, payload jsonb, offset_start, offset_end, text)`
- `embeddings(id UUID, object_id UUID, model text, dim int, vec vector)`
- `decisions(id UUID, object_id UUID, key text, value jsonb, created_at timestamptz)`
- `audit(id UUID, object_id UUID, agent text, action text, ts timestamptz, trace_id text, details jsonb)`
- `sets(id UUID, name text)` and `membership(id UUID, set_id UUID, object_id UUID)`
- `agent_memories(id UUID, run_id UUID, layer text, payload jsonb, provenance jsonb, created_at timestamptz)`

**Core-6** fields (`id`, `type`, `title`, `created`, `updated`, `origin`) are stored under `objects.payload.core6` and are immutable outside the normalizer.

## 3. Event & Graph Flow (LangGraph PER loops)
Each agent runs as a Plan → Execute → Reflect loop with explicit audit logging.

Order of execution in the ingestion pipeline:
1. **Normalizer** (`ingest.normalize.*`) — loads file, stabilizes Core-6, writes object & episodic memory.
2. **Classifier** (`curation.classify.*`) — tags & trust score; writes decisions/audit/memory.
3. **Chunker** (`ingest.chunk.*`) — splits text into logical spans and stores chunks.
4. **Deduper** (`curation.dedupe.*`) — identifies near duplicates; writes `duplicate_of` decisions.
5. **CitationChecker** (`curation.citation.*`) — flags missing citations and emits promotion blockers.
6. **Indexer** (`ingest.index.*`) — embeds every chunk (pgvector) and records stats memory.
7. **Reviewer** (`curation.review.*`) — aggregates provenance, writes `review` decisions & episodic memory.
8. **SetEvaluator** (`promotion.evaluate.*`) — computes promotion score (`evaluate` decisions).
9. **Projector** (`promotion.project.*`) — ensures membership in target sets when promoted.

Graphs are declared in `app/agents/*/graph.py` using `app/agents/base/graph.PERSpec`. CLI entry point: `python -m app.agents.runner --agent <name>`.

## 4. Retrieval & Search
- **BM25-lite** (`app/search/bm25_lite.py`) builds tsvector search vectors for objects.
- **pgvector** embeddings stored per chunk; retrieval uses cosine distance.
- Hybrid retrieval merges lexical and vector results before response composition.

## 5. LLM Abstractions
- `app/llm/adapter.generate()` selects providers via `LLM_PROVIDER`, `LLM_MODEL`, `LLM_REASONING_MODEL`.
- Supports JSON-mode prompts, optional reasoning traces (DeepSeek R1, OpenAI reasoning models).

## 6. Observability & Governance
- Every agent writes an audit row with `trace_id`, `agent`, `action`, and structured details.
- Episodic memories persisted through `app/memory/store.py` allow agents to read past context while remaining idempotent.
- Invariants:
  - Stable object identity keyed by `core6.origin` hash.
  - `embeddings` count ≥ chunk count per object after indexer.
  - Promotion gates enforced via Reviewer/SetEvaluator/Projector decisions and set membership.

## 7. Queues & Jobs
- Ingestion typically triggered via CLI/tests; WS queue (future) routes ingestion events.
- `app/jobs/backfill.py` performs hygiene (chunks, embeddings, review, evaluate, projection) on existing objects.

## 8. Deployment Notes
- Scale horizontally by running multiple agent workers; writes are idempotent and keyed by UUIDs.
- Remote LLM usage gated behind environment configuration; defaults to local Ollama if available.
- Alembic migrations tracked in `app/alembic/versions/` (merged heads guaranteed by SoT v4.2).

---

## Addendum: SoT v4.3 — Obsidian Integration & Lifecycle

SoT v4.3 layers Obsidian vault mirroring, export, and promotion/backfill automation on top of the v4.2 baseline. Highlights:

- **File-first lifecycle** that keeps Markdown sources in sync with SetDB (create/update/rename/delete semantics, conflict resolution).
- **Promotion chain** (Reviewer → SetEvaluator → Projector) now feeds Obsidian export and published sets.
- **Export pipeline** (`scripts/export_objects.py`) writes Core-6 + metadata frontmatter and optional chunk breakdowns into the vault.
- **Backfill hygiene** (`make backfill`) ensures historical objects receive chunks, embeddings, reviews, evaluations, and projections.
- **Dedicated deep dive**: see [`docs/architecture/obsidian_integration.md`](architecture/obsidian_integration.md) for detailed lifecycle flows, sequence diagrams, and operational guidance.

Future SoT releases will build on this foundation (e.g., merge/conflict tooling in v4.4).


## Status & Fitness
- SoT v4.3: live architecture
  - PER-loop baslager (plan→act→reflect) med trace_id
  - Outbox-driven indexering (p95 outbox→index ≤ 2s) — QAS-010 guard i CI
  - Fake search (deterministisk embedding) — k6 p(95)<250ms — QAS-003 guard i CI
  - Contracts: OpenAPI/AsyncAPI lintas i CI
- 4.3.1: Obsidian-first (pågår)
  - System settings som Markdown + JSON Schema
  - Git-driven watcher, rename utan re-embed, body-diff→re-embed
