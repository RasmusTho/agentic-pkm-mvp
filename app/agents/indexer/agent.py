from __future__ import annotations
import os, json, uuid
from typing import Any, Sequence
import psycopg
from psycopg.rows import dict_row
from app.search.embeddings import embed_text
from app.memory.store import remember, recall

def _dsn() -> str:
    url = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return url.replace("postgresql+psycopg://","postgresql://")

def _chunks(object_id: str) -> list[dict]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, idx, text FROM chunks WHERE object_id=%s ORDER BY idx ASC", (object_id,))
        return list(cur.fetchall())

def _write_embedding(embed_id: str, object_id: str, model: str, vec: Sequence[float]) -> None:
    dim = len(vec)
    vec_lit = "[" + ",".join(f"{v:.10f}" for v in vec) + "]"
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO embeddings (id, object_id, model, dim, vec) VALUES (%s,%s,%s,%s,%s::vector) ON CONFLICT (id) DO UPDATE SET object_id=EXCLUDED.object_id, model=EXCLUDED.model, dim=EXCLUDED.dim, vec=EXCLUDED.vec",
            (embed_id, object_id, model, dim, vec_lit),
        )

def _audit(object_id: str | None, agent: str, action: str, trace_id: str | None, details: dict | None) -> None:
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit(id, object_id, agent, action, ts, trace_id, details) VALUES (%s,%s,%s,%s, now(), %s, %s::jsonb)",
            (str(uuid.uuid4()), object_id, agent, action, trace_id, json.dumps(details or {})),
        )

def index_object(object_id: str, *, model: str, trace_id: str) -> dict[str, Any]:
    recall("indexer", "embedding_stats", object_id=object_id, limit=3)
    cs = _chunks(object_id)
    if not cs:
        _audit(object_id, "indexer", "no_chunks", trace_id, {})
        return {"embeddings": 0}
    n = 0
    for c in cs:
        e = embed_text(c["text"])
        _write_embedding(str(uuid.uuid4()), object_id, model, e)
        n += 1
    _audit(object_id, "indexer", "index.done", trace_id, {"embeddings": n})
    remember(
        agent="indexer",
        kind="embedding_stats",
        object_id=object_id,
        trace_id=trace_id,
        data={
            "embeddings": int(n),
            "model": model,
        },
    )
    return {"embeddings": n}

def run(object_id: str, *, trace_id: str, model: str = "offline/hash-emb") -> dict[str, Any]:
    return index_object(object_id, model=model, trace_id=trace_id)
