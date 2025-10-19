from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_api_key
from app.schemas.search import SearchHit, SearchRequest, SearchResponse
from app.search.service import search_full_text, search_hybrid, search_vector

router = APIRouter(
    prefix="/search",
    tags=["search"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=SearchResponse)
def search(payload: SearchRequest) -> SearchResponse:
    query_text = payload.query_text.strip() if payload.query_text else None
    query_embedding = payload.query_embedding
    if query_embedding is not None and len(query_embedding) == 0:
        raise HTTPException(
            status_code=400,
            detail="query_embedding must contain at least one value.",
        )
    if not query_text and not query_embedding:
        raise HTTPException(status_code=400, detail="Provide query_text and/or query_embedding.")

    k = payload.k
    results = []
    if query_text and query_embedding:
        results = search_hybrid(query_text, query_embedding, k=k)
    elif query_embedding:
        results = search_vector(query_embedding, k=k)
    elif query_text:
        results = search_full_text(query_text, k=k)

    hits = [
        SearchHit(object_id=res.object_id, score=res.score, payload=res.payload)
        for res in results
    ]
    return SearchResponse(hits=hits)
