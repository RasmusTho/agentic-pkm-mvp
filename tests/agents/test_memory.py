from datetime import datetime, timedelta, timezone
from app.memory_kv.store import remember, recall, decay


def test_memory_store_roundtrip():
    agent = "normalizer"
    kind = "normalized"
    oid = "00000000-0000-0000-0000-000000000000"
    trace = "t-memory-1"

    remember(agent, kind, oid, trace, {"title": "sample", "bytes": 123})
    remember(agent, kind, oid, trace, {"title": "sample2", "bytes": 456})

    rows_all = recall(agent, kind, object_id=oid, limit=10)
    assert isinstance(rows_all, list)
    assert len(rows_all) >= 2
    assert rows_all[0]["title"] == "sample2"

    rows_one = recall(agent, kind, object_id=oid, limit=1)
    assert len(rows_one) == 1
    assert rows_one[0]["title"] == "sample2"

    future = datetime.now(timezone.utc) + timedelta(days=1)
    deleted = decay(agent, kind, before_ts=future)
    assert deleted >= 1


def test_memory_store_scopes_equal_object_ids_by_binding():
    agent = "normalizer"
    kind = "binding-isolation"
    oid = "11111111-1111-4111-8111-111111111111"

    remember(
        agent,
        kind,
        oid,
        "trace-a",
        {"binding": "a"},
        vault_binding_id="binding-a",
    )
    remember(
        agent,
        kind,
        oid,
        "trace-b",
        {"binding": "b"},
        vault_binding_id="binding-b",
    )

    assert recall(
        agent, kind, object_id=oid, vault_binding_id="binding-a"
    )[0]["binding"] == "a"
    assert recall(
        agent, kind, object_id=oid, vault_binding_id="binding-b"
    )[0]["binding"] == "b"
