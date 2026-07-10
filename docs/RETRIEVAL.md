State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Current retrieval and optional rerank behavior for the runtime; retrieval semantics may evolve, but this doc should reflect the actual active path.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

## v6 Reading Boundary

`docs/plans/V60_ARCHITECTURE_TARGET.md` treats retrieval as a future reusable capability inside a
baseline-aware target operating model. This document still describes the current path.

For v6 planning, read current retrieval migration in stages:
- current-state bug fixes first: make missing scope/domain behavior conservative and avoid path as
  silent semantic authority;
- enabling work next: the runtime now has a small typed retrieval capability wrapper around current
  hybrid search plus optional provenance, relation, and view-freshness diagnostics. These inputs are
  metadata plumbing only; they do not change ranking, filtering, or default authority.
- capability seams delivered: retrieval now exposes an explicit typed contract (RetrievalRequest/RetrievalResponse with provenance and temporal-validity metadata per #573); orientation and resurfacing are delivered as minimal read-only runtime seams consuming derived signals only (`app/orientation/runtime.py`, `app/resurfacing/runtime.py` per #576/#577); derived salience/staleness signals are available as opt-in metadata per #571. These are accepted capability boundaries per the FINDING_AND_REORIENTING contracts (#392); no durable salience field is stored. Relation-aware ranking, full interaction-surface integration, and resurfacing-triggered mutations remain future work.

# Retrieval (Current Reality)

The default retrieval path is an in-process memory store (`app/retrieval/hybrid.py`) that combines:
- BM25 scores (lexical)
- embedding cosine similarity (semantic)
- a small token-overlap bonus

The final list can be optionally re-ranked via the rerank hook adapter.

Interpretation note:
- retrieval operates over runtime documents/projections, not directly over the full ontology of
  human artifacts.
- a retrieval hit is therefore a derived retrieval projection pointing back to an artifact that may
  currently be playing a source role.
- attentional salience may influence ranking or resurfacing logic, but retrieval itself is not the
  whole semantics of attentional relevance.

## Hybrid Search (Current)
Entry point: `app/retrieval/hybrid.py:hybrid_search(query, k=8, ...)`

Capability wrapper: `app/retrieval/capability.py:retrieve(RetrievalRequest)` exposes the same
current hybrid path through typed request/response objects. ASK now consumes this capability seam,
and other surfaces can call the same contract without depending on ASK internals. The wrapper carries
query, scope/domain inputs, trace id, hit metadata, response `metadata.provenance`, response
`metadata.temporal_validity` flags, and optional diagnostics for relation/provenance inputs, view
freshness, or an opt-in salience/staleness signal payload seam. It adapts the current results; it
does not introduce relation-aware ranking, orientation, resurfacing, or a new retrieval agent.

### Scoring
Per document, we compute:
- `bm25_norm` = normalized BM25 score
- `emb_norm` = normalized embedding similarity score
- `overlap_bonus` = fraction of query tokens present in doc tokens

Current weights (weighted linear fusion):
- `combined = 0.5*bm25_norm + 0.4*emb_norm + 0.1*overlap_bonus`

This weighted linear fusion is the ratified current topology (see
`docs/adr/ADR-0024-retrieval-topology.md`). The weights are an intentional first-pass **trust
encoding** — exact lexical match (BM25) weighted above fuzzy semantic match (embeddings), with a
small overlap bonus — not an arbitrary tuning artifact.

**Tuning config surface (ADR-0059 D3, #3404):** the fusion weights above, and the rerank gate
described in *Optional Rerank*, are no longer literals/inline env reads — they come from a single
typed `RetrievalTuning` config (`app/settings/models.py::RetrievalTuning`), settings-backed like
`EmbeddingProfiles`, resolved once per process (never a per-query `os.getenv`) by
`app.retrieval.tuning.get_retrieval_tuning()`. `app/retrieval/hybrid.py::_rank_eligible` reads
`linear_weights` from it instead of the literal; `app/retrieval/hook_adapter.py` and
`app/retrieval/hybrid_rerank_hook.py` read the `rerank`/`rerank_top_k` gate from it. With no
override set anywhere, every field reproduces today's behavior exactly (parity-tested:
`tests/retrieval/test_retrieval_tuning_config.py::test_default_config_ranking_parity`).

Fields and defaults:
- `fusion`: `linear` (default; the formula above) | `rrf` (**reserved, not implemented** — selecting
  it raises `RetrievalStrategyNotImplementedError` at resolution rather than silently falling back;
  ships behind ADR-0059 D3 step 5 / issue #3407, eval-gated)
- `linear_weights`: `{bm25: 0.5, embedding: 0.4, overlap: 0.1}` — today's trust encoding, now visible
  config; override via `RETRIEVAL_LINEAR_WEIGHTS="bm25,embedding,overlap"` (e.g. `"0.5,0.4,0.1"`)
- `rrf_k`: `60` (reserved; dormant until `fusion="rrf"` ships)
- `rrf_signal_weights`: `{lexical: 1.0, dense: 0.8}` — reserved per-signal multipliers on
  `1/(k+rank)`, `lexical >= dense` by default so the trust hierarchy survives a future strategy swap
  (dormant until `fusion="rrf"` ships)
- `retrieve_depth`: `500` — **dormant by construction today.** The in-memory cache is full-corpus
  (every document is already scored regardless of this value); the field exists now so the config
  shape does not churn later if/when an ANN backend or a non-full-corpus cache makes it meaningful.
  Documented as dormant, not silently ignored.
- `rerank`: `off` (default, today's behavior) | `always` (reranks every result through the existing
  optional rerank hook) | `conditional` (**reserved, not implemented** — a deterministic score-margin
  gate, not a keyword classifier; selecting it raises `RetrievalStrategyNotImplementedError`; ships
  behind ADR-0059 D3 step 5 / issue #3407)
- `rerank_top_k`: `100`
- `rerank_score_margin`: `0.2` — reserved conditional-gate threshold, dormant until
  `rerank="conditional"` ships

Env overrides (resolved once at process start, not per query): `RETRIEVAL_FUSION`,
`RETRIEVAL_LINEAR_WEIGHTS`, `RETRIEVAL_RRF_K`, `RETRIEVAL_RRF_SIGNAL_WEIGHTS`,
`RETRIEVAL_RETRIEVE_DEPTH`, `RETRIEVAL_RERANK`, `RETRIEVAL_RERANK_TOP_K`,
`RETRIEVAL_RERANK_SCORE_MARGIN`. A junk override value fails loud (raises) rather than silently
reverting to the default. The existing `RERANK_ENABLE`/`RERANK_TOP_K`/`RERANK_PROVIDER` env vars
keep working as overrides into this surface (compat): `RERANK_ENABLE` truthy maps to `rerank="always"`
when the new `RETRIEVAL_RERANK` knob is unset; `RERANK_TOP_K` maps to `rerank_top_k` when
`RETRIEVAL_RERANK_TOP_K` is unset; `RERANK_PROVIDER` is unrelated to this config shape and continues
to select the reranker implementation directly (`app/retrieval/rerank/provider.py`).

**Live serving path — durable index via a cache-through (KERNEL-05, #2870; G1res-1, #2981):** the
served source of truth is the durable Postgres/pgvector index (`PgVectorIndex` /
`store_vector_index`). The in-process memory store (`MemoryHybridStore` in `app/retrieval/hybrid.py`)
is a **cache-through** of that durable index, not an independently written truth —
`rebuild_from_durable_index()` (`app/retrieval/hybrid.py:268-309`) is the only production path
allowed to populate it, and it is warmed once at API startup (`_warm_retrieval_cache()` in
`app/api/app.py:177-193`, called from `lifespan`) so every retrieval entrypoint
(`app/retrieval/hybrid.py:hybrid_search`/`scoped_hybrid_search`, consumed through the typed
`app/retrieval/capability.py` wrapper) shares the same warmed cache. Freshness is bounded, not
per-query-live: `scoped_hybrid_search` revalidates the cache against a cheap durable
store-generation token (`PgVectorIndex.generation()`, `app/stores/pg.py`) at most once per a
configurable minimum interval (`_revalidate_cache_generation()`, `app/retrieval/hybrid.py:235-261`;
default/floor 1s via `RETRIEVAL_GENERATION_MIN_CHECK_INTERVAL_S`), and forces a full rebuild on a
generation mismatch — so a committed upsert/purge becomes visible without a process restart, bounded
by that check interval rather than being instantly live. **The token is identity-aware
(ADR-0059 D2, #3403):** it is `identity_hash:count:max(updated_at)`, where `identity_hash` is a
short stable hash of `vector_index_meta.identity_json` (empty-string component when no identity row
exists) — every `VectorIndex` implementation (`PgVectorIndex`, `MemoryVectorIndex`) computes it via
the shared `app/stores/base.py::identity_generation_component` helper. This closes a gap the
row-count/`max(updated_at)` token alone left open: an ADR-0052 repin that rewrites the stored
embedding identity WITHOUT rewriting any `store_vector_index` row now still moves the token and
forces a rebuild, instead of silently continuing to serve stale-identity vectors across a repin.
`_revalidate_cache_generation()` itself is unchanged — it only ever compares the token as an opaque
string. This closes the durable-spine direction ADR-0024
recorded and the once-per-process staleness gap that remained after KERNEL-05; see ADR-0024's
2026-07-05 status annotation for what is now superseded. Remaining scope under the RAG/memory
decomposition epic (#2314) is retrieval-quality work (RRF/HyDE/low-trust-weights/eval, next
paragraph), not the serving-path migration, which is delivered. Default retrieval is
metadata-filtered hybrid with **rerank off by default** (`RERANK_ENABLE` unset/false; see *Optional
Rerank*).

**Named future work (not current behavior):** RRF (Reciprocal Rank Fusion) over the weighted linear
sum is no longer an undecided placeholder — `docs/adr/ADR-0059-unified-retrieval-path-pgvector-read-authority.md`
(Accepted, owner-ratified 2026-07-10) is the ADR-0024-anticipated "new ADR" that adopts it as a
selectable, config-gated strategy (`RetrievalTuning.fusion="rrf"`, see above); it ships dark (config
accepts the value, resolution raises not-implemented) until ADR-0059 D3 step 5 / issue #3407 plus an
eval-gated owner call flips the default. HyDE / query expansion and provenance-aware / low-trust
signal weights remain undecided future work, deferred behind the future `SearchPort` boundary
(`docs/ROADMAP.md :: Abstraction Layer Hardening`); adopting either is still a new decision. None of
this changes the current scoring above. One related decision is already taken but not yet enacted:
Episode-closure decay — a derived, post-fusion rank multiplier per
`docs/adr/ADR-0058-event-horizon-closure-decay.md` (Accepted 2026-07-10), landing via ERE-06
(#3181); until that slice merges it is not current scoring behavior.

### Scope filter
Optional operational-scope filtering:
- the current runtime uses `ASK_DOMAIN_SCOPE` and `bridge_domains` as compatibility labels for a
  narrower scope filter and explicit inclusion mechanism
- matching may use document payload markers such as `domain` / `bridge_domains`
- path- or `source_ref`-derived hints are runtime heuristics for current scope handling, not the
  full semantics of human context or artifact meaning
- the broader semantic replacement lives upstream in:
  - `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
  - `docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md`
  - `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
  - `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
  - `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`

## Optional Rerank (Current)
Rerank is opt-in, gated by the `RetrievalTuning.rerank` field (see *Scoring* above; `off` by
default). It is still controlled by env vars, same effective knobs as before (ADR-0059 D3, #3404 —
compat preserved):
- `RERANK_ENABLE=1` to enable reordering (maps to `rerank="always"`)
- `RERANK_TOP_K` to limit how many results the reranker returns explicitly (maps to `rerank_top_k`)
- `RERANK_PROVIDER` selects the implementation (`none`, `mock`, `ce_local`, `ce_http`) — unrelated to
  the `RetrievalTuning` shape, read directly by `app/retrieval/rerank/provider.py`
- `rerank="conditional"` (deterministic score-margin gate) is reserved, not implemented yet — see
  *Scoring* above

Implementation lives under `app/retrieval/rerank/` and is applied via `app/retrieval/hook_adapter.py`
and `app/retrieval/hybrid_rerank_hook.py`, both of which resolve the gate through
`app.retrieval.tuning.get_retrieval_tuning()`.

## Output Shape
`hybrid_search` returns a list of dicts like:
```json
[
  {
    "doc_id": "…",
    "snippet": "…",
    "score": 0.62,
    "source_ref": "…",
    "payload": {}
  }
]
```

Interpretation:
- `doc_id` identifies the retrieval document/projection used in scoring.
- `source_ref` points back to the runtime-known location of the artifact or retained material.
- `payload` is retrieval metadata, not the canonical meaning of the artifact.

## Delta / Known Limits
- This retrieval store is in-memory; it is not a durable vector DB.
- Rerank defaults to disabled (`RERANK_ENABLE` unset/false).
- Relation/provenance inputs and view-freshness diagnostics are carried as optional metadata only.
  They do not affect result ordering or filtering in the current slice.
- Salience/staleness signal payload is capability-level metadata only and is included only when
  callers explicitly opt in (`include_signal_payload=True`). Retrieval does not derive these signals
  from persisted artifact payload or state-axis labels.
- Stale/partial/unknown view reporting is runtime honesty from existing status signals. It is not a
  multi-replica freshness guarantee and does not fail retrieval by itself.
- Query-independent resurfacing now has a separate read-only runtime seam
  (`app/resurfacing/runtime.py`) that derives relevance-change candidates from runtime status signals
  and emits operator-visible receipt/status summaries with explicit "why now" signal provenance.
  It does not write artifact state and does not run on the active retrieval query path.
