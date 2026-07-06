State: Accepted (owner-ratified decision recorded 2026-07-06; supersedes ADR-0023's fallback dimension pin). Records the primary-embedding-model switch to BGE-M3 at 1024 dimensions and the corresponding re-pin of the sanctioned Gemini fallback from `output_dimensionality=768` to `output_dimensionality=1024`. This ADR is docs/decision-only — no `app/` change and no re-index are made here; those are tracked by the sibling implementation issue (H4).
Doc role: Decision record (ADR)
Authority: Authoritative for the embedding-egress dimension pin (primary model/dim, fallback provider/dim). Supersedes `docs/adr/ADR-0023-embedding-egress-gemini-fallback.md`'s `output_dimensionality=768` pin; ADR-0023's mixed-identity/reconcile discipline (CTI-1/2/3) remains intact and unchanged.
Owner: Architecture / Embedding & retrieval posture
Temporal class: Durable decision (supersede via a new ADR, do not edit in place). Revisit if the primary model, its dimension, or the fallback shape contract changes again.
Source of truth: This ADR for the decision; `docs/EMBEDDINGS.md` carries the operational mirror. `app/components/embeddings/legacy.py :: EmbeddingIdentity` and `app/llm/embeddings.py` are the runtime projection, updated by the H4 implementation slice (#2984), not by this ADR.

# ADR-0052: Embedding fallback re-pin to 1024 dims for the BGE-M3 primary-model switch

**Date:** 2026-07-06
**Status:** Accepted (owner-ratified decision)

---

## Context

`docs/adr/ADR-0023-embedding-egress-gemini-fallback.md` (2026-06-20) sanctioned an Ollama-primary
embedding posture (`nomic-embed-text`, native **768** dimensions) with a dimension-matched, L2-renormalized
Google Gemini `gemini-embedding-001` auto-fallback pinned to `output_dimensionality=768`. That fallback
write carries the Gemini identity (mixed-identity, reconcilable per CTI-2) while the query path always
uses the primary identity (CTI-3). `docs/EMBEDDINGS.md :: Fallback rule` mirrors this 768-dim pin.

The Fable-5 second-brain audit (`docs/research/yggdrasil-fable5-audit.md`) and the resulting
`docs/MIMER_CAPABILITY_HARDENING/` capability-hardening program identified BGE-M3 as the recommended
primary embedding model to replace `nomic-embed-text`, specifically for **Swedish/multilingual retrieval
quality** on this vault's bilingual SV/EN corpus (G3-1, `docs/MIMER_CAPABILITY_HARDENING/RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md`).
BGE-M3's dense embedding output is **1024-dimensional**, which changes `EmbeddingIdentity`
(`app/components/embeddings/legacy.py :: EmbeddingIdentity`, the frozen `provider`/`model`/`dim`/`normalize` tuple) from
`dim=768` to `dim=1024`.

This directly breaks ADR-0023's sanctioned fallback: a fallback pinned to `output_dimensionality=768`
no longer matches a `dim=1024` primary, so the "dimension-matched" precondition that makes the Gemini
fallback safe (rather than a forbidden generic/identity-changing fallback) no longer holds. This
collision was flagged — not resolved — by
`docs/MIMER_CAPABILITY_HARDENING/README.md :: One remaining collision` (owner decision 2) and
`docs/MIMER_CAPABILITY_HARDENING/RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md :: §2`, which named the exact
choice this ADR now ratifies:

- **(a) Re-pin the fallback to `output_dimensionality=1024`** — `gemini-embedding-001` supports
  1024-dim output via Matryoshka Representation Learning (MRL) truncation + L2-renormalize, the
  identical mechanism ADR-0023 already relies on for the 768-dim pin. This preserves the availability
  bridge with the same discipline, just re-pinned to the new primary dimension.
- **(b) Accept a fallback-less window** during migration — simpler, but an Ollama outage during that
  window dead-letters the embed request locally (the documented no-key/no-fallback behavior) instead
  of falling back.

The owner ratified **(a)** on 2026-07-06.

## Decision

**Adopt BGE-M3 as the primary embedding model at 1024 dimensions (replacing `nomic-embed-text`@768),
and re-pin the sanctioned Gemini fallback to `output_dimensionality=1024` (was 768) so the
dimension-matched, mixed-identity, reconcilable fallback bridge described by ADR-0023 continues to
hold at the new primary dimension.**

Concretely:

1. **Primary:** BGE-M3, native **1024** dimensions, L2-normalized, replaces `nomic-embed-text` (768) as
   the primary embedding model on the normal dispatch path. Chosen for materially better Swedish/
   multilingual retrieval quality on a bilingual SV/EN vault (the specific gap `nomic-embed-text`
   does not close). BGE-M3 requires no query/passage prefix formatting (`docs/EMBEDDINGS.md ::
   Model-specific formatting`).
2. **Fallback:** Google Gemini `gemini-embedding-001` remains the sanctioned secondary, **re-pinned**
   from `output_dimensionality=768` to **`output_dimensionality=1024`** — the same MRL-truncation +
   L2-renormalize mechanism already in use, just requesting the dimension that now matches the new
   primary. All of ADR-0023's fallback discipline is preserved unchanged at the new dimension:
   - **dimension-matched** — `output_dimensionality=1024` to match BGE-M3's native dimension and the
     (future) `EMBED_DIM=1024` guardrail;
   - **normalization-matched** — L2-renormalized to match `EMBED_NORMALIZE`;
   - **mixed-identity but reconcilable (not identity-preserving)** — the fallback write still carries
     the Gemini identity, distinct from the BGE-M3 primary identity even at equal dim; reconcilable via
     `index reconcile` (CTI-2); the query path still always uses the primary identity (CTI-3).
3. **Egress cost:** the Gemini fallback runs on **Google's API**, which offers a **free tier** for
   `gemini-embedding-001`. Re-pinning the requested output dimension does not change the pricing tier
   or introduce new egress cost — fallback egress cost remains negligible, matching the ADR-0023
   baseline.
4. **Mixed-identity / reconcile discipline unchanged.** ADR-0023's CTI-1 (one steady-state identity /
   dim guardrail), CTI-2 (fallback is non-terminal, mixed-identity, reconcilable), and CTI-3 (query
   always uses the primary identity) all carry forward unchanged. Only the pinned dimension changes,
   from 768 to 1024, on both the primary and the fallback side simultaneously — the two must never
   drift apart, or the fallback stops being dimension-matched and becomes a forbidden generic fallback.
5. **Scoped re-supersession.** This ADR supersedes only ADR-0023's **dimension value** (768 → 1024) in
   the fallback pin. It does not reopen or change:
   - the choice of Ollama-primary-with-Gemini-fallback topology,
   - the mixed-identity/reconcile discipline (CTI-1/2/3),
   - the "no generic fallback" invariant's scoped exception shape.

   ADR-0023 remains the authoritative record of *why* a dimension-matched Gemini fallback is sanctioned
   at all; this ADR only re-parameterizes the pinned dimension for the new BGE-M3 primary.

## What this ADR does not do

- **No code change.** `app/components/embeddings/legacy.py :: EmbeddingIdentity`, `app/llm/embeddings.py`, and
  the runtime `EMBED_DIM` / `EMBED_MODEL` defaults are unchanged by this ADR. The actual BGE-M3
  identity migration, `EMBED_DIM` alignment, and full vector-index re-index are implementation work
  tracked by the sibling issue (H4 / #2984), gated on this ADR.
- **No re-index.** Reconciling or rebuilding `store_vector_index` under the new identity happens as
  part of #2984's rollout (dev vault first, then test channel; **prod re-index remains
  operator-ack-gated** per standing rule), not as part of this record.
- **No change to the egress/privacy posture.** The decision that Gemini fallback egress is acceptable
  at all was made by ADR-0023 and is not reopened here.

## Verification (dimension support)

`gemini-embedding-001` supports `output_dimensionality` values below its native 3072 output via MRL
truncation, which the model documentation and existing ADR-0023 implementation already exercise at
768. 1024 is within the same supported truncation range using the identical mechanism (truncate +
L2-renormalize) as the existing 768 pin — no new API capability is required, only a different
requested value of the same parameter. The **implementation slice (H4/#2984) must still confirm this
empirically against the live API** (a single embed call requesting `output_dimensionality=1024` and
asserting the returned vector length and L2 norm) before cutover, per the issue's own verification
requirement; this ADR records the decision and the mechanism precedent, not a live-API transcript.

## When to revisit

Reopen and re-decide (a new ADR) if any of these change:

- The primary embedding model or its native dimension changes again (a third dimension value would
  require a third re-pin).
- `gemini-embedding-001` stops supporting `output_dimensionality=1024` (verify at H4 implementation
  time; if unsupported, fall back to option (b), a fallback-less window, or a different dimension-
  matched secondary provider).
- The system moves to multi-provider load balancing or a steady-state heterogeneous-identity serving
  model, superseding the "one primary + one dimension-matched fallback" shape entirely (see ADR-0023
  "When to revisit").

## Consequences

- BGE-M3 becomes the primary embedding identity at 1024 dims; the Gemini fallback stays available and
  dimension-matched at the new dimension, so the availability bridge ADR-0023 established is not lost
  by the model swap.
- `docs/EMBEDDINGS.md :: Fallback rule` and its "Chosen Gemini model" callout are updated to read
  `output_dimensionality=1024` and cross-reference this ADR alongside ADR-0023.
- The actual runtime identity change (`EmbeddingIdentity.dim`, `EMBED_DIM`, `EMBED_MODEL`, provider
  wiring) and the full re-index are **out of scope here** and tracked by #2984 (H4). No `app/` file is
  touched by this ADR.
- Fallback egress cost is unaffected (still Google's free tier for `gemini-embedding-001`); no new
  cost consideration is introduced by the dimension re-pin.

## References

- #2983 — this ADR's governing issue (`[Retrieval] embedding-fallback-repin-ADR (supersede ADR-0023)`)
- #2980 — parent: Capability Hardening (Cognitive Expansion)
- #2984 — H4, the BGE-M3 identity migration + full re-index implementation slice (consumes this
  ADR's decision; not implemented here)
- `docs/adr/ADR-0023-embedding-egress-gemini-fallback.md` — the ADR partially superseded (dimension
  pin only; topology and mixed-identity/reconcile discipline unchanged)
- `docs/MIMER_CAPABILITY_HARDENING/README.md :: One remaining collision` — the flagged collision this
  ADR resolves
- `docs/MIMER_CAPABILITY_HARDENING/RETRIEVAL_EMBEDDINGS_AND_CONTEXT.md :: §2` — decision 2, options
  (a)/(b), and the practical caveats (EMBED_DIM/DEFAULT_EMBED_DIM drift, mode-formatting,
  EMBED_MAX_INPUT_CHARS) for the H4 implementation slice to address
- `docs/EMBEDDINGS.md :: Fallback rule` — the operational mirror updated alongside this ADR
- `app/components/embeddings/legacy.py :: EmbeddingIdentity` — the runtime identity type H4 will
  update
- `app/llm/embeddings.py` — the provider-aware embedding implementation H4 will update
