State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Current retrieval and optional rerank behavior for the runtime; retrieval semantics may evolve, but this doc should reflect the actual active path.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Retrieval (Current Reality)

The default retrieval path is an in-process memory store (`app/retrieval/hybrid.py`) that combines:
- BM25 scores (lexical)
- embedding cosine similarity (semantic)
- a small token-overlap bonus

The final list can be optionally re-ranked via the rerank hook adapter.

Interpretation note:
- retrieval operates over runtime documents/projections, not directly over the full ontology of
  human artifacts.
- a retrieval hit is therefore a derived retrieval object pointing back to a source artifact or
  vault-note projection.

## Hybrid Search (Current)
Entry point: `app/retrieval/hybrid.py:hybrid_search(query, k=8, ...)`

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
- `source_ref` points back to the source location known to the runtime.
- `payload` is retrieval metadata, not the canonical meaning of the artifact.

## Delta / Known Limits
- This retrieval store is in-memory; it is not a durable vector DB.
- Rerank defaults to disabled (`RERANK_ENABLE` unset/false).
