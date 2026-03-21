import os

import psycopg
import pytest

from app.db.dsn import resolve_dsn
from app.stores.provider import get_stores

pytestmark = pytest.mark.pg


def _pg_available() -> bool:
    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


def test_pg_roundtrip(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    objects, decisions = get_stores()
    obj = objects.upsert(kind="note", payload={"title": "pg"})
    res = decisions.put(object_id=obj["id"], agent="it", kind="check", key="classification", value={"type": "note"})
    assert res["id"]
