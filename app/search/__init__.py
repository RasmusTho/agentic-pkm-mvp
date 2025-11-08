from __future__ import annotations

# Publik yta (håll den smal & stabil)
from .service import (
    hybrid_search,
    bm25_search,
    vector_search,
    search,
    get_vector_index,
    get_bm25_index,
    ingest_object,
    # Legacy alias
    search_hybrid,
    search_vector,
)

__all__ = [
    "hybrid_search","bm25_search","vector_search","search",
    "get_vector_index","get_bm25_index","ingest_object",
    "search_hybrid","search_vector",
]
