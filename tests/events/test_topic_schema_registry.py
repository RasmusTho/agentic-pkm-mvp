"""KERNEL-08 (#2770): versioned per-topic outbox payload schema registry.

Covers:
- registry coverage: every topic in the live ``_dispatch_topic`` table has a
  registered ``schemas/events/<topic>.v1.schema.json`` (enumerated dynamically
  from the dispatch table's AST — no hardcoded topic list that could silently
  cap coverage);
- validation at write: ``write_outbox_event`` rejects a payload violating its
  registered schema and stamps ``meta.payload_schema``;
- grandfathering: a row with no ``payload_schema``/``schema_version`` tag is
  validated log-only at dispatch, never dead-lettered.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

import app.workers.outbox_worker as outbox_worker
from app.events.models import Event, new_event
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.events.topic_schema_registry import (
    TopicSchemaViolation,
    UnregisteredTopicError,
    current_schema_ref,
    is_registered_topic,
    resolve_payload_schema_version,
    validate_topic_payload,
)
from app.services.outbox import derive_binding_scoped_idempotency_key, write_outbox_event
from tests.helpers.topic_dispatch import enumerate_topic_comparators

pytestmark = pytest.mark.not_pg


def _dispatched_topics(
    source: str | None = None,
    module_ns: dict[str, Any] | None = None,
) -> list[str]:
    """Enumerate every topic constant compared in ``_dispatch_topic``'s if/elif chain.

    Walks the function's own source via ``ast`` (not a hand-maintained list) so
    a newly dispatched topic without a schema fails this test instead of
    silently shipping uncovered.
    """
    if source is None:
        source = inspect.getsource(outbox_worker._dispatch_topic)
    if module_ns is None:
        module_ns = vars(outbox_worker)
    resolved = enumerate_topic_comparators(source, module_ns)
    assert resolved, "expected to find at least one dispatched topic comparator in _dispatch_topic"
    return resolved


def _assert_every_dispatched_topic_has_schema(dispatched: list[str]) -> None:
    missing = [topic for topic in dispatched if not is_registered_topic(topic)]
    assert not missing, (
        "every topic in the live outbox_worker dispatch table must have a "
        f"schemas/events/<topic>.v1.schema.json: missing schemas for {missing}"
    )


def test_schema_enumerator_includes_literal_topics() -> None:
    synthetic_source = (
        "def _dispatch(topic):\n"
        "    if topic == CONSTANT_TOPIC:\n"
        "        pass\n"
        "    elif topic == 'inline.literal.topic':\n"
        "        pass\n"
        "    else:\n"
        "        pass\n"
    )

    assert _dispatched_topics(synthetic_source, {"CONSTANT_TOPIC": "module.constant.topic"}) == [
        "module.constant.topic",
        "inline.literal.topic",
    ]


def test_unregistered_literal_dispatch_topic_fails_schema_coverage() -> None:
    synthetic_source = (
        "def _dispatch(topic):\n"
        "    if topic == CONSTANT_TOPIC:\n"
        "        pass\n"
        "    elif topic == 'unregistered.synthetic.literal.topic':\n"
        "        pass\n"
        "    else:\n"
        "        pass\n"
    )
    dispatched = _dispatched_topics(synthetic_source, {"CONSTANT_TOPIC": "module.constant.topic"})

    with pytest.raises(AssertionError, match="unregistered.synthetic.literal.topic"):
        _assert_every_dispatched_topic_has_schema(dispatched)


def test_schema_and_idempotency_enumerators_agree() -> None:
    from tests.workers.test_handler_idempotency_harness import _dispatched_topics as idempotency_topics

    assert _dispatched_topics() == idempotency_topics()


def test_every_dispatched_topic_has_schema() -> None:
    dispatched = _dispatched_topics()
    assert len(dispatched) >= 9, f"expected at least the 9 known KERNEL-08 topics, got {dispatched}"

    _assert_every_dispatched_topic_has_schema(dispatched)


def test_write_validates_and_stamps_schema() -> None:
    """write_outbox_event rejects a schema-violating payload and stamps a valid one."""

    class _FakeConn:
        def __init__(self) -> None:
            self.inserted: list[dict[str, Any]] = []

        def cursor(self):
            return self

        def execute(self, sql: str, params: tuple) -> "_FakeConn":
            self._last_sql = sql
            self._last_params = params
            return self

        def fetchone(self):
            # Mirror _exec()'s cur.fetchone() contract: id, topic, payload(json), created_at, attempts
            idempotency_key = self._last_params[0]
            return (idempotency_key,)

        def close(self) -> None:
            pass

    # index.embedding.requested.v1 requires payload.object_id (string).
    valid_event = new_event(event_type="index.embedding.requested", payload={"object_id": "obj-123"})
    row_id = write_outbox_event(valid_event, conn=_FakeConn(), idempotency_key="key-valid-1")
    assert row_id == derive_binding_scoped_idempotency_key(
        "index.embedding.requested", COMPATIBILITY_BINDING_ID, "key-valid-1"
    )

    invalid_event = new_event(event_type="index.embedding.requested", payload={"not_object_id": "x"})
    with pytest.raises(TopicSchemaViolation):
        write_outbox_event(invalid_event, conn=_FakeConn(), idempotency_key="key-invalid-1")

    # A payload lacking object_id entirely also violates (required field absent).
    empty_event = new_event(event_type="index.embedding.requested", payload={})
    with pytest.raises(TopicSchemaViolation):
        write_outbox_event(empty_event, conn=_FakeConn(), idempotency_key="key-invalid-2")


def test_write_stamps_payload_schema_meta_on_valid_event() -> None:
    """A successfully written registered-topic event carries meta.payload_schema."""

    class _FakeConn:
        def cursor(self):
            return self

        def execute(self, sql: str, params: tuple) -> "_FakeConn":
            self._last_params = params
            return self

        def fetchone(self):
            return (self._last_params[0],)

        def close(self) -> None:
            pass

    captured: dict[str, Any] = {}
    original_model_dump_json = Event.model_dump_json

    def _capture(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        captured["meta"] = self.meta
        return original_model_dump_json(self, *args, **kwargs)

    event = new_event(event_type="index.embedding.requested", payload={"object_id": "obj-456"})
    try:
        Event.model_dump_json = _capture  # type: ignore[assignment]
        write_outbox_event(event, conn=_FakeConn(), idempotency_key="key-meta-1")
    finally:
        Event.model_dump_json = original_model_dump_json  # type: ignore[assignment]

    assert captured["meta"] == {"payload_schema": current_schema_ref("index.embedding.requested")}
    # The caller's original event object is not mutated in place.
    assert event.meta is None


def test_unregistered_topic_is_written_unvalidated() -> None:
    """Topics with no registered schema are written through unchanged (no coverage claim)."""

    class _FakeConn:
        def cursor(self):
            return self

        def execute(self, sql: str, params: tuple) -> "_FakeConn":
            self._last_params = params
            return self

        def fetchone(self):
            return (self._last_params[0],)

        def close(self) -> None:
            pass

    assert not is_registered_topic("some.unregistered.topic")
    event = new_event(event_type="some.unregistered.topic", payload={"anything": "goes"})
    row_id = write_outbox_event(event, conn=_FakeConn(), idempotency_key="key-unreg-1")
    assert row_id == derive_binding_scoped_idempotency_key(
        "some.unregistered.topic", COMPATIBILITY_BINDING_ID, "key-unreg-1"
    )


def test_pre_registry_rows_grandfathered_v0() -> None:
    """A row with no payload_schema/schema_version tag resolves as grandfathered v0."""
    assert resolve_payload_schema_version(None).is_grandfathered is True
    assert resolve_payload_schema_version({}).is_grandfathered is True
    assert resolve_payload_schema_version({"version": "1.0"}).is_grandfathered is True

    tagged = resolve_payload_schema_version({"payload_schema": "index.embedding.requested.v1"})
    assert tagged.is_grandfathered is False
    assert tagged.raw == "index.embedding.requested.v1"

    legacy_tagged = resolve_payload_schema_version({"schema_version": "index.embedding.requested.v1"})
    assert legacy_tagged.is_grandfathered is False


def test_validate_topic_payload_raises_for_unregistered_topic() -> None:
    with pytest.raises(UnregisteredTopicError):
        validate_topic_payload("no.such.topic", {})


def test_validate_topic_payload_accepts_known_good_payloads_per_topic() -> None:
    """Sanity: the shipped v1 schemas accept the real producer shapes, not just a toy example."""
    samples: dict[str, dict[str, Any]] = {
        "ingest.object.created": {"uuid": "note-1", "kind": "note"},
        "ingest.vault.changed": {"relative_path": "Inbox/note.md", "mtime": 123.0},
        "ingest.object.deleted": {"uuid": "note-1", "path": "/vault/note.md", "deleted": True},
        "panel.scan.requested": {"vault_path": "/vault/note.md", "relative_path": "note.md"},
        "promote.intent.created": {"note": {"uuid": "note-1", "path": "/vault/note.md"}},
        "note.move.workbench": {"note_path": "/vault/note.md", "params": {"destination_zone": "workbench"}},
        "index.embedding.requested": {"object_id": "obj-1"},
    }
    for topic, payload in samples.items():
        validate_topic_payload(topic, payload)  # must not raise


def test_validate_topic_payload_rejects_missing_required_fields() -> None:
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload("index.embedding.requested", {})
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload("note.move.workbench", {"params": {}})
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload("ingest.vault.changed", {"mtime": 1.0})
    with pytest.raises(TopicSchemaViolation):
        validate_topic_payload("panel.scan.requested", {"hash": "abc"})
