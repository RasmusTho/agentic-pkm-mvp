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
