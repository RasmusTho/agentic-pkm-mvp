import os, json
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from app.agents.normalizer.agent import run as normalize_run

def _dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")

def _fetch_object_payload(oid: str):
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, kind, source_ref, payload FROM objects WHERE id=%s", (oid,))
            return cur.fetchone()

def test_normalizer_core6_and_idempotence(tmp_path, monkeypatch):
    src = tmp_path / "sample.md"
    src.write_text("Hello world\n\nSome body text.")
    trace_id = "t-normalize-1"
    res1 = normalize_run(str(src), trace_id=trace_id)
    oid1 = res1["object_id"]
    row1 = _fetch_object_payload(oid1)
    assert row1 is not None
    assert UUID(oid1)
    assert row1["source_ref"].endswith("sample.md")
    payload = row1["payload"]
    assert "core6" in payload and "text" in payload
    core6 = payload["core6"]
    for k in ("id","type","title","created","updated","origin"):
        assert k in core6
    assert core6["id"] == oid1
    assert core6["type"] == "seed"
    res2 = normalize_run(str(src), trace_id=trace_id)
    oid2 = res2["object_id"]
    row2 = _fetch_object_payload(oid2)
    assert oid1 == oid2
    assert row2["id"] == row1["id"]
