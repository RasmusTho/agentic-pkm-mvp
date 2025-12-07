State: SoT v4.10 (current; details may lag ARCHITECTURE).
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
