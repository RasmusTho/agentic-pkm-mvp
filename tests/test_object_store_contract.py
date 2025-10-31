from datetime import datetime, timezone
from app.store.object_store import DomainObject
from tests.fakes.fake_object_store import FakeObjectStore


def test_fake_object_store_roundtrip():
    store = FakeObjectStore()
    ts = datetime.now(timezone.utc)

    obj = DomainObject(
        uuid="1234-test-uuid",
        kind="capture_note",
        payload={
            "frontmatter": {"uuid": "1234-test-uuid", "review_state": "inbox"},
            "body": "hello from test",
        },
        source_ref="cap-test",
        created_at=ts,
    )

    store.save_object(obj, emit_outbox=True, trace_id="trace-xyz")

    fetched = store.get_object("1234-test-uuid")
    assert fetched is not None
    assert fetched.uuid == "1234-test-uuid"
    assert fetched.kind == "capture_note"
    assert fetched.payload["body"] == "hello from test"

    listed = store.list_objects()
    assert len(listed) == 1
    assert listed[0].uuid == "1234-test-uuid"
