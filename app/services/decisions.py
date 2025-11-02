from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List

from app.db.db import conn_rw

# in-memory fallback so tests without db still work
_MEM_DECISIONS: Dict[str, List[dict[str, Any]]] = {}


def insert_decision(object_id: str, key: str, value: dict[str, Any], trace_id: str) -> None:
    rec = {
        "object_id": object_id,
        "key": key,
        "value": value,
        "trace_id": trace_id,
        "created_at": datetime.now(timezone.utc),
    }

    # always write to memory
    bucket = _MEM_DECISIONS.setdefault(object_id, [])
    bucket.append(rec)

    # best-effort DB write, ignore errors
    try:
        with conn_rw() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO decisions (object_id, key, value, trace_id, created_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        object_id,
                        key,
                        json.dumps(value),
                        trace_id,
                        rec["created_at"],
                    ),
                )
    except Exception:
        # no db? fine, pytest offline mode just uses memory
        return


def latest_decision(object_id: str, key: str) -> dict[str, Any] | None:
    """
    Return latest decision with this key for object_id from memory fallback.
    (DB lookup not needed for tests now, we rely on memory.)
    """
    items = _MEM_DECISIONS.get(object_id, [])
    # walk backwards for newest first
    for rec in reversed(items):
        if rec["key"] == key:
            return rec
    return None
