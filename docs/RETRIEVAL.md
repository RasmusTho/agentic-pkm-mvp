State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# 5.5 Retrieval (Hybrid + Rerank)

## Flöde
`BM25 U Embeddings` -> `merge` -> `rerank (cross-encoder/MonoT5)` -> `top_k (5-8)`

## Parametrar
- BM25 stopwords via `language`
- Embeddings-cache: key = content_hash, TTL=infinity (lokalt)
- Tröskel: om top1_score < T -> "otillräcklig evidens"

## Output
```json
[{"doc_id":"...","snippet":"...","score":0.62,"source_ref":"..."}]
```