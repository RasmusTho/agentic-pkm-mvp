State: Specification directory (capability source of truth) for reliable embedding ingestion.

# Embedding Reliability & Pluggable Provider

## Capability boundary

Make full-vault embedding ingestion **reliable** under a memory-constrained local Ollama, by adding two things:

1. An **embedding execution queue** with backpressure: bounded concurrency, rate limiting, retry-with-backoff on transient `5xx`/`EOF`, and a per-object skip / dead-letter path so one embedding failure can never abort a whole ingest.
2. A **pluggable embedding provider** with an operator-selectable **Ollama-primary / Google Gemini-fallback** posture, under strict **dimension consistency** and a defined **re-index migration**.

Success target: ingest the full vault (~63 notes) to a populated index without crashing Ollama, satisfying the still-open substrate AC in [#2242](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2242) ("`index rebuild` reports processed >= 1").

This capability does **not** change the renderer, retrieval ranking, or the object/companion-note substrate (already repaired by #2242 children #2252/#2253/#2254). It changes only how embedding requests are executed and which provider produces vectors.

## Background (why this exists)

- The substrate (outbox worker → object store → `index rebuild`) is repaired. The remaining wall is the **embedding step**: a full vault ingest aborts with `RuntimeError: Ollama embedding requests failed (model=nomic-embed-text:latest, expected_dim=768) ... HTTP 500: do embedding request: ... EOF`.
- Root cause is memory, not concurrency alone: on the mac mini the runtime embeds via the single shared prod Ollama (`pkm-prod-ollama-1`, host port 11434) inside a **Colima 4 GB** VM, with `nomic-embed-text` + `llama3.1:8b` co-resident. Under load the model runner OOM-crashes (`EOF`).
- Current config: `LLM_PROVIDER=ollama`, `EMBED_MODEL=nomic-embed-text:latest`, `EMBED_DIM=768`, `OLLAMA_HOST/OLLAMA_URL=http://host.docker.internal:11434`.

## Decided posture (operator, 2026-06-20)

See [OPERATOR_EGRESS_DECISION.md](OPERATOR_EGRESS_DECISION.md). The operator chose **Ollama-primary + Google Gemini auto-fallback** (over local-only-Colima-bump and Gemini-primary):

- Ollama stays primary. Gemini is tried **only when the Ollama path fails after retries**.
- Gemini is pinned to a **dimension-matched** model: `gemini-embedding-001` with `output_dimensionality=768` (L2-renormalized) to match the existing index dim. Mixed dims are forbidden.
- Real vault note content egresses to Google **only on fallback** (when Ollama is down). A local-only configuration stays viable (no Gemini key set ⇒ no egress, fallback is a no-op).
- A fallback-written index is **mixed-identity** and must be reconciled by a re-index under the primary identity once Ollama recovers. Auto-fallback is a *bridge for ingest progress*, not a permanent split.
- The Colima 4→8 GB local fix was evaluated and **not chosen** (it restarts the shared dev+prod VM); it is recorded as the rejected alternative, not executed.

## Implementation tasks (execution order)

Ordered, independently mergeable slices. `→` denotes a hard dependency.

1. [OPERATOR_EGRESS_DECISION.md](OPERATOR_EGRESS_DECISION.md) — record the egress/provider-default decision (docs/ADR). *No code deps; land first as the governing decision the rest reference.*
2. [EMBEDDING_EXECUTION_QUEUE.md](EMBEDDING_EXECUTION_QUEUE.md) — bounded-concurrency + backoff + per-object dead-letter execution primitive. *Independent; highest reliability value; can run parallel with (3).*
3. [PLUGGABLE_PROVIDER_REGISTRY.md](PLUGGABLE_PROVIDER_REGISTRY.md) — formalize the provider registry behind `EmbeddingClientProtocol` + primary/fallback selection config. *Independent; parallel with (2).*
4. [GOOGLE_GEMINI_ADAPTER.md](GOOGLE_GEMINI_ADAPTER.md) — Gemini `gemini-embedding-001` with `output_dimensionality=768` adapter + secret handling. *→ (3).*
5. [PROVIDER_FALLBACK_ORCHESTRATION.md](PROVIDER_FALLBACK_ORCHESTRATION.md) — wire Ollama-primary → Gemini-fallback into the queue path, with identity tagging of fallback writes. *→ (2), (3), (4).*
6. [DIMENSION_CONSISTENCY_AND_REINDEX.md](DIMENSION_CONSISTENCY_AND_REINDEX.md) — per-vector identity recording, mixed-identity detection in `index doctor`, reconcile/re-index migration, and the `docs/EMBEDDINGS.md` fallback-rule update. *→ (5).*

Parallelizable pairs: {1}, {2,3} together, then {4}, then {5}, then {6}.

## Cross-Task Invariants / Interaction Safety

These hold *across* tasks and name the partial-failure seams.

- **CTI-1 — One steady-state identity per index.** At rest, every vector in an index shares one `EmbeddingIdentity (provider, model, dim, normalize)`. The dim guardrail (`EMBED_DIM=768`) is enforced for *every* provider (Ollama and Gemini) — a provider returning a non-768 vector fails that object (existing `assert_embed_dim` behavior), never silently resizes or mixes dims.
- **CTI-2 — Fallback is non-terminal.** A Gemini-fallback write produces a vector tagged with the **Gemini identity**, which differs from the Ollama primary identity even at equal dim (nomic and gemini-embedding-001 occupy different vector spaces; cosine scores across them are meaningless). The index is therefore **mixed** after any fallback. A fallback write is recorded as **reconcilable**, not done. The seam: *task 5 may write a fallback vector that task 6 must later re-embed under the primary identity.* If task 6 never runs, retrieval over fallback-written notes is degraded — task 6 owns convergence and `index doctor` surfaces the drift loudly.
- **CTI-3 — Query uses the primary identity.** The ASK/retrieval path always embeds the query with the **primary** identity, never the fallback. Fallback-written document vectors are knowingly-degraded matches until reconciled; this is acceptable as a temporary availability bridge and must be visible (doctor/preflight), never silent.
- **CTI-4 — Secret-gated egress.** Gemini is available only when its key (`GEMINI_API_KEY` / `GOOGLE_API_KEY`) is present. Absent key ⇒ Gemini provider is unavailable ⇒ fallback is a no-op that surfaces `index.embedding.failed` for that object (never crashes the worker, never logs the key or note content beyond existing provenance fields). This keeps a local-only deployment fully viable.
- **CTI-5 — Backpressure precedes fallback.** The queue exhausts bounded retry-with-backoff against the **primary** provider before declaring a primary failure and consulting fallback. Backoff (not just concurrency=1) is what lets a crashed Ollama runner reload between attempts. Fallback is the last resort, not the first retry.
- **CTI-6 — No abort on single-object failure.** When neither primary (after retries) nor fallback can embed an object, the object is skipped/dead-lettered with `index.embedding.failed` and the ingest **continues**. The existing all-zero-batch fail-loud guard (`embed_texts`, #2190) is preserved: a *provider-wide* outage still fails loud rather than producing a semantically dead index.

If these invariants cannot be stated for a re-cut of the slices, the slice boundaries are wrong.

## Capability acceptance criteria

- [ ] A full ~63-note vault ingest completes with the local Ollama primary + queue (bounded concurrency + backoff) without aborting the ingest, even when individual embeds transiently fail.
  - Verify: runtime receipt on the parent issue — `index rebuild` / ingest output showing processed >= 1 and the corpus embedded; failing-object count surfaced rather than aborting.
- [ ] With a Gemini key configured, an induced Ollama failure routes the affected objects to Gemini (`gemini-embedding-001` with `output_dimensionality=768`, L2-renormalized) and the ingest still completes; without a key, fallback is a no-op and the run degrades gracefully (no crash, `index.embedding.failed` emitted).
  - Verify: `tests/llm/test_provider_fallback*.py` (behavioral) + runtime receipt.
- [ ] Dimension consistency is enforced across providers and mixed-identity indexes are detectable and reconcilable.
  - Verify: `tests/.../test_dimension_consistency*.py` + `index doctor` mixed-identity detection test + `docs/EMBEDDINGS.md` fallback-rule update anchor.
- [ ] The egress decision and re-index path are documented and the owner doc no longer forbids the disciplined fallback it now ships.
  - Verify: doc anchors in `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` and `docs/EMBEDDINGS.md`.

## Relationship to GitHub issues

The specification is the source of truth for *what to build*; GitHub issues track *what to pick up next*.

- Parent feature issue: see [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) (validation hub; links #2242 as the substrate antecedent).
- One child slice issue per task file above, created in dependency order with `Verify:`-bearing acceptance criteria.

## Related docs

- Owner doc (normative embedding spec): `docs/EMBEDDINGS.md`
- Events: `docs/EVENTS.md` (`index.embedding.requested|created|failed`)
- LLM endpoints/providers: `docs/LLM.md`
- Retrieval: `docs/RETRIEVAL.md`
- Substrate antecedent: [#2242](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2242)
