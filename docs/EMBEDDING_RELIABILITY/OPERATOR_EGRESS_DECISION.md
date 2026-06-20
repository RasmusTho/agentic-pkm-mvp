---
name: Operator Egress & Provider-Default Decision
description: Records the operator's data-egress / provider-default decision for embeddings and the rejected alternatives
task_id: EMBEDREL-01
source_anchor: docs/EMBEDDINGS.md :: Fallback rule
parent_capability: Embedding Reliability & Pluggable Provider
prerequisites: []
depends_on: []
can_parallelize_with: [EMBEDDING_EXECUTION_QUEUE.md, PLUGGABLE_PROVIDER_REGISTRY.md]
---

# Operator Egress & Provider-Default Decision

## Purpose

Capture the operator's explicit, signed-off decision on **where embedding compute runs and whether real vault note content may leave the machine**, so no agent re-litigates it and the implementation defaults are unambiguous. Embeddings were local-only until now; routing to Google Gemini is the first path that egresses note content externally, which is an irreversible/external decision the operator owns.

## What This Task Does

Adds this decision record and updates the embedding owner doc to reflect the chosen posture. It ships **no runtime behavior** by itself — it is the governing decision the code tasks (queue, registry, Gemini adapter, fallback, re-index) implement against.

## Decision (2026-06-20)

**Chosen: Ollama-primary + Google Gemini auto-fallback.**

- Ollama (`nomic-embed-text:latest`, dim 768) stays the **primary** embedding provider.
- Google **Gemini** is invoked **only when the Ollama path fails after the queue's bounded retry-with-backoff**.
- Gemini is pinned to a **dimension-matched** model — `text-embedding-004` @ **768** — to match the existing index dim. Mixing dims is forbidden (it corrupts the vector index).
- Data egress boundary: real vault note content is sent to Google **only on fallback** (when Ollama is unavailable). Steady-state, embeddings stay local.
- **Local-only stays viable:** if no Gemini key is configured, the Gemini provider is unavailable and fallback is a no-op (the object surfaces `index.embedding.failed`; nothing egresses).
- A fallback-written index is **mixed-identity** and must be reconciled by a re-index under the primary identity once Ollama recovers (see [DIMENSION_CONSISTENCY_AND_REINDEX.md](DIMENSION_CONSISTENCY_AND_REINDEX.md)).

## Secret handling

- Gemini key is supplied via env/secret only: `GEMINI_API_KEY` (preferred) or `GOOGLE_API_KEY`. Free tier.
- The key is **never** committed to the repo, written to logs, or echoed in events/receipts. Provenance records the provider/model/dim/normalize identity, not the key or note content beyond existing fields.

## Rejected alternatives (evaluated)

- **Local-first (Colima 4→8 GB):** raise the shared Colima VM memory so co-resident `nomic-embed-text` + `llama3.1:8b` stop OOM-crashing. Cheapest and keeps all content local, **but** restarts the single shared Colima VM that hosts **both** dev and prod runtimes on the mac mini (a dev+prod blip), and may still OOM if 8 GB is insufficient. Not chosen; recorded here so it is not re-proposed without new evidence. The queue + backpressure (task 2) still reduces peak pressure on the local path regardless.
- **Gemini-primary:** route all embeddings to Google. Most reliable and removes local OOM entirely, **but** egresses *all* vault content continuously and abandons local-only as the default. Not chosen.

## Acceptance Criteria

- [ ] This decision record exists with the chosen posture, secret env var, egress boundary, and rejected alternatives.
  - Verify: doc presence — `docs/EMBEDDING_RELIABILITY/OPERATOR_EGRESS_DECISION.md` (this file).
- [ ] `docs/EMBEDDINGS.md` "Fallback rule" no longer forbids the disciplined, dim-matched, re-index-reconciled fallback this capability ships; it points to this decision and to the re-index task.
  - Verify: doc anchor — `docs/EMBEDDINGS.md :: Fallback rule` references disciplined fallback + this record.

## How to Verify (Pre-Merge)

- Confirm this file renders and states the chosen posture + secret var + rejected alternatives.
- Confirm `docs/EMBEDDINGS.md :: Fallback rule` reads consistently with the chosen disciplined-fallback posture (no contradiction with shipped behavior).

## Out of Scope

- Implementing the queue, registry, Gemini adapter, fallback wiring, or re-index migration (separate tasks).
- The prod rollout itself (operator-acknowledged promotion, handled via the release-channel skills).

## Related Docs

- Owner doc: `docs/EMBEDDINGS.md`
- Capability overview: [README.md](README.md)
- Re-index path: [DIMENSION_CONSISTENCY_AND_REINDEX.md](DIMENSION_CONSISTENCY_AND_REINDEX.md)

## Related GitHub Issues

Create one bounded docs slice issue (`lane:governance` or docs lane) for this decision record + the `docs/EMBEDDINGS.md` fallback-rule update. It has no code dependencies and should land first.
