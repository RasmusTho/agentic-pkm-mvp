State: Parent feature issue draft (pre-filing) for the Embedding Reliability & Pluggable Provider capability.

> Once filed on GitHub, update this header with the live issue number and lifecycle state.

# [Embedding Reliability] Reliable embedding ingestion + pluggable provider (Ollama-primary, Gemini-fallback)

## Context

The ingest/index substrate was repaired (#2242 children #2252/#2253/#2254), but a full vault ingest still aborts at the **embedding step**: the shared local Ollama (`nomic-embed-text`, Colima 4 GB) OOM-crashes (`EOF`) under load, leaving the vault unindexed and Companion recall degraded. This capability makes embedding ingestion reliable and adds an operator-selected Ollama-primary / Google Gemini-fallback provider posture. Governed by `docs/EMBEDDING_RELIABILITY/README.md`; operator egress decision recorded in `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` (2026-06-20).

## Scope

Outcome boundary (not one PR): a bounded-concurrency embedding queue with backpressure + retry-with-backoff + per-object dead-letter; a formalized pluggable provider registry; a Google Gemini adapter (`gemini-embedding-001` with `output_dimensionality=768`, L2-renormalized) with env-only secrets; Ollama→Gemini fallback orchestration; and dimension-consistency + mixed-identity detection + a reconcile/re-index migration. See the specification directory `docs/EMBEDDING_RELIABILITY/`.

## Source Anchors
- `docs/EMBEDDING_RELIABILITY/README.md :: Capability boundary`
- `docs/EMBEDDINGS.md :: Fallback rule`
- `#2242` (substrate antecedent; this capability satisfies its AC2 "index rebuild processed >= 1")

## Constraints
- Dimension consistency is mandatory: one identity per index; the dim guardrail (`EMBED_DIM=768`) holds for every provider; never silently mix dims (CTI-1).
- Real vault content egresses to Google only on fallback; local-only stays viable with no key set (CTI-4).
- Gemini key via env/secret only; never committed or logged.
- No dev/prod feature split — identical feature across environments; only configured values differ.
- Prod rollout is operator-acknowledged (release-channel skills); do not mutate prod without ack.

## Acceptance Criteria
- [ ] A full ~63-note vault ingest completes under Ollama primary + queue without aborting, surfacing failed-object counts instead of crashing.
  - Verify: runtime receipt on this issue — `index rebuild` output showing processed >= 1 and corpus embedded.
- [ ] With a Gemini key, induced Ollama failure routes affected objects to Gemini (`gemini-embedding-001` with `output_dimensionality=768`, L2-renormalized) and the ingest completes; without a key, fallback is a graceful no-op (no crash, `index.embedding.failed` emitted).
  - Verify: `tests/llm/test_provider_fallback.py` + `tests/indexer/test_provider_fallback_indexer.py` (behavioral) + runtime receipt.
- [ ] Dimension consistency enforced across providers; mixed-identity indexes are detectable (`index doctor`) and reconcilable (re-index).
  - Verify: `tests/cli/test_index_reconcile.py` + `tests/indexer/test_mixed_identity_detection.py` + `docs/EMBEDDINGS.md :: Fallback rule` anchor.
- [ ] Egress decision and re-index path documented; owner doc no longer forbids the disciplined fallback it now ships.
  - Verify: doc anchors `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` and `docs/EMBEDDINGS.md :: Fallback rule`.

## Implementation Tasks

Specification directory: `docs/EMBEDDING_RELIABILITY/`. Execution order:

1. `OPERATOR_EGRESS_DECISION.md` (EMBEDREL-01) — decision record + owner-doc fallback-rule update.
2. `EMBEDDING_EXECUTION_QUEUE.md` (EMBEDREL-02) — queue/backpressure/retry/dead-letter.
3. `PLUGGABLE_PROVIDER_REGISTRY.md` (EMBEDREL-03) — provider registry + primary/fallback selection config.
4. `GOOGLE_GEMINI_ADAPTER.md` (EMBEDREL-04) — Gemini adapter + secret handling.
5. `PROVIDER_FALLBACK_ORCHESTRATION.md` (EMBEDREL-05) — Ollama→Gemini fallback wiring.
6. `DIMENSION_CONSISTENCY_AND_REINDEX.md` (EMBEDREL-06) — identity recording, mixed-identity detection, reconcile/re-index migration, owner-doc update.

Parallelizable: {1}, {2,3}, then {4}, then {5}, then {6}.

## Verification Path

Per-task: behavioral tests under `tests/llm/`, `tests/indexer/`, `tests/cli/` (each task spec names its test pointers); regression that mock/ollama and the ASK query path are unchanged; the `not-pg` unit gate with `--timeout 120` (#2260).

## Validation / Acceptance Path

Post-merge: run a full local vault ingest (dev) and record the receipt here (processed count, fallback_used signals, doctor identity report). Promote to test then prod via the release-channel skills with operator ack (egress posture already signed off). Owner-doc (`docs/EMBEDDINGS.md`) promotion ships within EMBEDREL-06.

## Out of Scope
- Renderer / retrieval ranking / object+companion-note substrate (already repaired).
- Colima memory bump (evaluated, rejected — see decision doc).
- Multi-vault dims epic (#2143) beyond referencing the dim-change re-index path.

## Source Docs
- `docs/EMBEDDING_RELIABILITY/` (specification directory)
- `docs/EMBEDDINGS.md`, `docs/EVENTS.md`, `docs/LLM.md`, `docs/RETRIEVAL.md`
