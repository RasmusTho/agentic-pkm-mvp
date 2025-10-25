from __future__ import annotations
import os, re, json, hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4
import psycopg
from psycopg.rows import dict_row
from app.agents.base.audit import audit_log
from app.memory.store import remember, recall

CORE6_KEYS = ("id","type","title","created","updated","origin")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _title_from_text(text: str, filename: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    if m:
        return m.group(1).strip()
    name = os.path.splitext(os.path.basename(filename))[0]
    return name.strip() or "untitled"

def _stable_id_for_source(source_ref: str) -> UUID:
    h = hashlib.sha256(source_ref.encode("utf-8")).digest()
    return UUID(bytes=h[:16], version=4)

def normalize_file(path: str, *, trace_id: str) -> UUID:
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    source_ref = os.path.abspath(path)
    object_id = _stable_id_for_source(source_ref)
    title = _title_from_text(text, path)
    core6 = {
        "id": str(object_id),
        "type": "seed",
        "title": title,
        "created": _now_iso(),
        "updated": _now_iso(),
        "origin": source_ref,
    }
    payload = {"core6": core6, "text": text}
    dsn = os.environ.get("DATABASE_URL","postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO objects (id, kind, source_ref, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (id) DO UPDATE
                  SET kind = EXCLUDED.kind,
                      source_ref = EXCLUDED.source_ref,
                      payload = objects.payload
                RETURNING id
                """,
                (str(object_id), "note", source_ref, json.dumps(payload)),
            )
    remember(
        agent="normalizer",
        kind="normalized",
        object_id=str(object_id),
        trace_id=trace_id,
        data={
            "core6": core6,
            "bytes": len(text or ""),
        },
    )
    audit_log(object_id=str(object_id), agent="normalizer", action="normalize", trace_id=trace_id, details={"source_ref": source_ref, "bytes": len(raw)})
    return object_id

def run(path: str, *, trace_id: str) -> dict:
    recall("normalizer", "normalized", object_id=None, limit=3)
    object_id = normalize_file(path, trace_id=trace_id)
    return {"object_id": str(object_id), "trace_id": trace_id}
