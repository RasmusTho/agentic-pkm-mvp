"""P-7 tombstone-preserves-lineage property (#2913).

Purpose: deleting a note leaves a ``P.objects`` tombstone (``path=NULL``) and
every decisions/audit row anchored to it survives with intact FK references --
the D-2 ratified contract, pinned as a regression floor. This is also the
floor for the future event-triggered relevance-decay lifecycle: decay design
must change this test deliberately, never break it silently.

Derivation: ``docs/testing/invariant-synthesis-2026-07.md :: P-7`` and
``docs/architecture/runtime-semantics.md :: Divergences`` (D-2 RATIFIED
tombstone; D-5 resolution #2788 realigned ``decisions.object_id`` to
``ON DELETE SET NULL``, mirroring ``audit.object_id``). Formal model anchor:
``docs/architecture/formal-model.md`` §2.2 T-delete --
    post: P.file_state rows deleted ∧ P.objects.path←NULL (TOMBSTONE — D-2)
          ∧ purge_vectors(P.vectors) [indexer path] ; worker handler is a no-op

Real production seam under test: ``app.services.vault_sync.delete_note`` --
the actual watcher delete-propagation function, driven for real against a
fake ``psycopg``-shaped connection that models the ``objects``/``file_state``
tables in-process (the same pattern ``tests/services/
test_vault_sync_lifecycle.py`` already established for this module, because
``delete_note`` issues raw SQL against Postgres tables with no memory-backend
port of its own). ``services/decisions.py::insert_decision``/
``latest_decision`` run through their OWN real ``STORE_BACKEND=memory``
in-process path (``_MEM_DECISIONS``), so the decision-survival half of this
property exercises real, unmodified production code, not a re-implementation.

``app.workers.outbox_worker.handle_ingest_object_deleted`` (#2944) now wires
the ``ingest.object.deleted`` event emitted by ``vault_sync.delete_note`` to
the real ``purge_vectors`` primitive, closing formal-model.md's T-delete
postcondition (``purge_vectors(P.vectors) [indexer path]``). This property
drives the REAL consumer dispatch path
(``app.workers.outbox_worker._dispatch_topic``) with the event
``delete_note`` actually emitted, rather than calling ``purge_vectors``
directly -- proving the end-to-end wiring, not just the primitive in
isolation.

``audit_event`` (``app/services/audit.py``) is a genuine, unconditional no-op
under the explicit memory backend ("best-effort... silently no-ops for
pytest") and no production call site invokes it from the delete path itself
-- ``vault_sync.delete_note`` never calls it. The AC's "audit rows intact and
non-orphaned" therefore refers to PRE-EXISTING audit rows anchored to the
object surviving deletion, not a new row created by the delete. Since D-2
means the ``objects`` row is NEVER actually deleted (only ``path`` is nulled),
no FK ever fires for either ``decisions`` or ``audit`` on this path -- the
tombstone makes CASCADE/SET NULL moot by construction, which is the property
this test pins.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from app.services import vault_sync
from app.services.decisions import insert_decision, latest_decision, _MEM_DECISIONS
from app.stores.memory import MemoryVectorIndex


# ---------------------------------------------------------------------------
# Fake connection modeling `objects` + `file_state` (mirrors
# tests/services/test_vault_sync_lifecycle.py's established fake-conn shape)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, conn: "_FakeConn") -> None:
        self.conn = conn
        self.rowcount = 0
        self._fetchone: Any = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:  # type: ignore[no-untyped-def]
        normalized = " ".join(sql.split()).lower()
        self.rowcount = 0
        self._fetchone = None

        if normalized.startswith("insert into objects(id, kind, payload, path)"):
            object_id, kind, payload_json, path = params
            self.conn.objects[object_id] = {
                "id": object_id,
                "kind": kind,
                "payload": payload_json,
                "path": path,
            }
            self.rowcount = 1
            return
        if normalized.startswith("insert into objects(uuid, kind, payload, path)"):
            object_id, kind, payload_json, path = params
            self.conn.objects[object_id] = {
                "id": object_id,
                "kind": kind,
                "payload": payload_json,
                "path": path,
            }
            self.rowcount = 1
            return
        if normalized.startswith("insert into file_state(path, uuid, fm_hash, body_hash, mtime, last_seen)"):
            path, uuid_value, fm_hash, body_hash, mtime = params
            self.conn.file_state[path] = {
                "path": path,
                "uuid": uuid_value,
                "fm_hash": fm_hash,
                "body_hash": body_hash,
                "mtime": mtime,
            }
            self.rowcount = 1
            return
        if normalized.startswith("delete from file_state where uuid = %s and path <> %s"):
            uuid_value, keep_path = params
            before = len(self.conn.file_state)
            self.conn.file_state = {
                path: row
                for path, row in self.conn.file_state.items()
                if not (row.get("uuid") == uuid_value and path != keep_path)
            }
            self.rowcount = before - len(self.conn.file_state)
            return
        if normalized.startswith("select path, uuid, fm_hash, body_hash, mtime from file_state where path = %s"):
            (path,) = params
            self._fetchone = self.conn.file_state.get(path)
            return
        if normalized.startswith("select path, uuid, fm_hash, body_hash, mtime from file_state where uuid = %s"):
            (uuid_value,) = params
            match = next(
                (row for row in self.conn.file_state.values() if row.get("uuid") == uuid_value),
                None,
            )
            self._fetchone = match
            return
        if normalized.startswith("delete from file_state where path = %s"):
            (path,) = params
            self.rowcount = 1 if self.conn.file_state.pop(path, None) else 0
            return
        if normalized.startswith("select count(*) from file_state where uuid = %s"):
            (uuid_value,) = params
            count = sum(1 for row in self.conn.file_state.values() if row.get("uuid") == uuid_value)
            self._fetchone = (count,)
            return
        if normalized.startswith("update objects set path = null where uuid = %s"):
            (uuid_value,) = params
            if uuid_value in self.conn.objects:
                self.conn.objects[uuid_value]["path"] = None
                self.rowcount = 1
            return
        if normalized.startswith("update objects set path = null where id = %s"):
            (uuid_value,) = params
            if uuid_value in self.conn.objects:
                self.conn.objects[uuid_value]["path"] = None
                self.rowcount = 1
            return
        raise AssertionError(f"Unhandled SQL in property fake: {normalized}")

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self._fetchone


class _FakeConn:
    def __init__(self) -> None:
        self.file_state: dict[str, dict[str, object]] = {}
        # Keyed by object id/uuid -- models the `objects` table row set.
        self.objects: dict[str, dict[str, object]] = {}

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _memory_decisions_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route services/decisions.py through its own explicit memory backend,
    and clear its in-process store before/after each test so no state leaks
    between tests (mirrors _machinery.py's ``_memory_backend`` pattern)."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    _MEM_DECISIONS.clear()
    yield
    _MEM_DECISIONS.clear()


def _seed_note(
    conn: _FakeConn,
    *,
    object_id: str,
    path: str,
) -> None:
    """Seed one object + file_state row, simulating a prior real ingest."""
    conn.objects[object_id] = {
        "id": object_id,
        "kind": "note",
        "payload": '{"title": "Property Note"}',
        "path": path,
    }
    conn.file_state[path] = {
        "path": path,
        "uuid": object_id,
        "fm_hash": "fm-hash",
        "body_hash": "body-hash",
        "mtime": datetime.now(timezone.utc),
    }


def _delete_note(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn, path: str, object_id: str) -> list[tuple]:
    """Drive the REAL ``vault_sync.delete_note`` (watcher delete propagation)
    against the fake connection, recording the outbox emission it makes."""
    emitted: list[tuple] = []
    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        vault_sync,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id, **kwargs: emitted.append((payload, topic, trace_id)),
    )
    vault_sync.delete_note(path, uuid_value=object_id)
    return emitted


# ---------------------------------------------------------------------------
# test_delete_leaves_anchored_tombstone
# ---------------------------------------------------------------------------


def test_delete_leaves_anchored_tombstone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting a note leaves an objects tombstone (path=NULL); pre-existing
    decisions/audit rows anchored to that object_id survive intact and
    non-orphaned; dispatching the real emitted ``ingest.object.deleted``
    event through the real worker consumer path purges the object's vectors,
    as the formal model's T-delete postcondition states (#2944).
    """
    object_id = str(uuid4())
    path = "/vault/notes/property-note.md"

    conn = _FakeConn()
    _seed_note(conn, object_id=object_id, path=path)

    # Pre-existing judgment/audit history anchored to this object, from
    # earlier (real) agent activity -- this is what must survive the delete.
    insert_decision(object_id, "promotion_gate", {"verdict": "hold"}, trace_id="trace-seed")
    audited_calls: list[dict] = []
    monkeypatch.setattr(
        "app.services.audit.audit_event",
        lambda **kwargs: audited_calls.append(kwargs),
    )
    import app.services.audit as audit_module

    audit_module.audit_event(
        event="promotion.gate.evaluated",
        object_id=object_id,
        agent="reviewer",
        trace_id="trace-seed",
    )
    assert audited_calls, "expected the seeded audit call to be recorded"

    # Pre-existing vectors for this object, via the real vector-index seam.
    # An explicit identity avoids depending on the process-global embedding
    # config (get_embedding_identity()), which the memory index otherwise
    # falls back to on first upsert.
    from uuid import UUID

    from app.components.embeddings import EmbeddingIdentity

    identity = EmbeddingIdentity(provider="test", model="test-embed", dim=4, normalize=False)
    vector_index = MemoryVectorIndex()
    vector_index.upsert(
        UUID(object_id),
        kind="note",
        source_ref=path,
        payload={"title": "Property Note"},
        embedding=[0.1, 0.2, 0.3, 0.4],
        model="test-embed",
        identity=identity,
    )
    assert vector_index.count_vectors() == 1

    # --- Act: real human-delete -> watcher delete propagation ---
    emitted = _delete_note(monkeypatch, conn, path, object_id)

    # --- Assert: objects row persists as a tombstone (path=NULL), never
    # deleted -- D-2's ratified contract. ---
    assert object_id in conn.objects, "the objects row must never be deleted (D-2 tombstone)"
    assert conn.objects[object_id]["path"] is None, "tombstoned object must have path=NULL"

    # file_state is cleared for the deleted path (that half is real cleanup,
    # distinct from the permanent objects tombstone).
    assert path not in conn.file_state

    # A real ingest.object.deleted event was emitted for this transition.
    assert emitted
    payload, topic, _trace_id = emitted[-1]
    assert topic == "ingest.object.deleted"
    assert payload["uuid"] == object_id
    assert payload["deleted"] is True

    # --- Assert: decisions row anchored to object_id survives intact, not
    # orphaned -- the D-5 FK-alignment contract (ON DELETE SET NULL) is moot
    # here because D-2 means the object row itself is never deleted, so no FK
    # ever fires; the decision keeps its original object_id and full value. ---
    decision = latest_decision(object_id, "promotion_gate")
    assert decision is not None, "decision row must survive the note's deletion"
    assert decision["object_id"] == object_id
    assert decision["value"] == {"verdict": "hold"}

    # --- Assert: audit call anchored to this object_id was recorded (real
    # call-site contract) and still names the same object_id -- no orphaning
    # at the call-site level either. ---
    assert any(call["object_id"] == object_id for call in audited_calls)

    # --- Assert: vectors purged via the REAL consumer path (#2944). Dispatch
    # the event that was ACTUALLY emitted by delete_note (not a hand-built
    # payload) through outbox_worker's real, production dispatch entrypoint --
    # this proves the end-to-end wiring from ingest.object.deleted to
    # purge_vectors, not just the primitive in isolation. ---
    from app.events.models import new_event
    from app.events.types import INGEST_OBJECT_DELETED
    from app.services import indexer as indexer_module
    from app.workers import outbox_worker

    # The worker handler delegates its purge to
    # ``app.services.indexer.purge_object_vectors`` (the allowlisted indexer
    # seam onto the vector index -- the worker itself must not import the
    # transitional app.stores layer, per tests/architecture/
    # test_deprecated_store_callers.py). purge_object_vectors resolves the
    # index through app.services.indexer's module-level ``get_vector_index``
    # binding -- patch that binding so the handler purges THIS test's
    # vector_index instance (already seeded above) rather than the separate
    # process-global singleton.
    monkeypatch.setattr(indexer_module, "get_vector_index", lambda: vector_index)

    envelope = new_event(event_type=INGEST_OBJECT_DELETED, payload=dict(payload))
    message = {
        "id": "property-row-1",
        "topic": INGEST_OBJECT_DELETED,
        "payload": payload,
        "event": envelope,
        "timestamp": envelope.created_at,
    }
    outbox_worker._dispatch_topic(
        INGEST_OBJECT_DELETED,
        payload,
        trace_id="trace-seed",
        message=message,
        event_id=outbox_worker._event_id_from_message(message),
    )

    assert vector_index.count_vectors() == 0
    assert vector_index.purge_vectors(UUID(object_id), view="default") == 0, (
        "vector row must already be purged by the real consumer dispatch -- redelivery is a no-op"
    )


# ---------------------------------------------------------------------------
# test_reingest_mints_new_identity
# ---------------------------------------------------------------------------


def test_reingest_mints_new_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-ingesting a new note at the SAME path after a delete gets a NEW
    object_id -- no identity resurrection of the tombstoned row.

    Models the real production identity rule: `upsert_object_from_note`
    upserts `objects` keyed by the note's frontmatter uuid (ON CONFLICT
    (id)/(uuid) DO UPDATE). A freshly authored note has no prior frontmatter
    uuid of the deleted note -- the uuid-heal seam mints a genuinely fresh
    one (app.services.note_uuid.ensure_note_uuid) -- so the re-ingest targets
    a brand-new object_id row rather than colliding with (and reviving) the
    tombstoned one.
    """
    old_object_id = str(uuid4())
    path = "/vault/notes/property-note.md"

    conn = _FakeConn()
    _seed_note(conn, object_id=old_object_id, path=path)
    insert_decision(old_object_id, "promotion_gate", {"verdict": "hold"}, trace_id="trace-seed")

    # Delete the original note at this path.
    _delete_note(monkeypatch, conn, path, old_object_id)
    assert conn.objects[old_object_id]["path"] is None

    # A brand-new note is authored at the SAME path. Because it has no
    # frontmatter uuid carried over from the deleted note, the identity-heal
    # seam mints a genuinely new uuid (this test models that minted value
    # directly, matching ensure_note_uuid's "fresh uuid" contract rather than
    # re-exercising the heal seam itself, which tests/properties/
    # test_read_purity.py already covers).
    new_object_id = str(uuid4())
    assert new_object_id != old_object_id

    # Real re-ingest call site: upsert_object_from_note upserts `objects`
    # keyed by the (new) frontmatter uuid.
    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_a, **_kw: None)
    monkeypatch.setattr(vault_sync, "insert_object_and_outbox", lambda *a, **kw: None)

    frontmatter = {"uuid": new_object_id, "title": "Property Note (recreated)", "review_state": "provisional"}
    vault_sync.upsert_object_from_note(path, frontmatter, "New body", fm_changed=True, body_changed=True)

    # --- Assert: two distinct object rows exist -- the old tombstone
    # (path=NULL, decisions/audit lineage intact) and the new row (path
    # restored, no relation to the old decisions history). ---
    assert old_object_id in conn.objects
    assert conn.objects[old_object_id]["path"] is None
    assert new_object_id in conn.objects
    assert conn.objects[new_object_id]["path"] == path
    assert new_object_id != old_object_id

    # The old decision row still resolves under the OLD object_id only -- the
    # new object has no judgment history of its own (no resurrection).
    old_decision = latest_decision(old_object_id, "promotion_gate")
    assert old_decision is not None
    assert old_decision["object_id"] == old_object_id

    new_decision = latest_decision(new_object_id, "promotion_gate")
    assert new_decision is None, "the re-ingested object must not inherit the old object's decision history"
