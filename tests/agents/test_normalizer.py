import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

def _dsn():
    v = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return v.replace("postgresql+psycopg://","postgresql://")

def _fetch_object_payload(oid: str) -> dict:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM objects WHERE id=%s", (oid,))
            row = cur.fetchone()
            return row["payload"] if row else {}

def _count_audit_for_object(oid: str) -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM audit WHERE object_id=%s AND agent='normalizer'", (oid,))
            return int(cur.fetchone()["n"])

def test_normalizer_core6_and_idempotence(tmp_path):
    from app.agents.normalizer.agent import run as normalize_run
    src = tmp_path / "sample.md"
    src.write_text("Hello world\n\nSome body text.")
    res1 = normalize_run(str(src), trace_id="t-normalize-1")
    oid1 = res1["object_id"]
    p1 = _fetch_object_payload(oid1)
    c1 = p1.get("core6", {})
    for k in ["id","type","title","created","updated","origin"]:
        assert k in c1
    res2 = normalize_run(str(src), trace_id="t-normalize-2")
    oid2 = res2["object_id"]
    assert oid1 == oid2
    p2 = _fetch_object_payload(oid2)
    c2 = p2.get("core6", {})
    assert c1["created"] == c2["created"]
    assert c2["updated"] == c1["updated"]
    assert _count_audit_for_object(oid1) >= 1
