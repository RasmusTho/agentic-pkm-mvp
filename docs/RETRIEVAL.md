# RETRIEVAL

## Indexes
- BM25-lite: token-based lexical ranking for fast keyword recall.
- Vector (pgvector): cosine distance over embeddings for semantic matching.
- Hybrid: union or weighted blend of lexical + vector candidates.

## Ingestion → Indexing
1) Chunker produces chunks with (object_id, idx, offset_start, offset_end, text)
2) Indexer:
   - Creates BM25 entries per chunk
   - Computes embeddings for chunk text (deterministic hashing in tests)
   - Upserts into pgvector (embeddings table keyed by object_id)
   - Emits ingest.index.ready and/or curation.review.request

## Query
- Vector query: embed the query text once; top-k by <=> operator.
- BM25 query: ranked by term statistics.
- Hybrid: run both, then merge by score; dedupe by object_id; keep provenance.

## Provenance
- All results carry provenance: object_id, chunk idx, offsets.
- Caller can reconstruct the exact source slice for citation.

## Relevance & Scoring
- BM25 score is lexical; vector score normalized to [0,1] as (1 - distance).
- For hybrid, default is simple re-rank by max(normalized_vector, normalized_bm25). Adjustable via settings.

## Operational Notes
- Embedding model is configured via EMBED_MODEL; in tests a hashing-based embedding is used.
- pgvector extension must be installed; migrations create necessary tables and indexes.
- Deterministic chunking ensures stable index keys across runs.
