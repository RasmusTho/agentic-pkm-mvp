import json
import psycopg
from app.db import conn_rw
from app.observability.tracer import start_span

def _upsert_object(cur, payload_json: str):
    cur.execute(
        """
        INSERT INTO objects (id, kind, payload)
        VALUES (gen_random_uuid(), %s, %s)
        """,
        ("note", payload_json),
    )

def handle_ingest_object_created(message):
    if isinstance(message, dict) and "payload" in message:
        payload = message["payload"]
        trace_id = message.get("trace_id")
    else:
        payload = message
        trace_id = None
    with conn_rw() as conn:
        with conn.cursor() as cur:
            pj = json.dumps(payload)
            with start_span("indexer.upsert", trace_id, {"kind": "note"}):
                _upsert_object(cur, pj)
        conn.commit()
