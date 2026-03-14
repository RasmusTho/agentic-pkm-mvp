import json
import os
import statistics
import time
from uuid import uuid4

import psycopg

N = int(os.getenv("QAS010_N", "15"))


def _conn():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return psycopg.connect(database_url)


def seed():
    with _conn() as conn:
        with conn.cursor() as cur:
            for _ in range(N):
                uid = "qas010-" + uuid4().hex[:8]
                cur.execute(
                    """
                    insert into objects(uuid,title,review_state,content)
                    values(%s,%s,%s,%s)
                    on conflict (uuid) do nothing
                    """,
                    (uid, f"Seed-{uid}", "inbox", f"qas010 content {uid}"),
                )
                cur.execute(
                    """
                    insert into outbox(topic, payload_json)
                    values(%s, jsonb_build_object('uuid', %s, 'title', %s, 'review_state', %s, 'content', %s))
                    """,
                    ("ingest.object.created", uid, f"Seed-{uid}", "inbox", f"qas010 content {uid}"),
                )
        conn.commit()


def measure(timeout: float = 10.0):
    start = time.time()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select payload_json->>'uuid'
                from outbox
                where topic='ingest.object.created'
                order by id desc
                limit %s
                """,
                (N,),
            )
            target = [row[0] for row in cur.fetchall()]
    latencies: dict[str, float] = {}
    while time.time() - start < timeout and len(latencies) < len(target):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select o.payload_json->>'uuid' as uuid,
                           extract(epoch from (e.occurred_at - o.occurred_at)) as latency
                    from outbox o
                    join objects_embeddings e on e.uuid = o.payload_json->>'uuid'
                    where o.topic='ingest.object.created'
                    """,
                )
                for uuid, latency in cur.fetchall():
                    latencies[uuid] = float(latency)
        time.sleep(0.2)
    collected = [latencies[u] for u in target if u in latencies]
    if not collected:
        print(json.dumps({"ok": False, "reason": "no_embeddings"}))
        raise SystemExit(2)
    p95 = statistics.quantiles(collected, n=100)[94] if len(collected) >= 100 else sorted(collected)[max(int(len(collected) * 0.95) - 1, 0)]
    ok = p95 <= 2.0
    print(json.dumps({"ok": ok, "count": len(collected), "p95": p95, "sample": collected[:10]}))
    if not ok:
        raise SystemExit(1)


def main():
    seed()
    measure()

if __name__ == "__main__":
    main()
