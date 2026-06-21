State: Accepted (owner-settled decision recorded 2026-06-20; ratified into owner docs by #2317). Records the standing embedding-egress posture: Ollama-primary with an identity-preserving Google Gemini auto-fallback, and the controlled supersession of the prior no-generic-fallback invariant in `docs/EMBEDDINGS.md`. **Numbering note:** the governing issue #2317 originally named this "ADR-0015", but ADR-0015 through ADR-0022 were already taken on `origin/main` (the SBS series). This record uses the next free number, **ADR-0023**; its sibling retrieval-topology ADR is **ADR-0024**, and **ADR-0025** is reserved for sibling issue #2318.
Doc role: Decision record (ADR)
Authority: Authoritative for the embedding-egress posture (primary provider, fallback provider, and the conditions under which fallback is permitted). The governing reference for the identity-preserving Gemini exception to the EMBEDDINGS no-generic-fallback rule.
Owner: Architecture / Embedding & retrieval posture
Temporal class: Durable decision (supersede via a new ADR, do not edit in place). Revisit on a provider/identity change, a multi-provider load-balancing pivot, or a change to the egress/privacy posture — see "When to revisit".
Source of truth: This ADR for the decision; `docs/EMBEDDINGS.md` and `docs/LLM_ROUTING.md` carry the operational mirror. The compiled task policy (`runtime/settings/llm_routing.yaml`) and the recorded embedding identity remain the runtime machine projection.

# ADR-0023: Embedding egress — Ollama-primary with identity-preserving Gemini auto-fallback

**Date:** 2026-06-20
**Status:** Accepted (owner-settled decision)

---

## Context

The system embeds vault content (and the matching ASK query) through a single embedding identity so that document and query vectors are comparable. The normative embedding contract (`docs/EMBEDDINGS.md :: Fallback rule`) historically forbade *generic provider fallback*: the runtime could repair the endpoint for the chosen provider, but it must never silently switch to a different provider/model that changes provider, model, dimension, or normalization, because that breaks the RAG identity invariant and makes similarity scores meaningless. `docs/LLM_ROUTING.md` mirrored this: "Embedding fallback is blocked unless the fallback preserves the resolved embedding identity."

Two facts created pressure on that posture:

- **Reliability.** A single locally-hosted Ollama is a single point of failure for the entire embedding path. A transient Ollama outage or memory-bound failure stalls indexing and degrades recall, with no second source. The Embedding Reliability capability (issue #2292) exists to add a disciplined, dimension-matched fallback path rather than fail the whole ingest.
- **An available identity-compatible provider.** Google Gemini's `text-embedding-004` can be requested at **768 dimensions** — the same native dimension as the local default `nomic-embed-text` — and can be L2-normalized to match the local normalization, and supports query-vs-document usage so the query==document identity can be preserved. This makes a *narrow, identity-preserving* fallback possible without the generic-fallback failure mode the original rule was written to prevent.

The owner settled this on 2026-06-20: the embedding posture is **Ollama-primary with a Gemini auto-fallback that preserves embedding identity**, *not* a blanket reversal of the no-generic-fallback rule. This ADR records that decision and the controlled supersession.

Options weighed:

- **Option A — keep strict no-fallback.** Maximally safe for the identity invariant, but leaves the embedding path single-sourced; a local Ollama failure stalls ingest and degrades recall with no recovery short of operator intervention.
- **Option B — generic provider fallback.** Maximizes availability but is exactly what the original invariant forbids: a fallback that changes provider/model/dimension/normalization silently corrupts retrieval comparability.
- **Option C — identity-preserving fallback (chosen).** Permit fallback to a *specific, dimension- and normalization-matched* secondary provider whose embedding identity is comparable to the primary, with re-index discipline when identities are mixed. Captures the availability benefit of B while honoring the comparability concern that motivated A.

## Decision

**Option C — adopt Ollama-primary embedding with an identity-preserving Google Gemini auto-fallback, and supersede the EMBEDDINGS no-generic-fallback invariant as a scoped, identity-preserving exception (not a blanket reversal).**

Concretely:

1. **Primary:** Ollama (`nomic-embed-text`, native `768` dimensions, L2-normalized) remains the primary embedding provider on the normal dispatch path (precedence as documented in `docs/EMBEDDINGS.md :: Configuration`: `EMBED_PRIMARY_PROVIDER` → profile → `LLM_PROVIDER`).

2. **Fallback:** Google Gemini `text-embedding-004` is the sanctioned **identity-preserving** secondary, consulted only on primary-provider failure. It is permitted *only* when it preserves the resolved embedding identity:
   - **dimension-matched** — requested at `768` to match the local default;
   - **normalization-matched** — L2-normalized to match `EMBED_NORMALIZE` behavior;
   - **query==document identity** — the same identity is used for both the indexed document/chunk vectors and the ASK query vector (the RAG invariant in `docs/EMBEDDINGS.md :: Query vs Document embeddings`).

3. **Mixed-identity discipline:** when the stored index contains vectors from more than one identity (e.g. some objects embedded under Ollama and some under the Gemini fallback), the system must **re-index on mixed identity** so comparability is restored under a single identity. The fallback is a reliability bridge, not a license to leave a permanently heterogeneous index.

4. **Scoped supersession:** this ADR **explicitly supersedes** the `docs/EMBEDDINGS.md :: Fallback rule` "no generic provider fallback" invariant — but only as an *identity-preserving exception*. Generic fallback that changes provider/model/dimension/normalization in a way that breaks comparability remains forbidden. The invariant's intent (retrieval comparability) is preserved; only the absolute "never switch provider" wording is relaxed for the dimension/normalization/query-identity-matched Gemini case.

This is **not** a move to a local-only posture and **not** an unbounded multi-provider load-balancing posture. It is a single sanctioned, identity-matched fallback for availability, with re-index discipline as the comparability backstop. The egress posture (sending content to Gemini on fallback) is governed by the broader privacy/security docs and the operator's configuration — the runtime change that *registers and wires* the Gemini adapter is out of scope here and is tracked by #2292 / #2296 / #2297.

## Relationship to the prior invariant

The original `docs/EMBEDDINGS.md :: Fallback rule` said the runtime "must not silently switch to another embedding model/provider that changes provider, model, dimension, or normalization." This ADR reframes that rule:

- **Still true:** a fallback that *changes* dimension, normalization, or query/document identity is forbidden — it corrupts retrieval.
- **Now permitted (the exception):** a fallback to a *named, identity-preserving* provider (Gemini `text-embedding-004` @ 768, normalization-matched, query==document) on primary failure, with re-index on mixed identity.

The reconciled wording lives in `docs/EMBEDDINGS.md :: Fallback rule`, anchored back to this ADR; `docs/LLM_ROUTING.md` and `docs/LLM.md` mirror the change per the EMBEDDINGS change policy.

## When to revisit

Reopen and re-decide (a new ADR) if any of these change:

- The chosen primary or fallback **identity changes** (different model, native dimension, or normalization) such that 768/L2/query==document no longer holds — that is an identity change and a new posture.
- The system moves to **multi-provider load balancing or steady-state heterogeneous serving**, where "re-index on mixed identity" is no longer the operating model.
- The **egress/privacy posture** changes (e.g. a local-only requirement, or a different cloud provider), which would re-open whether Gemini fallback is acceptable at all.

## Consequences

- The embedding path gains a second source: a transient Ollama failure can fall back to identity-matched Gemini instead of stalling ingest, improving recall availability.
- The no-generic-fallback invariant is **superseded as a scoped exception**, not deleted: the comparability intent survives; only an identity-preserving Gemini fallback is newly allowed.
- A mixed-identity index is a transient state that must trigger **re-index**, not a steady state. Operators and doctor/preflight surfaces should treat mixed identity as a rebuild signal.
- The **documented** `EMBED_DIM` default is corrected to `768` in `docs/EMBEDDINGS.md` / `docs/LLM.md` to match the identity-preserving posture (both the local `nomic-embed-text` native size and the Gemini `text-embedding-004` @ 768 fallback). The separate runtime constant `app/embedding_config.py::DEFAULT_EMBED_DIM` is a code change tracked by #2296 / #2297 and is **out of scope** for this docs-only ratification — no `app/` change is made here.
- This ADR is docs/decision-only. The adapter registration and fallback orchestration are runtime work tracked by #2292 / #2296 / #2297; this record ratifies the posture they implement against.

## References

- #2314 — RAG/memory decomposition epic (parent track)
- #2317 — this ratification (two ADRs, docs-only); records the ADR-0015→ADR-0023 renumber
- #2292 — Embedding Reliability capability (disciplined dimension-matched fallback + re-index path)
- #2296 / #2297 — runtime `DEFAULT_EMBED_DIM` / embedding-config changes (out of scope here; the code change the doc default mirrors)
- `docs/EMBEDDINGS.md` :: Fallback rule, Configuration, Embedding identity (reconciled wording + corrected default)
- `docs/LLM_ROUTING.md` :: Configuration precedence / Current policy (embedding-fallback mirror)
- `docs/LLM.md` :: Ollama (Embeddings) (operational mirror of the corrected default)
- ADR-0024 — sibling retrieval-topology ratification
