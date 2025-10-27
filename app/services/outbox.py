# app/services/outbox.py
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import psycopg
from psycopg.rows import dict_row

from app.db import conn_rw, ensure_schema

# Minimal bootstrap-DDL för outbox. Körs bara om tabellen saknas.
# (Skapar även index som är säkra att köra flera gånger.)
_OUTBOX_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS public.outbox (
  id           bigserial PRIMARY KEY,
  topic        text NOT NULL,
  payload      jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz NULL,
  attempts     int NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_created_at_idx ON public.outbox (created_at DESC);
CREATE INDEX IF NOT EXISTS outbox_delivered_null_idx ON public.outbox ((delivered_at IS NULL));
"""

def bootstrap() -> None:
    """
    Säkerställ att schema finns och att outbox-tabellen finns.
    Körs med app-rättigheter efter att ägarskap är fixat.
    """
    with conn_rw() as conn:
        # Kör modulens migrations (om några). Saknar vi rättigheter så
        # fångar ensure_schema redan InsufficientPrivilege och hoppar över.
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(_OUTBOX_BOOTSTRAP_SQL)
        conn.commit()

def insert_object_and_outbox(payload: Dict[str, Any], topic: str, trace_id: Optional[str]) -> None:
    """
    Lägger bara ett meddelande i outbox. Själva objekt-/domänlagringen sker i respektive service.
    """
    with conn_rw() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '30s'")
        cur.execute(
            "INSERT INTO public.outbox(topic, payload) VALUES (%s, %s::jsonb)",
            (topic, json.dumps(payload)),
        )
        conn.commit()

def poll_outbox_one(undelivered_only: bool = True) -> Optional[Dict[str, Any]]:
    """
    Hämtar äldsta meddelandet (ev. bara icke-levererade), markerar det levererat och returnerar.
    """
    sql = "SELECT id, topic, payload::text FROM public.outbox "
    if undelivered_only:
        sql += "WHERE delivered_at IS NULL "
    sql += "ORDER BY id ASC LIMIT 1"

    with conn_rw() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        row = cur.fetchone()
        if not row:
            return None
        oid = row["id"]
        topic = row["topic"]
        payload_json = row["payload"]
        cur.execute("UPDATE public.outbox SET delivered_at = now() WHERE id = %s", (oid,))
        conn.commit()
    return {"id": oid, "topic": topic, "payload": json.loads(payload_json)}
