from __future__ import annotations

import json
from typing import Any, Dict
import uuid as _uuid

import psycopg
from app.db.dsn import resolve_dsn

def _conn():
    return psycopg.connect(resolve_dsn())

def _is_valid_uuid(v: str) -> bool:
    try:
        _uuid.UUID(str(v))
        return True
    except Exception:
        return False

def handle_ingest_object_created(obj: Dict[str, Any]) -> None:
    uid = obj.get("uuid")
    if not uid:
        return

    payload = {
        "title": obj.get("title"),
        "review_state": obj.get("review_state"),
        "source_uuid": uid,  # bevara inkommande värde för spårbarhet
    }

    with _conn() as conn, conn.cursor() as cur:
        if _is_valid_uuid(uid):
            # Skriv med given UUID (stödjer både id- och uuid-kolumnnamn)
            try:
                cur.execute(
                    """
                    insert into objects(id, kind, payload)
                    values (%s, %s, %s::jsonb)
                    on conflict (id) do update set payload = excluded.payload
                    """,
                    (uid, "note", json.dumps(payload)),
                )
            except Exception:
                cur.execute(
                    """
                    insert into objects(uuid, kind, payload)
                    values (%s, %s, %s::jsonb)
                    on conflict (uuid) do update set payload = excluded.payload
                    """,
                    (uid, "note", json.dumps(payload)),
                )
        else:
            # Generera UUID i databasen när inkommande inte är en riktig UUID
            # (kräver pgcrypto)
            try:
                cur.execute(
                    """
                    insert into objects(id, kind, payload)
                    values (gen_random_uuid(), %s, %s::jsonb)
                    """,
                    ("note", json.dumps(payload)),
                )
            except Exception:
                cur.execute(
                    """
                    insert into objects(uuid, kind, payload)
                    values (gen_random_uuid(), %s, %s::jsonb)
                    """,
                    ("note", json.dumps(payload)),
                )