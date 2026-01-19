from __future__ import annotations

import contextlib
from typing import Iterable, Sequence

import psycopg
from fastapi import APIRouter, Query, Request

from app.components.retrieval import embed_query
from app.db.dsn import resolve_dsn
from app.observability.tracer import start_span
from app.search.cosine import cosine

router = APIRouter()


def _conn():
    return psycopg.connect(resolve_dsn())


def _coerce_vector(raw: object) -> Sequence[float]:
    if raw is None:
        return ()
    if isinstance(raw, memoryview):
        raw = raw.tobytes().decode("utf-8")
    if isinstance(raw, str):
        stripped = raw.strip("[]{}()")
        if not stripped:
            return ()
        return tuple(float(part) for part in stripped.split(",") if part.strip())
    if isinstance(raw, Iterable):
        return tuple(float(part) for part in raw)
    return ()


def _recent_objects(limit: int = 10) -> list[dict[str, str]]:
    rows: list[tuple[str, str]] = []
    with _conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    select uuid::text, coalesce(payload->>'title','') as title
                    from objects
                    order by created_at desc
                    limit %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
            except psycopg.Error:
                conn.rollback()
                cur.execute(
                    """
                    select uuid::text, coalesce(title, '') as title
                    from objects
                    order by created_at desc
                    limit %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
    return [{"uuid": uuid, "title": title or ""} for uuid, title in rows if uuid]


@router.get("/search")
async def search(request: Request, q: str = Query(...)) -> dict[str, object]:
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("x-trace-id")
    span_cm = start_span("api.search", trace_id, {"path": "/search", "q": q}) if trace_id else contextlib.nullcontext()
    results: list[dict[str, object]] = []
    with span_cm:
        try:
            query_vector, _ = embed_query(q)
        except Exception:
            return {"results": _recent_objects()}

        try:
            with _conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    select e.uuid::text as uuid,
                           coalesce(o.payload->>'title', o.title, '') as title,
                           e.vector
                    from objects_embeddings e
                    join objects o on o.uuid = e.uuid
                    limit 200
                    """
                )
                rows = cur.fetchall()
        except Exception:
            rows = []

        for uuid_value, title, raw_vector in rows:
            vector = _coerce_vector(raw_vector)
            if not vector:
                continue
            score = cosine(query_vector, vector)
            results.append({"uuid": uuid_value, "title": title or "", "score": float(score)})

    if not results:
        return {"results": _recent_objects()}

    results.sort(key=lambda item: item["score"], reverse=True)
    return {"results": results[:10]}
