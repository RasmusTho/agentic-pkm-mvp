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
- target-state change later: separate retrieval, orientation, and resurfacing, with salience and
  relation-aware behavior implemented and accepted before it is described as runtime reality.

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
current hybrid path through typed request/response objects for non-ASK callers. The wrapper carries
query, scope/domain inputs, trace id, hit metadata, and optional diagnostics for relation/provenance
inputs, view freshness, or an opt-in salience/staleness signal payload seam. It adapts the current results; it does not introduce relation-aware
ranking, orientation, resurfacing, or a new retrieval agent.

### Scoring
Per document, we compute:
- `bm25_norm` = normalized BM25 score
- `emb_norm` = normalized embedding similarity score
- `overlap_bonus` = fraction of query tokens present in doc tokens

Current weights:
- `combined = 0.5*bm25_norm + 0.4*emb_norm + 0.1*overlap_bonus`

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
Rerank is opt-in and controlled by env vars:
- `RERANK_ENABLE=1` to enable reordering
- `RERANK_TOP_K` to limit how many results the reranker returns explicitly
- `RERANK_PROVIDER` selects the implementation (`none`, `mock`, `ce_local`, `ce_http`)

Implementation lives under `app/retrieval/rerank/` and is applied via `app/retrieval/hook_adapter.py`.

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
