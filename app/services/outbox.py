import json
import os
from typing import Any, Dict, Optional

import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:15432/app")

BOOTSTRAP_SQL = """
create table if not exists outbox (
  id bigserial primary key,
  topic text not null,
  payload_json jsonb not null,
  occurred_at timestamptz not null default now(),
  delivered_at timestamptz
);
create table if not exists objects (
  uuid text primary key,
  title text not null,
  review_state text not null,
  content text not null,
  path text
);
alter table if exists objects add column if not exists path text;
create table if not exists objects_embeddings (
  uuid text primary key,
  dim int not null,
  vector double precision[] not null,
  occurred_at timestamptz not null default now()
);
create table if not exists file_state (
  path text primary key,
  uuid text,
  fm_hash text,
  body_hash text,
  mtime timestamptz,
  last_seen timestamptz default now()
);
create index if not exists file_state_uuid_idx on file_state(uuid);
"""


def _conn():
    return psycopg.connect(DATABASE_URL)


def bootstrap() -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(BOOTSTRAP_SQL)
        conn.commit()


def insert_object_and_outbox(obj: Dict[str, Any], topic: str, trace_id: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into objects(uuid,title,review_state,content,path) values(%s,%s,%s,%s,%s) "
                "on conflict (uuid) do update set title=excluded.title, review_state=excluded.review_state, content=excluded.content, path=excluded.path",
                (obj["uuid"], obj["title"], obj["review_state"], obj["content"], obj.get("path")),
            )
            payload = dict(obj)
            payload["trace_id"] = trace_id
            cur.execute("insert into outbox(topic, payload_json) values(%s,%s)", (topic, json.dumps(payload)))
        conn.commit()


def poll_outbox_one(undelivered_only: bool = True) -> Optional[Dict[str, Any]]:
    sql = "select id, topic, payload_json::text from outbox "
    if undelivered_only:
        sql += "where delivered_at is null "
    sql += "order by id asc limit 1"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if not row:
                return None
            oid, topic, payload_json = row
            cur.execute("update outbox set delivered_at = now() where id = %s", (oid,))
        conn.commit()
    return {"id": oid, "topic": topic, "payload": json.loads(payload_json)}
