State: SoT v5.5 baseline (descriptive). This doc describes the current in-process hybrid retrieval + optional rerank hooks.

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
Optional domain scoping:
- `ASK_DOMAIN_SCOPE=<domain>` filters docs to that domain (or bridge domains) when doc payload contains `domain`/`bridge_domains` or when `source_ref` path implies a domain folder.

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

## Delta / Known Limits
- This retrieval store is in-memory; it is not a durable vector DB.
- Rerank defaults to disabled (`RERANK_ENABLE` unset/false).
