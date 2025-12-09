from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from pydantic import AliasChoices, BaseModel, Field

from app.agents.ask.graph import run_ask_graph
from app.agents.ask.utils import get_ask_settings
from app.observability.status_service import record_ask_query
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.stores import get_object_store

_HYBRID_WARMED = False


def _load_pg_documents(store, hybrid, seen: set[str]) -> int:
    try:
        from app.stores.pg import PgObjectStore, _connect  # type: ignore
    except Exception:
        return 0

    if not isinstance(store, PgObjectStore):
        return 0

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT object_id, payload, source_ref FROM store_objects")
                rows = cur.fetchall()
    except Exception:
        return 0

    docs_added = 0
    for row in rows or []:
        payload = row.get("payload") or {}
        text = payload.get("text") or payload.get("content")
        if not text:
            continue
        doc_id = str(row.get("object_id"))
        if doc_id in seen:
            continue
        hybrid.add_document(doc_id=doc_id, text=str(text), source_ref=row.get("source_ref"), payload=payload)
        seen.add(doc_id)
        docs_added += 1
    return docs_added


def _ensure_hybrid_store_loaded() -> None:
    global _HYBRID_WARMED
    hybrid = get_hybrid_store()
    if hybrid.all():
        _HYBRID_WARMED = True
        return

    store = get_object_store()
    docs_added = 0
    seen: set[str] = set()

    # Memory store path
    try:
        objs = getattr(store, "_objects", {})
        if isinstance(objs, dict) and objs:
            for oid, rec in objs.items():
                payload = rec.get("payload") or {}
                text = payload.get("text") or payload.get("content")
                if not text:
                    continue
                doc_id = str(oid)
                hybrid.add_document(
                    doc_id=doc_id,
                    text=str(text),
                    source_ref=rec.get("source_ref"),
                    payload=payload,
                )
                seen.add(doc_id)
                docs_added += 1
    except Exception:
        pass

    docs_added += _load_pg_documents(store, hybrid, seen)
    if docs_added > 0:
        _HYBRID_WARMED = True

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(validation_alias=AliasChoices("question", "query"))
    zone_strategy: str | None = "default"


class AskSource(BaseModel):
    uuid: str
    title: str
    origin: str
    plane: str
    zone: str | None = None
    path: str | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[AskSource]
    latency_ms: int


def _to_source(hit: Any) -> AskSource:
    raw: dict[str, Any]
    if hasattr(hit, "model_dump"):
        raw = hit.model_dump()
    elif isinstance(hit, dict):
        raw = hit
    else:
        raw = {}
    payload = raw.get("payload") or {}
    origin = str(payload.get("origin") or "vault")
    plane = str(payload.get("plane") or origin)
    path = raw.get("source_ref") or payload.get("source_ref") or raw.get("path")
    title = payload.get("title") or raw.get("title") or ""
    raw_zone = payload.get("zone") or raw.get("zone")
    zone = str(raw_zone) if raw_zone not in (None, "") else None
    return AskSource(
        uuid=str(raw.get("id") or raw.get("doc_id") or raw.get("object_id") or payload.get("uuid") or ""),
        title=str(title),
        origin=origin,
        plane=plane,
        zone=zone,
        path=str(path) if path else None,
    )


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    if not _HYBRID_WARMED:
        _ensure_hybrid_store_loaded()
    start = time.perf_counter()
    ask_settings = get_ask_settings()
    state = run_ask_graph(req.question, ask_settings=ask_settings)
    answer_text = state.answer or "No results found."
    top_hits = state.hits
    latency_ms = int((time.perf_counter() - start) * 1000)
    record_ask_query(float(latency_ms))
    sources = [_to_source(hit) for hit in top_hits]
    return AskResponse(answer=answer_text, sources=sources, latency_ms=latency_ms)


__all__ = ["router", "AskRequest", "AskResponse"]
