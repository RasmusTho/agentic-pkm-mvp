State: SoT v4.10 Reality-MVP (current).
# Retrieval (Hybrid + optional rerank)

Reality-MVP uses a hybrid search pipeline over the in-process HybridStore (ObjectStore + VectorIndex). Rerank is optional and disabled by default in smoke/CI.

## Flow
`BM25 (lexical) ∪ embeddings` → merge/normalize scores → optional rerank → truncate to `top_k` (controlled by ask settings / rerank top_k).

## Parameters & defaults
- Embeddings: `EMBED_MODEL` (default `nomic-embed-text` via Ollama; tests use deterministic hash embedding).
- Rerank: gated by `RERANK_ENABLE` + `RERANK_PROVIDER` (`none|mock|ce_local|ce_http`). Default is off (`none`).
- Rerank invariants: only reorders returned hits; does not drop items.
- HybridStore warm-load: `/api/ask` warms from `store_objects` on first request; CLI ingest populates both stores directly.

## Output shape
```json
[
  {
    "doc_id": "uuid",
    "score": 0.62,
    "source_ref": "vault/path",
    "snippet": "...",
    "payload": {"title": "...", "origin": "vault", "zone": null, "trust": "provisional"}
  }
]
```
ASK transforms these hits into `AskSource` entries with `uuid`, `title`, `origin`, `zone?`, `path?`.

## Evidence thresholds
- Reality-MVP does not enforce a hard “insufficient evidence” threshold in `/api/ask`; the ASK graph returns top-hit snippets when LLM reasoning is disabled. Rerank/score thresholds can be added in future versions.
