"""AC coverage for #2990: watcher-detected vault deletions are reconciled.

The watcher computes a ``deleted`` path list every tick
(``app/watcher/vault_watcher.py::compute_changes`` / ``VaultWatcherResult``)
but until this change nothing consumed it: ``result.changed`` was ingested,
``result.deleted`` was discarded. Purge machinery already existed
(``app/services/indexer.py::purge_object_vectors``, the ``ingest.object.deleted``
outbox event, ``app/workers/outbox_worker.py::handle_ingest_object_deleted``)
but was only reachable from the app-initiated
``app/services/vault_sync.py::delete_note`` seam, never from a filesystem
deletion observed by the watcher -- ghost rows in ``store_objects`` /
``store_vector_index`` accumulated forever.

The fix wires ``run_watcher_tick`` to call the SAME ``vault_sync.delete_note``
seam for every watcher-detected deleted path, so watcher-observed deletions
get identical uuid resolution (file_state lookup by path), tombstoning, and
event emission as an app-initiated delete -- and therefore the same
idempotency (replaying against an already-purged path is a no-op because
``file_state`` no longer has a row for it).

Two ACs:

- ``test_fs_delete_purges_index_rows`` -- deleting a vault note that has
  store/vector rows results in those rows being purged via the
  watcher-seam -> outbox -> worker path, driven end-to-end against a fake
  Postgres-shaped connection (the established pattern for
  ``vault_sync.delete_note``, see ``tests/properties/test_tombstone_lineage.py``)
  and the real (memory-backend) vector index.
- ``test_run_watcher_tick_emits_deleted_tombstones`` -- the purge path is
  exercised from the REAL production ``run_watcher_tick`` entrypoint (not
  only the service-level ``delete_note`` call in isolation), proving the
  watcher tick actually calls the seam for each path in ``result.deleted``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.events.types import INGEST_OBJECT_DELETED
from app.services import vault_sync
from app.stores.memory import MemoryVectorIndex
from app.watcher import vault_watcher


# ---------------------------------------------------------------------------
# Fake connection modeling `objects` + `file_state`, mirroring the pattern
# established by tests/properties/test_tombstone_lineage.py (the same module
# vault_sync.delete_note issues raw SQL against, with no memory-backend port
# of its own).
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

        # MVR-05A0 (#4543): file_state statements lead with vault_binding_id.
        if normalized.startswith(
            "delete from file_state where vault_binding_id = %s and path = %s"
        ):
            _binding_id, path = params
            self.rowcount = 1 if self.conn.file_state.pop(path, None) else 0
            return
        if normalized.startswith("select id::text, count(*) over ()"):
            canonical_alias, uuid_value = params
            self._fetchone = (
                (uuid_value, 1, str(canonical_alias) in self.conn.store_objects)
                if uuid_value in self.conn.objects
                else None
            )
            return
        if normalized.startswith("select exists(select 1 from store_objects"):
            canonical_id, _id, uuid_value, expected, _again = params
            canonical = str(canonical_id) in self.conn.store_objects
            mirror = uuid_value in self.conn.objects
            self._fetchone = (canonical, mirror, canonical and self.conn.store_objects[str(canonical_id)]["source_ref"] == expected)
            return
        if normalized.startswith(
            "select count(*) from file_state where vault_binding_id = %s and uuid = %s"
        ):
            _binding_id, uuid_value = params
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
        if normalized.startswith("update store_objects"):
            source_ref, object_id = params
            row = self.conn.store_objects.get(str(object_id))
            if row is not None:
                row["source_ref"] = source_ref
                self.rowcount = 1
            return
        if normalized.startswith(
            "select path, uuid, fm_hash, body_hash, mtime from file_state "
            "where vault_binding_id = %s and path = %s"
        ):
            _binding_id, path = params
            self._fetchone = self.conn.file_state.get(path)
            return
        raise AssertionError(f"Unhandled SQL in fake conn: {normalized}")

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self._fetchone


class _FakeConn:
    def __init__(self) -> None:
        self.file_state: dict[str, dict[str, object]] = {}
        self.objects: dict[str, dict[str, object]] = {}
        self.store_objects: dict[str, dict[str, object]] = {}

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
def _stub_tick_ingest(monkeypatch: pytest.MonkeyPatch):
    """Isolate these tests from the process-global stores.

    run_watcher_tick's ingest step (run_vault_alpha_ingest_paths) writes to
    the process-global object store and vector index; letting it run for the
    tmp-vault notes here advances the global store-generation token (#2981)
    and pollutes downstream in-process suites (seen on CI: the eval golden
    benchmark's seeded corpus was force-rebuilt away mid-run, tripping the
    regression gate). These tests exercise deletion reconciliation, not
    ingest, so stub the ingest seam with a truthful summary.
    """
    from types import SimpleNamespace

    monkeypatch.setattr(
        vault_watcher,
        "run_vault_alpha_ingest_paths",
        lambda vault_root, paths, force=False: SimpleNamespace(ingested=len(list(paths)), errors=0),
    )


def _seed_file_state(conn: _FakeConn, *, object_id: str, path: str) -> None:
    conn.objects[object_id] = {"id": object_id, "kind": "note", "path": path}
    conn.store_objects[object_id] = {
        "object_id": object_id,
        "kind": "note",
        "source_ref": path,
    }
    conn.file_state[path] = {
        "path": path,
        "uuid": object_id,
        "fm_hash": "fm-hash",
        "body_hash": "body-hash",
        "mtime": datetime.now(timezone.utc),
    }


def _dispatch_delete_event(payload: dict) -> None:
    """Drive the real production consumer dispatch path for the deletion
    event vault_sync.delete_note emits (mirrors
    tests/workers/test_handle_ingest_object_deleted.py)."""
    from app.events.models import new_event
    from app.workers import outbox_worker

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


def test_fs_delete_purges_index_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: deleting a vault note that has store/vector rows results in
    those rows being purged via the watcher(vault_sync.delete_note)
    -> outbox -> worker path, and replaying the same deletion is a no-op
    (idempotent, per the issue's Constraints)."""
    object_id = str(uuid4())
    path = "/vault/Concepts/deleted-note.md"

    conn = _FakeConn()
    _seed_file_state(conn, object_id=object_id, path=path)

    emitted: list[tuple[dict, str, str | None]] = []
    monkeypatch.setattr(vault_sync, "_conn", lambda: conn)
    monkeypatch.setattr(vault_sync, "ensure_schema", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        vault_sync,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id, **kwargs: emitted.append((payload, topic, trace_id)),
    )

    from app.components.embeddings import EmbeddingIdentity

    identity = EmbeddingIdentity(provider="test", model="test-embed", dim=4, normalize=False)
    vector_index = MemoryVectorIndex()
    vector_index.upsert(
        UUID(object_id),
        kind="note",
        source_ref=path,
        payload={"title": "Deleted Note"},
        embedding=[0.1, 0.2, 0.3, 0.4],
        model="test-embed",
        identity=identity,
    )
    assert vector_index.count_vectors() == 1
    generation_before = vector_index.generation()

    # --- Act: this is exactly what run_watcher_tick now calls for every
    # watcher-detected deleted path. ---
    assert vault_sync.delete_note(path) is True

    assert len(emitted) == 1, "expected exactly one ingest.object.deleted emission"
    payload, topic, _trace = emitted[0]
    assert topic == INGEST_OBJECT_DELETED
    assert payload["uuid"] == object_id
    assert payload["deleted"] is True

    # Drive the real worker dispatch path with the event actually emitted.
    monkeypatch.setattr(
        "app.stores.get_vector_index",
        lambda: vector_index,
    )
    monkeypatch.setattr(
        "app.services.indexer.get_vector_index",
        lambda: vector_index,
    )
    _dispatch_delete_event(payload)

    assert vector_index.count_vectors() == 0, "deleted object's vectors must be purged"
    assert vector_index.generation() != generation_before, (
        "purge must advance the vector-index generation token so the "
        "retrieval hybrid cache revalidates (couples with #2981)"
    )

    # --- Idempotency: replaying the deletion for the same (now-purged) path
    # must be a no-op -- no file_state row left to match, so no new event. ---
    emitted.clear()
    assert vault_sync.delete_note(path) is False
    assert emitted == [], "replaying a deletion for an already-purged path must not re-emit"

    # Replaying the purge itself (at-least-once redelivery) must also be a
    # a no-op on the vector index (KERNEL-11).
    _dispatch_delete_event(payload)
    assert vector_index.count_vectors() == 0


def test_run_watcher_tick_emits_deleted_tombstones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2: the purge path is exercised from the production
    ``run_watcher_tick`` entrypoint, not only the service-level delete --
    i.e. run_watcher_tick itself must call the vault_sync.delete_note seam
    for every path in the watcher's computed ``deleted`` list."""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "Concepts" / "A.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Body", encoding="utf-8")

    outbox = tmp_path / "events.jsonl"
    telemetry_log = tmp_path / "watcher_run.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(telemetry_log))

    snapshot_path = vault / ".state.json"

    # First tick: establishes the snapshot with the note present. No
    # deletions yet, so the seam must not be called.
    calls: list[tuple[str,]] = []
    monkeypatch.setattr(
        vault_watcher, "delete_note", lambda path, **kw: (calls.append((path,)), True)[1]
    )

    summary_first, _ = vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )
    assert summary_first["deleted"] == 0
    assert calls == []

    # Delete the file on disk (never touched again -- only derived rows may
    # be purged) and run a second tick: the watcher must now observe the
    # deletion and call the production delete_note seam for that path.
    time.sleep(0.01)
    note.unlink()

    summary_second, _ = vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )

    assert summary_second["deleted"] == 1
    assert summary_second["deleted_purged"] == 1
    assert len(calls) == 1
    (deleted_path,) = calls[0]
    assert Path(deleted_path) == note

    # The vault file itself must never be recreated/touched by the watcher
    # reconciling the deletion -- only derived store rows are purged.
    assert not note.exists()

    # A third, no-op tick (nothing changed, nothing deleted) must not
    # re-invoke the seam -- the watcher's own snapshot no longer tracks the
    # removed path.
    summary_third, _ = vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )
    assert summary_third["deleted"] == 0
    assert len(calls) == 1


def test_run_watcher_tick_dry_run_never_purges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dry_run must never invoke the purge seam, even when a deletion is
    detected (dry-run is a preview, not an action)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "A.md"
    note.write_text("Body", encoding="utf-8")

    snapshot_path = vault / ".state.json"
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))

    calls: list[tuple[str,]] = []
    monkeypatch.setattr(
        vault_watcher, "delete_note", lambda path, **kw: (calls.append((path,)), True)[1]
    )

    vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )

    time.sleep(0.01)
    note.unlink()

    summary, _ = vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=True,
        max_notes=10,
        force=False,
    )

    assert summary["deleted"] == 1
    assert calls == [], "dry_run must never call the purge seam"


def test_run_watcher_tick_falls_back_to_derived_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A note ingested only through the tick's vault-alpha path has no
    file_state row, so delete_note cannot emit for it (returns False). The
    tick must then resolve the identity the way vault-alpha ingest derived
    it -- companion by source_ref when one survives, else the deterministic
    uuid5(rel_path) fallback -- and emit a delete_note-compatible
    ingest.object.deleted event itself."""
    import uuid as _uuid

    from app.ingest.vault_alpha import _VAULT_NOTE_UUID_NAMESPACE

    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "Concepts" / "B.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Body", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))
    # The patched producer below stands in for an outbox that accepts the
    # tombstone, so declare the runtime posture that matches it (#4214 D3):
    # deleted_purged may only be reported for a runtime where the tombstone is
    # actually delivered. Without this the tick correctly reports 0 purges.
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")
    snapshot_path = vault / ".state.json"

    # delete_note reports it could not identify/emit (no file_state row).
    monkeypatch.setattr(vault_watcher, "delete_note", lambda path, **kw: False)
    emitted: list[tuple[dict, str, object]] = []
    monkeypatch.setattr(
        vault_watcher,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id=None, **kw: emitted.append(
            (payload, topic, kw.get("observation"))
        ),
    )

    vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )
    assert emitted == []

    time.sleep(0.01)
    note.unlink()

    summary, _ = vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )

    assert summary["deleted"] == 1
    assert summary["deleted_purged"] == 1
    assert len(emitted) == 1
    payload, topic, observation = emitted[0]
    assert topic == INGEST_OBJECT_DELETED
    assert payload["deleted"] is True
    assert payload["path"] == str(note)
    # No companion survives for this note, so identity falls back to the
    # exact uuid vault-alpha ingest derives for a note without a
    # frontmatter/companion uuid: uuid5(namespace, rel_path).
    assert payload["uuid"] == str(_uuid.uuid5(_VAULT_NOTE_UUID_NAMESPACE, "Concepts/B.md"))
    # Idempotency key is scoped to the deleted version's last observed mtime.
    assert observation is not None


def test_run_watcher_tick_prefers_companion_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a companion note survives the deletion, its uuid (the canonical
    ingest identity) wins over the uuid5 fallback."""
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "Concepts" / "C.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Body", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))
    snapshot_path = vault / ".state.json"

    companion_uuid = str(uuid4())
    monkeypatch.setattr(vault_watcher, "delete_note", lambda path, **kw: False)
    monkeypatch.setattr(
        vault_watcher,
        "find_companion_by_source_ref",
        lambda root, source_ref: (
            type("C", (), {"uuid": companion_uuid})() if source_ref == "Concepts/C.md" else None
        ),
    )
    canonical_uuid = str(uuid4())
    monkeypatch.setattr(
        vault_watcher,
        "resolve_canonical_object_id",
        lambda vault_uuid: canonical_uuid,
    )
    emitted: list[dict] = []
    monkeypatch.setattr(
        vault_watcher,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id=None, **kw: emitted.append(payload),
    )

    vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )
    time.sleep(0.01)
    note.unlink()
    vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )

    assert len(emitted) == 1
    assert emitted[0]["uuid"] == canonical_uuid
    assert emitted[0]["object_id"] == canonical_uuid
    assert emitted[0]["vault_uuid"] == companion_uuid


def test_run_watcher_tick_rename_does_not_purge_live_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rename safety: when the resolved identity's companion points at a
    path that still exists (the rename target this tick already re-ingested),
    no tombstone is emitted -- an async purge would wipe the freshly
    re-ingested vectors with nothing to restore them."""
    vault = tmp_path / "vault"
    vault.mkdir()
    old_note = vault / "Concepts" / "Old.md"
    old_note.parent.mkdir(parents=True, exist_ok=True)
    old_note.write_text("Body", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))
    snapshot_path = vault / ".state.json"

    identity_uuid = str(uuid4())
    monkeypatch.setattr(vault_watcher, "delete_note", lambda path, **kw: False)
    monkeypatch.setattr(
        vault_watcher,
        "find_companion_by_source_ref",
        lambda root, source_ref: type("C", (), {"uuid": identity_uuid})(),
    )
    # The identity's companion now points at the rename target (updated by
    # this tick's ingest of the new path), which exists on disk.
    monkeypatch.setattr(
        vault_watcher,
        "read_companion",
        lambda root, u: (
            type("C", (), {"uuid": identity_uuid, "source_ref": "Concepts/New.md"})()
            if u == identity_uuid
            else None
        ),
    )
    emitted: list[dict] = []
    monkeypatch.setattr(
        vault_watcher,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id=None, **kw: emitted.append(payload),
    )

    vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )

    # Simulate the rename on disk: old gone, new present.
    time.sleep(0.01)
    new_note = vault / "Concepts" / "New.md"
    new_note.write_text("Body", encoding="utf-8")
    old_note.unlink()

    summary, _ = vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )

    assert summary["deleted"] == 1
    assert summary["deleted_purged"] == 0, "live renamed identity must not be purged"
    assert emitted == []
    assert new_note.exists() and not old_note.exists()
