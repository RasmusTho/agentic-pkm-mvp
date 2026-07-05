"""AC coverage for #2944: ``handle_ingest_object_deleted`` purges vectors.

``app/workers/outbox_worker.py::handle_ingest_object_deleted`` was an explicit
no-op (logged and returned), leaving formal-model.md's T-delete postcondition
``purge_vectors(P.vectors)`` unenforced on the real delete-consumer path (only
the primitive itself was exercised, directly, by
``tests/properties/test_tombstone_lineage.py`` -- see that module's docstring
"Known, confirmed production gap", now closed by this change).

This module drives the real production dispatch entrypoint
(``app.workers.outbox_worker._dispatch_topic``) for the
``ingest.object.deleted`` topic end-to-end against the real (memory-backend)
``MemoryVectorIndex``, proving:

- a vector seeded for the deleted object's id is purged from the durable
  index by the real handler, not just the primitive in isolation;
- the object-store tombstone contract (D-2: the ``store_objects`` row stays,
  only ``path`` is nulled -- this handler never touches the object row at
  all) is respected implicitly, since the handler operates purely on the
  vector index;
- redelivery (the same event dispatched twice) converges: purging an already
  -purged (or never-indexed) object is a documented no-op, not an error.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.events.types import INGEST_OBJECT_DELETED
from app.stores import reset_store_backends
from app.stores.memory import MemoryVectorIndex
from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    yield
    reset_store_backends()


def _seed_vector(object_id: UUID, *, source_ref: str = "Inbox/deleted-note.md") -> MemoryVectorIndex:
    from app.stores import get_vector_index

    idx = get_vector_index()
    assert isinstance(idx, MemoryVectorIndex)
    identity = EmbeddingIdentity(provider="test", model="test-embed", dim=4, normalize=False)
    idx.upsert(
        object_id,
        kind="note",
        source_ref=source_ref,
        payload={"title": "Deleted Note"},
        embedding=[0.1, 0.2, 0.3, 0.4],
        model="test-embed",
        identity=identity,
    )
    return idx


def _dispatch_delete(payload: dict) -> None:
    from app.events.models import new_event

    envelope = new_event(event_type=INGEST_OBJECT_DELETED, payload=dict(payload))
    message = {
        "id": "test-row-1",
        "topic": INGEST_OBJECT_DELETED,
        "payload": payload,
        "event": envelope,
        "timestamp": envelope.created_at,
    }
    outbox_worker._dispatch_topic(
        INGEST_OBJECT_DELETED,
        payload,
        trace_id="test-trace",
        message=message,
        event_id=outbox_worker._event_id_from_message(message),
    )


def test_dispatching_delete_event_purges_vectors_end_to_end() -> None:
    """AC1: dispatching an ingest-delete event through the real worker purges
    the object's vectors from the durable index (memory backend)."""
    object_id = uuid4()
    idx = _seed_vector(object_id)
    assert idx.count_vectors() == 1

    payload = {
        "uuid": str(object_id),
        "path": "/vault/Inbox/deleted-note.md",
        "deleted": True,
        "reason": "vault_note_deleted",
        "source": "vault_sync.delete_note",
    }
    _dispatch_delete(payload)

    assert idx.count_vectors() == 0
    assert idx.purge_vectors(object_id, view="default") == 0, (
        "vector row must already be gone after dispatch -- a second purge is a no-op"
    )


def test_delete_event_does_not_touch_object_store_tombstone() -> None:
    """The handler purges vectors only; it must never delete or resurrect the
    ``store_objects`` row. D-2 tombstone semantics (path=NULL, row persists)
    are the responsibility of ``app.services.vault_sync.delete_note``
    upstream of this handler, not this handler itself -- this test proves the
    handler has no object-store side effect at all, so it cannot violate that
    contract."""
    from app import objects as object_store_module
    from app.objects import DomainObject
    from datetime import datetime, timezone

    object_id = uuid4()
    _seed_vector(object_id)

    tombstone = DomainObject(
        uuid=str(object_id),
        kind="note",
        payload={"title": "Deleted Note"},
        source_ref=None,  # tombstone: path/source_ref cleared upstream
        created_at=datetime.now(timezone.utc),
    )
    object_store_module._MEMORY_STORE[str(object_id)] = tombstone

    payload = {
        "uuid": str(object_id),
        "path": "/vault/Inbox/deleted-note.md",
        "deleted": True,
        "reason": "vault_note_deleted",
        "source": "vault_sync.delete_note",
    }
    _dispatch_delete(payload)

    # The tombstone row is untouched: still present, still nulled.
    assert str(object_id) in object_store_module._MEMORY_STORE
    assert object_store_module._MEMORY_STORE[str(object_id)].source_ref is None


def test_redelivery_of_same_delete_event_converges() -> None:
    """AC2 (idempotency): dispatching the SAME delete event twice purges once
    and no-ops the second time -- no error, no double-count, durable state
    identical after both dispatches."""
    object_id = uuid4()
    idx = _seed_vector(object_id)

    payload = {
        "uuid": str(object_id),
        "path": "/vault/Inbox/deleted-note.md",
        "deleted": True,
        "reason": "vault_note_deleted",
        "source": "vault_sync.delete_note",
    }

    _dispatch_delete(payload)
    assert idx.count_vectors() == 0

    # Redelivery: same payload dispatched again must not raise and must
    # leave the (already-empty) vector index unchanged.
    _dispatch_delete(payload)
    assert idx.count_vectors() == 0


def test_delete_event_with_unresolvable_uuid_is_a_safe_no_op() -> None:
    """A malformed/missing uuid in the payload must not crash the worker; the
    handler logs and skips the purge rather than raising UUID(...) errors."""
    payload = {
        "uuid": "not-a-uuid",
        "path": "/vault/Inbox/broken.md",
        "deleted": True,
    }
    # Must not raise.
    _dispatch_delete(payload)

    payload_missing = {
        "path": "/vault/Inbox/broken.md",
        "deleted": True,
    }
    _dispatch_delete(payload_missing)
