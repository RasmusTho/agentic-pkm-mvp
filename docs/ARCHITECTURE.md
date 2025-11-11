# Architecture — SoT v4.5A Canon

## Purpose & Principles
- Human-first and agentisk PKM: agents stay assistive, preserve author context, and only advance maturity when a reviewer signs off.
- Observability-first to främja transparens: every agent emits structured audit spans plus deterministic fixtures so regressions reproduce in CI.
- Core-6 frontmatter & UUID identity: each object carries the Core-6 envelope (id, type, title, created, updated, origin) and a stable UUID threaded through stores and events.
- Store abstraction & Outbox events: ObjectStore, VectorIndex, and RelationIndex share a Store interface, while the Outbox broadcasts change events for asynchronous consumers.
- Separation of trust and audit: trust levels gate promotion; audit trails remain append-only so reviewers can replay any decision independently.

## Core Architecture

### Agents
- Normalizer — accepts capture payloads, enforces Core-6 fields, and strips unsafe metadata.
- Classifier — tags object type, topic facets, and routing hints for downstream agents.
- Chunker — segments normalized text into retrieval-ready spans plus embedding metadata stubs.
- Deduper — compares against prior hashes and emits relation records for duplicates or merges.
- CitationChecker — validates outbound references and attaches citation debt metrics.
- Indexer — materializes embeddings, syncs ObjectStore + VectorIndex, and raises `index.object.embedded`.
- Reviewer — enforces maturity gates, toggles trust levels, and prepares Projector contracts.
- Projector — publishes curated packets to downstream surfaces (docs, API, knowledge packs).
- PromotionAgent — final arbiter that commits promotion decisions to audit + Outbox while coordinating cooldowns.

### Store Layer
ObjectStore persists object envelopes and agent decisions; VectorIndex stores chunk vectors plus embedding metadata; RelationIndex captures graph edges (duplicate_of, cites, derived_from) for query-time traversal. Each store implements CRUD via the Store abstraction so the same agent code works against in-memory dicts or Postgres-backed engines.

### Event Choreography
1. `ingest.object.created` records capture acceptance and seeds the PER loop.
2. `ingest.object.normalized`, `.classified`, `.chunked`, `.deduped`, `.citation_checked` mark completion of each agent and carry `trace_id` plus payload diff.
3. `index.object.embedded` signals VectorIndex writes and unlocks the Reviewer.
4. `promote.pending` captures Reviewer approval; `promote.done` finalizes PromotionAgent moves and informs subscribers such as search indexing or set sync.

### PromotionAgent Rules
- Idempotent writes: promotion can be retried safely because target maturity and storage side effects are computed deterministically from audit trails.
- Cooldown windows: move requests within the same five-minute window are coalesced to prevent thrash when upstream agents reclassify the same object.
- `move_policy` guardrails: `move_policy=advance_only` prohibits demotions outside manual overrides, while `move_policy=force` is reserved for maintenance tasks and always logs a privileged audit entry.

## Ingestion Pipeline (PER loop)
Every agent follows Plan → Execute → Reflect. Plan inspects the latest event plus Core-6 envelope to decide whether work is required, Execute performs the mutation using the Store layer, and Reflect writes audit spans, metrics, and Outbox entries. Data hand-offs are immutable payloads: Normalizer emits `normalized_object`, Chunker emits `chunk_set`, Deduper adds a `relation_patch`, CitationChecker appends `citation_report`, and Indexer produces an `embedding_batch`. The Reviewer consumes the cumulative context to assert maturity, then Projector and PromotionAgent close the loop. Failed executions requeue themselves by emitting a retryable event with the same `trace_id`.

## Persistence & Execution Modes
- `STORE_BACKEND=memory` is the default for CI and unit tests; it instantiates in-memory implementations of ObjectStore, VectorIndex, and RelationIndex with deterministic UUID seeds.
- `STORE_BACKEND=pg` connects to Postgres/pgvector for full-fidelity runs; migrations guarantee schema parity with the memory structs.
- VectorIndex persistence is optional JSONL snapshots: set `INDEX_PERSIST_PATH` when writing batches and `INDEX_PERSIST_LOAD` to bootstrap warm caches across runs.
- `audit_log()` always writes to the configured sink, falling back to `logs/audit.jsonl` when stdout/file destinations are unavailable, ensuring no audit gap.
- The LLM layer defaults to `LLM_PROVIDER=mock` with fixture responses for deterministic CI; production enabling switches providers via env, while `llm_retry()` applies exponential backoff and caps at three attempts per request.

## Retrieval Layer (Rerank & Hybrid Search)
Hybrid search merges BM25 (FTS) plus vector similarity, returning distinct object IDs with score provenance. `RerankerProvider` currently supports `none` and `mock_ce`, both injected via dependency wiring; v4.5A leaves reranking inert by default. Operators enable reranking with `RERANK_ENABLE=1`, choose providers via `RERANK_PROVIDER`, and bound cost using `RERANK_TOP_K`. `apply_optional_rerank()` (located in `app/retrieval/hybrid_rerank_hook.py`) is called at the end of `hybrid_search` after unioning lexical + vector matches; invariants: never drop items, only reorder the first `TOP_K`, and maintain stable IDs for downstream caching. The forward plan for v4.6 is a plug-in model that loads a real cross-encoder while respecting the hook interface so tests can keep swapping mocks without touching query code.

### Rerank Hook Placement
The adapter `app/retrieval/hook_adapter.py::maybe_rerank(query, items)` sits on the final step of `hybrid_search` after BM25/vector scores are normalized and merged. By default it returns items untouched; when `RERANK_ENABLE` is set it delegates to `apply_optional_rerank()` so PromotionAgent and downstream caches always observe deterministic payloads (id, text, score, snippet, metadata). Memory-mode CI keeps determinism because the mock cross-encoder is pure Python and respects the provided ordering contracts.

## Observability & CI
JSONL audit logs capture `trace_id`, agent name, inputs, and outputs for each PER step; correlated `span_id`s map to structured metrics for latency and retries. Deterministic CI runs use `pytest -q -m "not pg"`, memory stores, and mock LLMs to ensure reproducible timings. Outbox processing meets QAS-010 by keeping ingest-to-index latency ≤ 2 s, while search endpoints monitor QAS-003 with p95 latency < 250 ms under hybrid retrieval. Telemetry dashboards watch agent failure rates and promotion cooldown breaches so regressions are caught before shipping.

## Extensibility & v5 Direction
The v5 roadmap layers declarative reasoning (RDF/OWL/SHACL constraints) on top of the existing stores, enabling Reviewer and PromotionAgent to validate logic gates instead of bespoke Python checks. The Agent Memory Graph will evolve to persist reflective notes per object, informing future PER plans. Provenance and promotion governance will add policy bundles (who can promote, when to reset cooldowns) so humans stay accountable even as automation deepens.
