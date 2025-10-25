# Architecture — SoT v4.2 (MVP Ingestion)

## System Overview
- AMG/SetDB in Postgres 16 with pgvector is the cognitive source of truth:
  - Tables: objects, chunks, embeddings, relations, sets, membership, decisions, audit.
  - objects.payload stores Core-6 (projection source of truth).
- Frontmatter contract: Markdown + YAML; Projector mirrors a whitelist only:
  - maturity, trust, aliases, related, parent, canonical, sets, scope, relevance_score.
  - Core-6 (id, type, title, created, updated, origin) is never overwritten by the projector.
- Event choreography: in-process queue with typed events:
  - ingest.* (normalization, chunking, indexing), curation.* (classification, dedupe, citation checks, review).
  - Every event carries trace_id.

## Agent Model (LangGraph PER)
- Each agent follows PER: Plan → Execute → Reflect.
- Conventions:
  - Deterministic/idempotent writes (UPSERT).
  - trace_id in all audit rows.
  - Structured output: { "event": "...", "object_id": "..." } plus agent fields.
  - Contract tests + e2e smoke.

## Data Model
- objects: one row per knowledge object; payload includes Core-6 and metadata.
- chunks: (object_id, idx, offset_start, offset_end, text).
- embeddings: (id, object_id, model, dim, vec).
- relations: typed edges (parent, canonical, related, IN_SET, ...).
- sets/membership: set:core|latent|transient, golden.
- decisions: key/value agent outputs (duplicate_of, type, trust, missing_citations).
- audit: (id, object_id, agent, action, ts, trace_id, details).

## Pipeline (MVP)
Ingestor → Normalizer → Classifier → Chunker → Deduper → CitationChecker → Indexer → Reviewer → SetEvaluator → Projector

### Normalizer
Input: file path
Output: DB objects with Core-6 in payload
Idempotent

### Classifier
Decisions: type, tags, conservative trust

### Chunker
Strategy: heading_first with fallback
Deterministic chunk boundaries, stores byte offsets

### Deduper
Similarity: max(cosine(hash-emb), jaccard(k=2), token overlap ratio)
Decision: duplicate_of { canonical_id, score }

### CitationChecker
Marks missing_citations
Blocks promotion on low trust + missing citations

### Indexer
BM25 (in-memory) + pgvector
Embeds chunks with provenance (object_id, idx, offsets)

### Reviewer
Gates from maturity.yaml
Auto-promote seed → note at confidence ≥ 0.7

### SetEvaluator
Applies set rules and membership

### Projector
Mirrors whitelist to frontmatter
Never mutates Core-6

## Events
{
  "type": "ingest.index.ready",
  "attrs": { "object_id": "uuid" },
  "trace_id": "..."
}

## Testing & CI
- Unit tests per agent, fast e2e
- Deterministic behavior
- CI runs pytest and short e2e

## Configuration
- data/context/*: maturity.yaml, retrieval.yaml, retention.yaml, agents.yaml
- app/settings.py: vector backend, model names, DB URL
- Env: DATABASE_URL, LLM_PROVIDER, LLM_MODEL, LLM_REASONING_MODEL

## Non-Goals
- Reranker, autoscaling, advanced QueryRouter/AnswerComposer
