from __future__ import annotations

import json
import os
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.agents.base.audit import audit_log
from app.memory.store import remember, recall

AGENT = "projector"


def _dsn() -> str:
    url = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return url.replace("postgresql+psycopg://", "postgresql://")


def _ensure_set(conn: psycopg.Connection, name: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM sets WHERE name=%s", (name,))
        row = cur.fetchone()
        if row:
            return row["id"]
        set_id = str(uuid.uuid4())
        cur.execute("INSERT INTO sets(id, name) VALUES (%s, %s)", (set_id, name))
        return set_id


def _latest_evaluation(conn: psycopg.Connection, object_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT value
            FROM decisions
            WHERE object_id = %s AND key = 'evaluate'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (object_id,),
        )
        row = cur.fetchone()
        return row["value"] if row else None


def project(object_id: str, *, set_name: str = "published", trace_id: str) -> dict[str, Any]:
    recall(AGENT, "projection", object_id=object_id, limit=3)
    with psycopg.connect(_dsn(), autocommit=True, row_factory=dict_row) as conn:
        evaluation = _latest_evaluation(conn, object_id)
        if not evaluation:
            payload = {"promoted": False, "score": 0.0, "set": set_name, "reason": "missing_evaluation"}
            audit_log(
                object_id=object_id,
                agent=AGENT,
                action="promotion.missing_evaluation",
                trace_id=trace_id,
                details=payload,
            )
            remember(AGENT, "projection", object_id, trace_id, payload)
            return {
                "event": "promotion.project.skip",
                "object_id": object_id,
                "promote": False,
                "score": 0.0,
                "set": set_name,
                "reason": "missing_evaluation",
            }

        promote = bool(evaluation.get("promote"))
        score = float(evaluation.get("score") or 0.0)

        if not promote:
            payload = {"promoted": False, "score": score, "set": set_name}
            audit_log(
                object_id=object_id,
                agent=AGENT,
                action="promotion.skip",
                trace_id=trace_id,
                details=payload,
            )
            remember(AGENT, "projection", object_id, trace_id, payload)
            return {
                "event": "promotion.project.skip",
                "object_id": object_id,
                "promote": False,
                "score": score,
                "set": set_name,
            }

        set_id = _ensure_set(conn, set_name)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM membership WHERE set_id = %s AND object_id = %s",
                (set_id, object_id),
            )
            already_present = cur.fetchone() is not None
            if not already_present:
                cur.execute(
                    "INSERT INTO membership(id, set_id, object_id) VALUES (%s, %s, %s)",
                    (str(uuid.uuid4()), set_id, object_id),
                )

        payload = {"promoted": True, "score": score, "set": set_name}
        audit_log(
            object_id=object_id,
            agent=AGENT,
            action="promotion.projected",
            trace_id=trace_id,
            details=payload,
        )
        remember(AGENT, "projection", object_id, trace_id, payload)
        return {
            "event": "promotion.project.done",
            "object_id": object_id,
            "promote": True,
            "score": score,
            "set": set_name,
        }


def run(object_id: str, *, set_name: str = "published", trace_id: str) -> dict[str, Any]:
    return project(object_id, set_name=set_name, trace_id=trace_id)
