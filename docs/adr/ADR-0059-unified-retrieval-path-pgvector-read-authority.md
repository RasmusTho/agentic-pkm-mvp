State: Accepted (owner-ratified 2026-07-10). Completes the unified retrieval path: the durable Postgres vector index becomes the read authority for stored vectors (previously its vectors were written but discarded at rebuild), the in-memory store stays a warm cache with identity-aware invalidation, and fusion/rerank tuning (RRF k=60, retrieve-depth, conditional rerank) becomes selectable config. Supersedes-in-part ADR-0024 §"Future work" — per ADR-0024's own terms, adopting a fusion strategy requires a new ADR; this is that record. Migration steps 1–5 are approved for delivery; any ranking-default flip stays gated on eval evidence plus an owner call; step 6 (real pgvector extension) stays deferred and un-scheduled. This ADR is docs/decision-only — implementation ships via the sibling slice issues.
Doc role: Decision record (ADR)
Authority: Authoritative for the unified-retrieval-path target design, invalidation triggers, tuning-config posture, and migration order. ADR-0024 (as annotated) remains the record of the prior topology; ADR-0039 and ADR-0052 are unchanged. `docs/RETRIEVAL.md` remains the live-behavior contract and is updated by the implementation slices, not by this ADR.
Owner: Architecture / Retrieval posture
Temporal class: Durable decision once accepted (supersede via a new ADR, do not edit in place)
Source of truth: This ADR for the target-design decision; `docs/RETRIEVAL.md` for live behavior; `app/retrieval/hybrid.py` + `app/stores/pg.py` for the executing code.

# ADR-0059: Unified retrieval path — durable index as vector read authority, warm cache with identity-aware invalidation, tunable fusion

**Date:** 2026-07-10
**Status:** Accepted (owner-ratified 2026-07-10)

---

## Context

### What is already delivered (corrects the audit's G1 framing)

The Fable-5 field-scan audit (`docs/research/yggdrasil-fable5-audit.md`, Draft 2026-07-05) describes
G1 as "durable retrieval is built-but-dormant — the pgvector index is written at ingest but never
read at query time." **That description is stale.** As of KERNEL-05 (#2870) and G1res-1 (#2981,
PR #3003), verified against the code on 2026-07-10:

- `rebuild_from_durable_index()` (`app/retrieval/hybrid.py:268`) is the only production path allowed
  to populate the in-process `MemoryHybridStore`, warmed at API lifespan start
  (`_warm_retrieval_cache()`, `app/api/app.py`).
- The serving path revalidates the cache against a cheap durable store-generation token
  (`PgVectorIndex.generation()` = `count(*):max(updated_at)`, `app/stores/pg.py:634`) at most once
  per configurable interval (floor 1 s) and forces a full rebuild on mismatch
  (`_revalidate_cache_generation()`, `app/retrieval/hybrid.py:235`).
- ADR-0024 carries a 2026-07-05 superseded-in-part annotation recording exactly this.

So "durable index as serving source of truth, in-memory as cache-through" is **largely shipped**.
What remains is narrower — and one part of it is worse than the audit noticed.

### What is actually still broken (verified 2026-07-10)

**R1 — The durable vectors are read and then thrown away.** `PgVectorIndex.all_rows()`
(`app/stores/pg.py:656`) returns each row's stored `embedding`, but `rebuild_from_durable_index()`
drops that field when building cache documents, and `MemoryHybridStore._ensure_indexes()`
(`app/retrieval/hybrid.py:156`) then **re-embeds the entire corpus** via `embed_docs()` on the first
query after every rebuild. Consequences:

1. Every generation mismatch (any committed upsert/purge) triggers a full-corpus re-embed — cost and
   latency that scale linearly with vault size, on the **read** path.
2. If the primary embedder (Ollama) is degraded at that moment, the sanctioned Gemini fallback can
   fire **from a query**, i.e. read-path egress. ADR-0023/ADR-0052 sanctioned the fallback as a
   write-path availability bridge; the read path re-creating embeddings was never part of that
   posture.
3. The cache silently re-stamps every document with the *current runtime identity*, diverging from
   the per-row identities the durable index records under CTI-1/2/3. During an ADR-0052 repin window
   the cache and the durable index can score with different vector spaces without any signal.
4. The durable vectors themselves remain effectively write-only — the audit's G1 instinct was right
   about the vectors even though the serving-path claim was stale.

**R2 — Invalidation does not cover embedding identity.** The generation token changes on
upsert/purge (and therefore on re-index, which rewrites rows), but a repin of
`vector_index_meta.identity_json` **without** row rewrites does not change it. Today this is masked
by R1 (the cache re-embeds with the current identity anyway); the moment R1 is fixed, identity must
become part of the invalidation token or a repin would serve stale-space vectors.

**R3 — "pgvector" is not pgvector.** `store_vector_index.embedding` is `DOUBLE PRECISION[]`
(`app/stores/pg.py:97-107`); `PgVectorIndex.search()` is a full-table scan with a Python dot product.
No `vector` type, no ANN index. Harmless at current corpus size (the serving cache holds the full
corpus anyway), but the name in docs/audit overstates what exists. The extension upgrade is kept as
an isolated, optional, *later* step in this design — not a prerequisite for anything else.

**R4 / G5 — Fusion and rerank tuning are hardcoded and scattered.** The trust-weighted linear fusion
`0.5·bm25 + 0.4·emb + 0.1·overlap` is a literal at `app/retrieval/hybrid.py:498`. Rerank is
controlled by three env vars read at call time (`RERANK_ENABLE/RERANK_TOP_K/RERANK_PROVIDER` in
`app/retrieval/hook_adapter.py` and `app/retrieval/rerank/provider.py`). There is no RRF, no
retrieve-depth knob, no conditional-rerank gate, and no single config surface. ADR-0024 explicitly
defers RRF/tuning and requires a new ADR to adopt any of it.

### Relationship to the moat ruling (Prompt 1) — resolved for this ADR's scope

The audit is still **Draft**; the broader G1/G5 rulings it requests are not on record. G1's
serving-path half was enacted ahead of any ruling (#2870/#2981/#2982). On **2026-07-10 the owner
ruled this ADR's scope directly**: deliver both the repair (steps 1–3) and the tuning-as-config work
(steps 4–5), judged orthogonal to other planned work — so steps 4–5 are not blocked on the wider
moat ruling. The G5 posture adopted here is "field defaults as tunable config, not as flipped
defaults": any ranking-default flip remains gated on eval evidence plus an explicit owner call.

## Decision (proposed)

**Complete the unified retrieval path: the durable vector index becomes the read authority for
stored vectors (not just texts); the in-memory store stays a warm full-corpus cache with explicit,
identity-aware invalidation; embedding happens only on the write path (plus live query embedding);
and fusion/rerank tuning becomes one typed, selectable config surface with today's behavior as the
default.**

### D1 — Vector read authority: cache loads stored vectors, read path never embeds documents

`rebuild_from_durable_index()` consumes `all_rows()` **including** `embedding`;
`MemoryHybridStore` accepts preloaded vectors, and `_ensure_indexes()` computes only
BM25/tokenization. Document embedding on the serving path is removed. The cache becomes a faithful
projection of the durable index — texts, payloads, *and* vectors — instead of a projection of
durable texts re-embedded by whatever identity the process currently holds.

- **Mixed-identity rows (CTI-2 fallback writes) load as-is.** They are dimension-matched and
  L2-renormalized by construction (ADR-0023/ADR-0052), and the durable `PgVectorIndex.search()`
  already scores them together — the cache scoring them together is the *same* semantics, now
  honestly shared between paths. The rebuild counts and logs mixed-identity rows as a reconcile
  signal (surfaced via the index doctor, #2324); it does not re-embed them.
- **Query embedding is unchanged:** embedded live with the primary identity (CTI-3).
- **Test-seeded corpora** (`set_documents()` without vectors) keep the lazy-embed path as an
  explicit fallback for docs lacking vectors — deterministic, and never reachable from
  `rebuild_from_durable_index()` once ingest always writes vectors (it does today).

### D2 — Explicit invalidation triggers, identity included

The generation token becomes `identity_hash:count:max(updated_at)` (hash of
`vector_index_meta.identity_json`). The complete trigger list, each mapping to a cache rebuild
within the bounded check interval:

| Trigger | Mechanism | Status |
|---|---|---|
| Ingest upsert / purge | `updated_at`/count moves the token | shipped (#2981) |
| Re-index / reconcile | row rewrites move the token | shipped (implied) |
| Embedding repin (ADR-0052) | **identity hash moves the token** | **new (this ADR)** |
| Operator force | `rebuild_from_durable_index(force=True)` | shipped (smoke/CLI) |

Cold start is unchanged: lifespan warm; an empty durable index yields an empty cache and a running
system (no-vault idle boot, #2005, holds).

### D3 — Fusion and tuning as one typed config surface (G5)

A `RetrievalTuning` config (settings-backed, env-overridable, resolved once per process — not
per-call `os.getenv`) owns:

- `fusion`: `linear` (default) | `rrf`
- `linear_weights`: `(0.5, 0.4, 0.1)` — today's trust encoding, now visible config
- `rrf_k`: 60 (field default; 30–40 for top-1 precision, per the audit's citations)
- `rrf_signal_weights`: per-signal multipliers on `1/(k+rank)` with lexical ≥ dense by default, so
  the **trust hierarchy survives the strategy swap** — weighted RRF, not vanilla RRF
- `retrieve_depth`: ~500/signal — **dormant by construction today** (the full-corpus in-memory cache
  scores everything; this knob becomes meaningful only if/when step 6 introduces ANN or the cache
  stops being full-corpus). Recorded now so the config shape doesn't churn later; documented as
  dormant, not silently ignored.
- `rerank`: `off` (default) | `always` | `conditional`, plus `rerank_top_k` (~100). The conditional
  gate is a **deterministic score signal** (e.g. skip rerank when the top BM25 result dominates by a
  configured margin — exact-match queries are where reranking measurably hurts), not a keyword
  classifier. The existing `RERANK_*` env vars keep working as overrides into this surface.

**Ranking contract preserved:** fusion strategy is internal to `_rank_eligible()`. The scope
prefilter (eligibility before scoring), eligible-only normalization, content-free denials,
evidence-role clamping, rerank containment (`_contain_rerank`), and the result-dict shape with
`score ∈ [0,1]` (RRF scores min-max-normalized before exposure) are all unchanged regardless of
strategy. Default behavior after D3 lands is **byte-identical to today** — RRF and conditional
rerank ship dark until the eval gate (step 5) and an owner call flips anything.

## Constraints honored (invariant check)

1. **Retrieval = candidate, not authority (ADR-0039): untouched.** The evidence-role machinery
   (`_intrinsic_evidence_role`, `_clamp_in_context`, conservative `background` default) is
   orthogonal to storage and fusion; this design changes where candidates come from and how they are
   ordered, never what authority they carry. One wording tension exists and is resolved by scoping:
   the durable index is the **read authority for the retrieval projection** — authoritative about
   "what the index contains," subordinate to markdown-canonical, and never authority about truth.
   The word "authority" in this ADR's title means only that.
2. **Markdown-canonical / index-disposable: strengthened.** The rebuild chain stays one-directional
   (vault → ingest → durable index → cache; `index_rebuild` CLI regenerates the durable index from
   canonical markdown). D1 actually *repairs* a subtle violation: today's cache is not a projection
   of the durable index (its vectors are minted read-side); after D1 it is, byte-for-byte.
3. **Embedding identity under mixed/repin (ADR-0052): strengthened.** Per-row recorded identities
   are carried into the cache instead of being silently overwritten; a repin invalidates the cache
   via the identity-aware token; CTI-1/2/3 discipline is untouched (one steady-state identity,
   reconcilable fallback rows, query always on primary identity). The read path also stops being a
   potential Gemini-egress path, tightening the egress posture rather than loosening it.
4. **Fail-loud store resolution (KERNEL-03/I-S4), migration-owned schema (KERNEL-04), single
   populate path (KERNEL-05/I-D3): unchanged.** Step 6 is the only step touching schema and is
   explicitly Alembic-owned and operator-ack-gated for prod re-index per standing rule.

## Migration (forward-only, each step independently shippable and verifiable)

| # | Step | Reversible? | Verification | Model tier |
|---|---|---|---|---|
| 1 | **Identity-aware generation token** — `generation()` includes a hash of `vector_index_meta.identity_json`; token format change only | Yes (token format; rebuilds are idempotent) | Test: repin identity without row rewrites → cache invalidates within the check interval | Sonnet (mechanical) |
| 2 | **Durable vectors become the cache's vectors** — rebuild passes `all_rows()` embeddings through; `MemoryHybridStore` accepts preloaded vectors; `_ensure_indexes` computes BM25 only; lazy-embed retained solely for vector-less test seeds | Yes (flag-guardable; old path deletable after soak) | **The isolated read-authority step:** assert zero `embed_docs` calls on the serving path; ranking parity vs pre-change on the golden eval; rebuild latency drops to SQL-read + tokenize. Hot-path change → full `not pg` suite + `RUN_INTEGRATED_RUNTIME_UAT=1` | Sonnet (mechanical, but full-suite gated) |
| 3 | **Mixed-identity observability** — rebuild logs/counts CTI-2 rows; index doctor surfaces the count | Yes (additive) | Doctor output on a corpus with fallback rows | Sonnet |
| 4 | **`RetrievalTuning` config surface** — settings + env plumbing for linear weights and rerank gate; defaults byte-identical to today | Yes (defaults = today) | Ranking-parity test: default config reproduces current ordering exactly | Sonnet |
| 5 | **RRF (weighted, k=60) + conditional rerank as selectable strategies** — implemented behind D3 config, validated with the bilingual/golden eval runner (#2319/#2320); default stays `linear` until eval sign-off; any default flip is an owner call recorded against this ADR | Yes (config-selected, dark by default) | Eval: RRF ≥ linear on the bilingual set without degrading the trust hierarchy; conditional gate shows rerank skipped on exact-match queries | Opus/Fable framing + eval judgment; Sonnet for the mechanical strategy code |
| 6 | **(Optional, deferred) Real pgvector** — extension + `vector(dim)` column + HNSW, `search()` pushed into SQL; Alembic migration; prod re-index operator-ack-gated | Forward-only (schema) — isolated behind the `VectorIndex` interface | Only when corpus scale makes full-corpus caching or scan-search untenable; parity test SQL-ANN vs cache ranking on overlap | Opus for migration design; Sonnet execution |

Ordering constraint: 1 before 2 (loading stored vectors without an identity-aware token would serve
stale-space vectors across a repin). 3–4 are independent after 2. 5 requires 4. 6 requires nothing
above but should not precede 2 (no point optimizing a search path the server doesn't read).

## Consequences

- The durable index's vectors go from write-only to the single vector source for serving; rebuilds
  become cheap SQL reads, removing per-rebuild corpus re-embeds and the read-path egress hazard.
- Repin/re-index/reconcile all become explicit, tested invalidation events instead of relying on the
  accident that "the cache re-embeds everything anyway."
- Fusion weights stop being folklore in a code literal; RRF and conditional rerank exist as
  config-selectable strategies with an eval gate, satisfying ADR-0024's "new ADR to adopt" clause
  without flipping any default silently.
- ADR-0024's remaining live content (linear fusion default, rerank-off default) stays true until the
  owner flips a default under step 5's eval evidence.
- docs/RETRIEVAL.md and the audit's G1 row need reconciling to this record when accepted (the audit
  currently describes a pre-#2981 world).

## Decisions recorded (2026-07-10)

1. **D1–D2 (steps 1–3): approved** by the owner — correctness/efficiency repair, delivered
   independent of the wider moat ruling.
2. **D3 as config-not-default (steps 4–5): approved** by the owner, judged orthogonal to other
   planned work. The default flip stays gated on the bilingual eval plus an explicit owner call —
   no silent behavior change.
3. **Conditional-rerank gate shape** (builder-decided under the Agency default): deterministic
   score-margin gate, built and shipped dark until eval evidence exists.
4. **Step 6 timing** (builder-decided): un-scheduled; revisit at ~10k indexed chunks or when
   rebuild/scan latency becomes user-visible.
5. **Terminology** (builder-decided, flagged for objection): "read authority for the retrieval
   projection" — authority about what the index contains, never about truth; subordinate to
   markdown-canonical; ADR-0039's semantics untouched.

## References

- ADR-0024 (retrieval topology; 2026-07-05 superseded-in-part annotation), ADR-0039
  (candidate-not-authority), ADR-0023/ADR-0052 (embedding egress + repin, CTI-1/2/3)
- `docs/RETRIEVAL.md`, `docs/EMBEDDINGS.md`, `docs/research/yggdrasil-fable5-audit.md` (Draft; G1/G5)
- #2314 (epic; Gate0/W1–W3 children closed), #2870/KERNEL-05, #2981/G1res-1, #2984/H4 (bge-m3 cutover)
- `app/retrieval/hybrid.py` (`rebuild_from_durable_index`, `_revalidate_cache_generation`,
  `_rank_eligible`), `app/stores/pg.py` (`PgVectorIndex.generation/all_rows/search`, DDL),
  `app/api/app.py` (`_warm_retrieval_cache`)
