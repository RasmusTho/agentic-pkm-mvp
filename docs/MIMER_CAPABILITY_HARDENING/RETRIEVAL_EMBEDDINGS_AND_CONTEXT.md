State: Specification (design + bounded slices). Advisory until child issues are delivered. Covers the mechanical spine: G1 residual (freshness + doc truth), G3 BGE-M3 migration (owner ruling R2: switch now, no pre-benchmark), G5 fusion/rerank tuning, G6 session hot-cache.
Doc role: Specification (capability design: retrieval spine)
Authority: Owns the G1res/G3/G5/G6 design. Subordinate to ADR-0023/ADR-0024 (and the superseding ADRs it requests), `docs/EMBEDDINGS.md`, `docs/RETRIEVAL.md`, the KERNEL-05 contract (`docs/RUNTIME_CORRECTNESS_KERNEL/RETRIEVAL_READS_DURABLE_INDEX.md`), and the low-trust retrieval invariants.
Owner: Architecture / product (Rasmus)
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed — code citations current; design is proposal
Last reviewed: 2026-07-05

# Retrieval Spine: Freshness, BGE-M3, Fusion Tuning, Hot-Cache (G1res · G3 · G5 · G6)

These four are mechanical relative to the rest of the program, but they are the substrate the
curation and proactivity capabilities read — sequencing discipline matters more than design novelty
here. **Invariant guard over everything in this doc:** nothing changes *eligibility* or *authority* —
the scope prefilter runs before ranking (`app/retrieval/hybrid.py:459-480`), evidence-role clamping
never upgrades (`:39-50`), and rerank containment cannot reintroduce excluded docs (`:483-493`).
Fusion and caching change ordering and cost, never membership.

## 1. G1 residual — freshness + doc truth (the audit's G1 is mostly done)

**Correction to the audit:** KERNEL-05 landed. `MemoryHybridStore` is a cache-through of
`store_vector_index`; `rebuild_from_durable_index()` is the only production population path
(`app/retrieval/hybrid.py:212-247`), invoked at API startup (`app/api/app.py:190-193`) and by the
ASK route (`app/api/routes/ask.py:39`). The residual gap is *liveness*: the rebuild is
once-per-process (`_REBUILT_FROM_DURABLE_INDEX`, `hybrid.py:224-226`), so rows upserted **after**
process warm are invisible to retrieval until restart or explicit `force=True` — acknowledged in
the delete-handler's coherence note (`app/workers/outbox_worker.py`, comment near the purge handler:
cache rebuilt "at process warm / explicit rebuild").

**Contract.** Retrieval freshness bound: after a durable upsert/purge commits, retrieval reflects it
within one generation check — concretely, the serving path revalidates the cache against a cheap
durable **store generation** signal (the SINGLE_STORE_GENERATION seam from the same kernel wave) and
rebuilds when the generation advanced. No per-row incremental patching in slice 1 (the vault is
hundreds of notes; full rebuild is cheap and simpler to prove equivalent — incremental invalidation
is a later optimization *only if* rebuild latency ever hurts, measured not assumed).

**Slices.**
1. **G1res-1 Generation-checked cache revalidation.** Generation captured at rebuild; serving path
   compares against durable generation (bounded staleness window via a min-check interval, e.g.
   ≥1 s, to avoid per-query DB hits); mismatch ⇒ rebuild. `force` and test seams unchanged.
   `Verify:` extend `tests/retrieval/test_retrieval_durable_equivalence.py` with
   `::test_post_upsert_visibility_without_restart`;
   `tests/invariants/…::test_retrieval_serves_durable_truth_fresh`. Deps: none. **Sonnet.**
2. **G1res-2 Doc truth.** `docs/RETRIEVAL.md:66-71` ("not the serving path today") and the
   ADR-0024 forward-direction phrasing are now false — update RETRIEVAL.md to the cache-through
   reality and add a status note to ADR-0024 (docs lane; ADR text itself gets a dated
   "superseded-in-part by KERNEL-05 delivery" annotation per ADR hygiene, not a rewrite).
   `Verify:` doc-audit against origin/main. Deps: G1res-1 merged (describe the end state once).
   **Sonnet, docs lane.**

## 2. G3 — BGE-M3 identity migration (R2: switch now; eval after, not before)

R2 removes the pre-benchmark: switch to BGE-M3, then measure. The migration is an
`EmbeddingIdentity` change (`app/components/embeddings.py:30-35`) — provider stays `ollama`, model
becomes `bge-m3` (Ollama-served, dense output), **dim 768 → 1024**, normalize true. Under
`docs/EMBEDDINGS.md :: Change policy` this forces a full re-index; the mixed-identity/reconcile
discipline (ADR-0023, `index doctor` + `index reconcile`) is the migration rail — this is exactly
the scenario that machinery was built for.

**The collision (README owner decision 2).** ADR-0023's sanctioned fallback is *dimension-matched
at 768* (Gemini `gemini-embedding-001` @`output_dimensionality=768`). At 1024, the pin breaks. The
requested superseding ADR chooses:
- **(a) Re-pin fallback to 1024** — `gemini-embedding-001` supports `output_dimensionality=1024`
  (MRL truncation + L2-renormalize, same mechanism as the current 768 pin). Recommended: preserves
  the availability bridge with the identical discipline. Verify the dim support against the live
  API at implementation time.
- **(b) Fallback-less window** — simpler, but embed outages during the window dead-letter (the
  documented no-key behavior). Acceptable if (a) hits any snag.

**Practical caveats the audit under-weighted:**
- `EMBED_DIM` is a guardrail asserted per vector (`docs/EMBEDDINGS.md:55-69`); the migration flips
  it to 1024 *together with* the identity, and inherits the standing `DEFAULT_EMBED_DIM=1536` code
  drift (#2296/#2297) — the migration slice should close that drift rather than layer a third value
  on top; fold #2297's carry item in.
- BGE-M3 wants query/passage awareness less than E5-family, but the `mode` formatting seam
  (`docs/EMBEDDINGS.md :: Model-specific formatting`) must be explicitly decided (BGE-M3: no prefix
  required) and recorded in the identity notes so it is not re-litigated per call site.
- `EMBED_MAX_INPUT_CHARS=6000` was tuned for nomic's ~2k-token window; BGE-M3 takes 8192 tokens —
  raise the budget in the same slice (fewer chunk-mean-pools ⇒ better long-note vectors; that alone
  may matter as much as the model swap for retrieval quality).
- **BM25-folding into BGE-M3 sparse output is explore-only** (README owner decision 6): Ollama's
  embed API returns dense vectors only; the sparse/multi-vector heads require a FlagEmbedding-class
  serving path — a new runtime dependency, against the harden-don't-rebuild guardrail. Keep BM25
  (with its own Swedish-tokenization gap noted for the eval); revisit only on eval evidence.

**Slices.**
3. **G3-1 Identity migration + full re-index.** New embedding profile (model, dim 1024, no-prefix
   mode, input budget), EMBED_DIM alignment closing #2296/#2297 drift, re-index via the existing
   rebuild path, doctor-verified single identity at completion. Dev vault first; test channel next;
   **prod re-index operator-ack-gated** (standing rule). Runbook = Opus; implementation = Sonnet.
   `Verify:` `tests/index/test_identity_migration.py` (old-identity rows flagged by doctor;
   reconcile converges; query path pins new identity),
   `tests/invariants/…::test_embedding_identity_converges_post_reindex`. Deps: superseding ADR.
4. **G3-2 SV/EN retrieval eval (after migration — decides G5 defaults).** Hand-labelled Niflheim
   query set (SV-only / EN-only / cross-lingual, recall@k + MRR), fusion held fixed, run against
   both identities (nomic snapshot vs BGE-M3) offline. Output: an eval note + the G5 default
   recommendation. This is R2's inversion honored: the eval *validates and tunes*, it no longer
   *gates*. `Verify:` eval fixture set committed under `tests/evals/fixtures/` (extends the existing
   eval-fixture culture); scorecard reproducible. Deps: G3-1. **Sonnet.**

## 3. G5 — fusion option, conditional rerank, tuned sizes

Current: trust-weighted linear fusion `0.5·bm25 + 0.4·emb + 0.1·overlap` (`hybrid.py:433`),
rerank off by default via env hook (`app/retrieval/hook_adapter.py:10`, `docs/RETRIEVAL.md:92-98`).
ADR-0024 ratified linear-as-current and named RRF as future work behind `SearchPort`
(`docs/ROADMAP.md:200-207`).

**Divergence from the roadmap gate, argued:** the SearchPort prerequisite existed to make fusion
swaps safe. The safety properties it was buying are now *directly enforced in the serving path* —
prefilter-before-ranking, role clamping, rerank containment, plus the property-test lane (P-1..P-7)
— so adding a **selectable fusion strategy inside `_rank_eligible`** (linear | rrf) behind config
is a bounded change with the invariants pinned where they run. SearchPort remains desirable for
A/B infrastructure; it is no longer a *blocker* for shipping a config-selectable RRF. This still
requires a small ADR superseding ADR-0024's "linear only" ratification — bundled with the G5 slice.

**Design.**
- `RETRIEVAL_FUSION={linear|rrf}` (compiled setting, env for dev): RRF over the per-mode rankings
  (BM25 rank list, embedding rank list; overlap folds into the lexical rank or drops under RRF —
  decided by the eval), `k=60` starting constant, exposed as config. Trust-weighting remains
  available as the linear option; the *default* flips only on G3-2 evidence (and only if RRF does
  not degrade the trust hierarchy — ADR-0024's own caution, now testable).
- **Conditional rerank:** replace the boolean `RERANK_ENABLE` with a query-shape gate in the hook
  adapter: short keyword-ish queries (≤N tokens, no question words SV/EN) skip rerank; natural-
  language questions rerank top-M. Deterministic, cheap, and honest about the field's "rerank hurts
  simple queries" result. Existing containment assertion unchanged and covering the gate.
- **Sizes:** retrieve-per-mode and rerank-window become named config (`RETRIEVAL_CANDIDATES_PER_MODE`,
  `RERANK_WINDOW`) with defaults set by G3-2 — the field's 500/100 are corpus-scale numbers; a
  hundreds-of-notes vault will land far lower (start 100/25 as safe pre-eval defaults).

**Slice.**
5. **G5-1 Fusion option + conditional rerank + size config (+ ADR).** Code behind config with
   current behavior as default until G3-2 flips it.
   `Verify:` `tests/retrieval/test_fusion_strategies.py` (same eligible set under both fusions —
   property: fusion permutes, never adds/removes; RRF math golden tests),
   `tests/retrieval/test_conditional_rerank_gate.py`,
   `tests/invariants/…::test_fusion_changes_order_never_eligibility`. Deps: code-independent;
   default flip depends on G3-2. **Sonnet.**

## 4. G6 — session hot-cache

The field's `hot.md` primitive, adapted to our authority model: a small, token-cheap
**recent-context set** consulted before full retrieval — recently touched notes, recent moments,
recent panel interactions, active commitments.

**Contract (what keeps it safe and boring):**
- **Derived, rebuildable, non-canonical.** Lives under `runtime/context/hot_cache.json` (machine
  state — NOT a vault note; a `hot.md` in the vault would be a machine-written surface humans might
  edit, creating a phantom authority. The human-visible "what's warm" view is the existing
  `/api/companion/now` surface, not a file). Deleting it costs a cold assembly, never correctness.
- **Population:** append-on-event from existing signals (watcher touches, moment materializations,
  panel executions) with size/age bounds (e.g. 20 entries / 7 days) and content = references +
  short snippets, not full bodies.
- **Consumption:** context assembly (ASK/chat envelope seam) reads hot-cache entries as
  candidates **merged before ranking, subject to the same scope prefilter**, and their in-context
  evidence role is clamped to `background` maximum — recency is salience, not authority. A
  hot-cache hit never bypasses eligibility (this is the one place a cheap cache could quietly
  become a scope leak; the invariant pins it).
- Alignment: this is a first concrete step toward the `ActiveContextSet` direction
  (`docs/contracts/ACTIVE_CONTEXT_SET.md`) — tagged **extends**, and deliberately smaller than that
  contract (no generation semantics, no bindings model).

**Slice.**
6. **G6-1 Hot-cache.** Store + population hooks + envelope-seam consumption + bounds.
   `Verify:` `tests/context/test_hot_cache.py` (bounds; rebuild-from-durable equivalence — cache
   deleted ⇒ same final answers, possibly slower; scope-filtered entry never surfaces),
   `tests/invariants/…::test_hot_cache_derived_never_authority`. Deps: G1res-1 (freshness semantics
   shared). **Sonnet.**

## 5. Fitness invariants (registry candidates)

### retrieval_serves_durable_truth_fresh
- **Purpose:** After a committed durable upsert/purge, retrieval reflects it within the declared
  freshness bound without process restart; the cache can be stale only within that bound.
- **Expected failure mode:** long-lived API process serves day-old retrieval while the index moved.
- **Test path:** `tests/retrieval/test_retrieval_durable_equivalence.py::test_post_upsert_visibility_without_restart`.

### fusion_changes_order_never_eligibility
- **Purpose:** Switching fusion (linear/RRF), toggling rerank, or resizing windows can permute
  result order but never change the eligible set, reintroduce an excluded doc, or upgrade an
  evidence role.
- **Test path:** `tests/invariants/test_retrieval_spine_invariants.py::test_fusion_changes_order_never_eligibility`.

### embedding_identity_converges_post_reindex
- **Purpose:** After the BGE-M3 migration completes, doctor reports exactly one identity; any
  mixed-identity state during the window is loud (doctor error) and reconcilable, never silent.
- **Test path:** `tests/invariants/test_retrieval_spine_invariants.py::test_identity_converges`.

### hot_cache_derived_never_authority
- **Purpose:** Hot-cache content is rebuildable from durable stores, passes the scope prefilter like
  any candidate, and enters context clamped to `background` at most.
- **Expected failure mode:** the cache becomes a side-channel that surfaces out-of-scope or
  role-upgraded material because "it was recent".
- **Test path:** `tests/invariants/test_retrieval_spine_invariants.py::test_hot_cache_never_authority`.
