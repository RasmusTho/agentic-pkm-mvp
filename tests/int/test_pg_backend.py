import pytest

from app.stores.provider import get_stores

pytestmark = pytest.mark.pg


def test_pg_roundtrip(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "pg")
    objects, decisions = get_stores()
    obj = objects.upsert(kind="note", payload={"title": "pg"})
    res = decisions.put(object_id=obj["id"], agent="it", kind="check", key="classification", value={"type": "note"})
    assert res["id"]
