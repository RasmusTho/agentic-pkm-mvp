from typing import Dict, Any
import os
import psycopg
from app.services.embedding import deterministic_embedding

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:15432/app")

def _conn():
    return psycopg.connect(DATABASE_URL)

def handle_ingest_object_created(payload: Dict[str, Any]) -> None:
    content = payload.get("content") or ""
    vector = deterministic_embedding(content)
    uuid = payload["uuid"]
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into objects_embeddings(uuid, dim, vector) values(%s,%s,%s) on conflict (uuid) do update set dim=excluded.dim, vector=excluded.vector",
                (uuid, len(vector), vector),
            )
        conn.commit()
