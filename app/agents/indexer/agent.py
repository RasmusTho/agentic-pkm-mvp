from __future__ import annotations
import os, json, uuid
from typing import Any, Sequence
import psycopg
from psycopg.rows import dict_row
from app.search.embeddings import embed_text
from app.memory.store import remember, recall


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return url.replace("postgresql+psycopg://", "postgresql://")


def _chunks(object_id: str) -> list[dict]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, idx, text FROM chunks WHERE object_id=%s ORDER BY idx ASC", (object_id,))
        return list(cur.fetchall())


def _as_float_list(vec: Any) -> list[float]:
    # 1) JSON-sträng? -> parse
    if isinstance(vec, str):
        parsed = json.loads(vec)
        if not isinstance(parsed, list):
            raise ValueError("Embedding JSON måste vara en lista.")
        return [float(x) for x in parsed]
    # 2) Har tolist() (t.ex. NumPy)? -> använd den
    if hasattr(vec, "tolist"):
        return [float(x) for x in vec.tolist()]
    # 3) Annars: iterabel av numerics
    return [float(x) for x in vec]


def _write_embedding(embed_id: str, object_id: str, model: str, vec):
    dim = len(vec)
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO embeddings (id, object_id, model, dim, vec)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE
              SET object_id=EXCLUDED.object_id,
                  model=EXCLUDED.model,
                  dim=EXCLUDED.dim,
                  vec=EXCLUDED.vec
            """,
            (embed_id, object_id, model, dim, list(vec)),
        )


def _safe_confidence(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _latest_classifier_decision(object_id: str) -> tuple[list[str], float]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM decisions WHERE object_id=%s AND key='classification' ORDER BY created_at DESC LIMIT 1",
            (object_id,),
        )
        row = cur.fetchone()
    if not row:
        return ([], 0.0)
    value = row.get("value") or {}
    labels = value.get("tags")
    if isinstance(labels, str):
        label_list = [labels]
    elif isinstance(labels, (list, tuple, set)):
        label_list = [str(v) for v in labels]
    else:
        label_list = []
    confidence = _safe_confidence(value.get("confidence"))
    return (label_list, confidence)


def _audit(object_id: str | None, agent: str, action: str, trace_id: str | None, details: dict | None) -> None:
    with psycopg.connect(_dsn(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            # OBS: se till att detta matchar din verkliga audit-tabell (kolumner/ordning)!
            "INSERT INTO audit(id, object_id, agent, action, trace_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), object_id, agent, action, trace_id, json.dumps(details or {})),
        )


def index_object(object_id: str, *, model: str, trace_id: str) -> dict[str, Any]:
    recall("indexer", "embedding_stats", object_id=object_id, limit=3)
    labels, confidence = _latest_classifier_decision(object_id)
    cs = _chunks(object_id)
    if not cs:
        _audit(object_id, "indexer", "no_chunks", trace_id, {})
        return {"embeddings": 0}
    n = 0
    for c in cs:
        e = embed_text(c["text"])
        _write_embedding(str(uuid.uuid4()), object_id, model, e)
        n += 1
    _audit(
        object_id,
        "indexer",
        "index.done",
        trace_id,
        {"embeddings": n, "confidence": confidence, "labels": labels},
    )
    remember(
        agent="indexer",
        kind="embedding_stats",
        object_id=object_id,
        trace_id=trace_id,
        data={"embeddings": int(n), "model": model, "confidence": confidence, "labels": labels},
    )
    return {"embeddings": n}


def run(object_id: str, *, trace_id: str, model: str = "offline/hash-emb") -> dict[str, Any]:
    return index_object(object_id, model=model, trace_id=trace_id)