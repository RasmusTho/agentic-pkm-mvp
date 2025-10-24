from __future__ import annotations
import os, json, re, uuid
from typing import Any
import psycopg
from psycopg.rows import dict_row
from app.llm.adapter import generate
from app.agents.base.audit import audit_log

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def _fetch_object(oid: str) -> dict[str, Any] | None:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, payload FROM objects WHERE id=%s", (oid,))
            return cur.fetchone()

def _heuristic(text: str) -> dict[str, Any]:
    title_first = re.search(r"^#\s+(.+)$", text, re.M)
    tags = []
    if "TODO" in text.upper():
        tags.append("topic/todo")
    if "http" in text:
        tags.append("topic/links")
    if title_first:
        tags.append("topic/has_title")
    return {"type":"note","trust":"provisional","tags":sorted(set(tags)), "confidence":0.55}

def _parse_json_block(s: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def classify_object(object_id: str, *, trace_id: str) -> dict[str, Any]:
    row = _fetch_object(object_id)
    if not row:
        raise ValueError("object not found")
    payload = row["payload"] or {}
    text = payload.get("text") or payload.get("content") or ""

    messages = [
        {"role":"system","content":"Returnera JSON {type, tags, trust, confidence}. type∈{note,seed,idea,doc}. trust∈{own,provisional,external,conflict}. tags=[topic/*]. Svara enbart JSON."},
        {"role":"user","content":text[:4000]},
    ]
    content = None
    try:
        content = generate(messages, reasoning=True)
        data = _parse_json_block(content) or {}
    except Exception:
        data = {}

    if not data or not isinstance(data, dict) or float(data.get("confidence",0)) < 0.7:
        data = _heuristic(text)

    value = {
        "type": data.get("type","note"),
        "tags": data.get("tags",[]),
        "trust": data.get("trust","provisional"),
        "confidence": float(data.get("confidence",0.55)),
    }

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO decisions (id, object_id, key, value, created_at) VALUES (%s,%s,%s,%s::jsonb, now())",
                (str(uuid.uuid4()), object_id, "classification", json.dumps(value)),
            )
    audit_log(object_id=object_id, agent="classifier", action="classify", trace_id=trace_id, details=value)
    audit_log(object_id=object_id, agent="classifier", action="metadata.changed", trace_id=trace_id, details={"key":"classification"})
    return {"object_id": object_id, "classification": value, "raw": content}

def run(object_id: str, *, trace_id: str) -> dict[str, Any]:
    return classify_object(object_id, trace_id=trace_id)
