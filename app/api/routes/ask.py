from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, model_validator

from app.observability.status_service import record_ask_query
from app.retrieval.hybrid import hybrid_search
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.stores import get_object_store

_HYBRID_WARMED = False


def _ensure_hybrid_store_loaded() -> None:
    global _HYBRID_WARMED
    hybrid = get_hybrid_store()
    if hybrid.all():
        _HYBRID_WARMED = True
        return

    store = get_object_store()
    docs_added = 0

    # Memory store path
    try:
        objs = getattr(store, "_objects", {})
        if isinstance(objs, dict) and objs:
            for oid, rec in objs.items():
                payload = rec.get("payload") or {}
                text = payload.get("text") or payload.get("content")
                if not text:
                    continue
                hybrid.add_document(doc_id=str(oid), text=str(text), source_ref=rec.get("source_ref"))
                docs_added += 1
    except Exception:
        pass

    # PG store path
    try:
        from app.stores.pg import PgObjectStore, _connect  # type: ignore
    except Exception:
        PgObjectStore = None  # type: ignore
        _connect = None  # type: ignore

    if PgObjectStore is not None and isinstance(store, PgObjectStore) and _connect is not None:
        try:
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT object_id, payload, source_ref FROM store_objects")
                    rows = cur.fetchall()
            for row in rows:
                payload = row.get("payload") or {}
                text = payload.get("text") or payload.get("content")
                if not text:
                    continue
                hybrid.add_document(
                    doc_id=str(row.get("object_id")),
                    text=str(text),
                    source_ref=row.get("source_ref"),
                )
                docs_added += 1
        except Exception:
            pass

    if docs_added > 0:
        _HYBRID_WARMED = True

router = APIRouter()


class AskRequest(BaseModel):
    question: str
    zone_strategy: str | None = "default"

    @model_validator(mode="before")
    @classmethod
    def allow_query_alias(cls, data):
        if isinstance(data, dict) and "question" not in data and "query" in data:
            data = {**data, "question": data.get("query")}
        return data


class AskSource(BaseModel):
    uuid: str
    title: str
    origin: str
    zone: str | None = None
    path: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[AskSource]
    latency_ms: int


def _to_source(hit: dict[str, Any]) -> AskSource:
    payload = hit.get("payload") or {}
    origin = str(payload.get("origin") or "vault")
    path = hit.get("source_ref") or payload.get("source_ref")
    title = payload.get("title") or hit.get("title") or ""
    return AskSource(
        uuid=str(hit.get("id") or hit.get("doc_id") or payload.get("uuid") or ""),
        title=str(title),
        origin=origin,
        zone=None,
        path=str(path) if path else None,
    )


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    if not _HYBRID_WARMED:
        _ensure_hybrid_store_loaded()
    start = time.perf_counter()
    hits = hybrid_search(req.question, k=4)
    if hits:
        answer_text = hits[0].get("snippet") or hits[0].get("text") or ""
    else:
        answer_text = "No results found."
    latency_ms = int((time.perf_counter() - start) * 1000)
    record_ask_query(float(latency_ms))
    sources = [_to_source(hit) for hit in hits]
    return AskResponse(answer=answer_text, sources=sources, latency_ms=latency_ms)


__all__ = ["router", "AskRequest", "AskResponse"]
