"""Companion continuity files cannot replay as human source publications (#5912)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app import objects
from app.components.embeddings import EmbeddingIdentity
from app.events.models import new_event
from app.events.types import INGEST_OBJECT_CREATED, INGEST_OBJECT_DELETED, INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from app.index.artifact_metadata import build_indexed_unit_payload
from app.objects import ObjectStore
from app.services import indexer
from app.services.outbox import write_outbox_event
from app.services.companion_note import companion_path
from app.stores.memory import MemoryVectorIndex
from app.workers import outbox_worker
from app.write_guard import DEFAULT_WRITE_GUARD
from tests.workers.test_outbox_worker_consumes_ingest import FakeOutboxConn, fake_conn as _fake_conn_fixture

SOURCE_UUID = "11111111-1111-4111-8111-111111111111"
SOURCE_BODY = "The retained source fact is companion-boundary-regression-5912."
SYSTEM_DIR = "Runtime/Identity"

pytestmark = pytest.mark.not_pg
fake_conn = _fake_conn_fixture


@pytest.fixture
def boundary_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MemoryVectorIndex:
    # Only the provider is substituted: production object publication, vector
    # replacement/purge, and the dispatched worker handlers remain real.
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", SYSTEM_DIR)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.delenv("INDEX_PERSIST_PATH", raising=False)
    monkeypatch.setattr(objects, "_MEMORY_STORE", {})
    monkeypatch.setattr("app.stores._resolve_backend", lambda: "memory")
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "running"})

    index = MemoryVectorIndex()
    identity = EmbeddingIdentity(provider="test", model="boundary-test", dim=4, normalize=False)
    embedder = SimpleNamespace(identity=identity, embed_text=lambda _: [1.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(indexer, "get_product_embedding_client", lambda: embedder)
    monkeypatch.setattr(indexer, "get_vector_index", lambda: index)
    return index


def write_source(vault: Path, body: str = SOURCE_BODY) -> Path:
    path = vault / "Inbox/source.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nuuid: {SOURCE_UUID}\ntitle: Source\n---\n\n{body}\n", encoding="utf-8")
    return path


def source_payload(vault: Path, note: Path) -> dict[str, object]:
    return {
        "vault_path": str(note),
        "relative_path": note.relative_to(vault).as_posix(),
        "mtime": note.stat().st_mtime,
        "hash": "queued-observation",
        "watcher": "registry:ingest",
    }


def dispatch(topic: str, payload: dict[str, object]) -> None:
    envelope = new_event(event_type=topic, payload=payload)
    message = {"id": "queued-boundary-event", "topic": topic, "payload": payload, "event": envelope}
    outbox_worker._dispatch_topic(topic, payload, trace_id="boundary-trace", message=message)


def assert_source_publication(index: MemoryVectorIndex, body: str = SOURCE_BODY) -> None:
    obj = ObjectStore().get_object(SOURCE_UUID)
    assert obj is not None
    assert obj.payload["content"] == body
    hits = index.search([1.0, 0.0, 0.0, 0.0], k=10, identity=index.get_identity())
    source_hits = [hit for hit in hits if hit.object_id == UUID(SOURCE_UUID)]
    assert len(source_hits) == 1
    assert source_hits[0].payload["content"] == body


@pytest.mark.parametrize("location", ["canonical", "legacy"])
@pytest.mark.parametrize("locator", ["absolute", "relative"])
def test_queued_companion_events_do_not_publish_source_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary_index: MemoryVectorIndex,
    location: str, locator: str,
) -> None:
    vault = tmp_path / "vault"
    source = write_source(vault)
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    dispatch(INGEST_VAULT_CHANGED, source_payload(vault, source))
    canonical = vault / companion_path(SOURCE_UUID, vault)
    companion = canonical if location == "canonical" else vault / f"_system/companions/{SOURCE_UUID}.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_bytes(canonical.read_bytes())
    retained_bytes = companion.read_bytes()
    original_object = deepcopy(ObjectStore().get_object(SOURCE_UUID))
    writes: list[object] = []
    reads: list[Path] = []
    original_reader = outbox_worker._stabilized_note_text

    def read_note(path: Path) -> str | None:
        reads.append(path)
        return original_reader(path)

    monkeypatch.setattr(outbox_worker, "_stabilized_note_text", read_note)
    monkeypatch.setattr(outbox_worker, "write_companion", lambda *_a: writes.append(_a))
    monkeypatch.setattr(outbox_worker, "run_panel_note_execution", lambda *_a, **_kw: SimpleNamespace(emitted_count=0))

    payload = source_payload(vault, companion)
    if locator == "relative":
        payload.pop("vault_path")
    # At-least-once replay must be a terminal no-op, including a panel refresh
    # (the real refresh would replace raw_text and source_ref at the shared UUID).
    for _ in range(2):
        dispatch(INGEST_VAULT_CHANGED, payload)
        dispatch(PANEL_SCAN_REQUESTED, payload)
    assert writes == []
    assert reads == []
    assert ObjectStore().get_object(SOURCE_UUID) == original_object
    assert companion.read_bytes() == retained_bytes
    assert_source_publication(boundary_index)

    # A healthy sibling source event still publishes and refreshes normally.
    changed_body = f"{SOURCE_BODY} Updated by the human."
    write_source(vault, changed_body)
    dispatch(INGEST_VAULT_CHANGED, source_payload(vault, source))
    dispatch(PANEL_SCAN_REQUESTED, source_payload(vault, source))
    assert_source_publication(boundary_index, changed_body)
    assert ObjectStore().get_object(SOURCE_UUID).payload["raw_text"] == source.read_text(encoding="utf-8")


@pytest.mark.parametrize("previous_locator", ["canonical", "legacy", "relative", "aliased", "ordinary", "foreign"])
def test_source_reingest_recovers_only_companion_contaminated_locator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary_index: MemoryVectorIndex,
    previous_locator: str,
) -> None:
    vault = tmp_path / "vault"
    source = write_source(vault)
    source_bytes = source.read_bytes()
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    dispatch(INGEST_VAULT_CHANGED, source_payload(vault, source))
    canonical = companion_path(SOURCE_UUID, vault)
    alias = tmp_path / "vault-alias"
    alias.symlink_to(vault, target_is_directory=True)
    locators = {
        "canonical": str(vault / canonical),
        "legacy": str(vault / f"_system/companions/{SOURCE_UUID}.md"),
        "relative": canonical.as_posix(),
        "aliased": str(alias / canonical),
        "ordinary": str(vault / "Notes/original-source.md"),
        "foreign": str(tmp_path / "other-vault" / canonical),
    }
    old_ref = locators[previous_locator]
    expected_ref = str(source) if previous_locator in {"canonical", "legacy", "relative", "aliased"} else old_ref
    store = ObjectStore()
    contaminated = store.get_object(SOURCE_UUID)
    assert contaminated is not None
    contaminated.source_ref = old_ref
    contaminated.payload = build_indexed_unit_payload(
        object_id=SOURCE_UUID, kind="note", source_ref=old_ref,
        payload={"content": "stale companion metadata"},
    )
    store.save_object(contaminated, emit_outbox=False)

    dispatch(INGEST_VAULT_CHANGED, source_payload(vault, source))
    assert_source_publication(boundary_index)
    restored = store.get_object(SOURCE_UUID)
    assert restored is not None
    assert restored.uuid == SOURCE_UUID
    assert restored.source_ref == expected_ref
    for payload in (restored.payload, boundary_index.all_rows()[0]["payload"]):
        assert payload["path"] == expected_ref
        assert payload["source_ref"] == expected_ref
        assert payload["provenance"]["source_ref"] == expected_ref
        assert payload["artifact_id"] == SOURCE_UUID
    assert boundary_index.all_rows()[0]["source_ref"] == expected_ref
    assert source.read_bytes() == source_bytes


@pytest.mark.parametrize("location", ["canonical", "legacy"])
@pytest.mark.parametrize("locator", ["absolute", "relative", "aliased-absolute", "explicit-root"])
def test_companion_delete_does_not_purge_source_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary_index: MemoryVectorIndex,
    fake_conn: FakeOutboxConn, location: str, locator: str,
) -> None:
    vault = tmp_path / "vault"
    source = write_source(vault)
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    dispatch(INGEST_VAULT_CHANGED, source_payload(vault, source))
    canonical = vault / companion_path(SOURCE_UUID, vault)
    companion = canonical if location == "canonical" else vault / f"_system/companions/{SOURCE_UUID}.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_bytes(canonical.read_bytes())
    retained_bytes = companion.read_bytes()
    original_object = deepcopy(ObjectStore().get_object(SOURCE_UUID))
    deleted_path = companion if locator in {"absolute", "explicit-root"} else companion.relative_to(vault)
    if locator == "aliased-absolute":
        alias = tmp_path / "vault-alias"
        alias.symlink_to(vault, target_is_directory=True)
        deleted_path = alias / companion.relative_to(vault)
    payload = {"uuid": SOURCE_UUID, "path": str(deleted_path), "deleted": True}
    if locator == "explicit-root":
        monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
        monkeypatch.delenv("VAULT_ROOT", raising=False)
        monkeypatch.setenv("STORE_BACKEND", "pg")
        event = new_event(event_type=INGEST_OBJECT_DELETED, payload=payload)
        write_outbox_event(event, idempotency_key=f"explicit-companion-delete:{location}")
        while fake_conn.undelivered_count():
            assert outbox_worker.run_once(vault_root=vault).state == "processed"
    else:
        for _ in range(2):
            dispatch(INGEST_OBJECT_DELETED, payload)
    assert_source_publication(boundary_index)
    assert ObjectStore().get_object(SOURCE_UUID) == original_object
    assert companion.read_bytes() == retained_bytes

    # Genuine source deletion keeps the existing vector purge and object
    # tombstone ownership: this consumer never deletes the object row itself.
    source.unlink()
    dispatch(INGEST_OBJECT_DELETED, {"uuid": SOURCE_UUID, "path": str(source), "deleted": True})
    assert boundary_index.count_vectors() == 0
    assert ObjectStore().get_object(SOURCE_UUID) == original_object
    assert companion.read_bytes() == retained_bytes


@pytest.mark.parametrize("location", ["canonical", "legacy"])
@pytest.mark.parametrize("locator", ["source_ref", "path"])
@pytest.mark.parametrize("form", ["absolute", "relative"])
def test_queued_companion_object_created_does_not_publish_source_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary_index: MemoryVectorIndex,
    fake_conn: FakeOutboxConn, location: str, locator: str, form: str,
) -> None:
    vault = tmp_path / "vault"
    source = write_source(vault)
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    dispatch(INGEST_VAULT_CHANGED, source_payload(vault, source))
    canonical = vault / companion_path(SOURCE_UUID, vault)
    companion = canonical if location == "canonical" else vault / f"_system/companions/{SOURCE_UUID}.md"
    companion.parent.mkdir(parents=True, exist_ok=True)
    companion.write_bytes(canonical.read_bytes())
    retained = companion.read_bytes()
    original = deepcopy(ObjectStore().get_object(SOURCE_UUID))
    # Drive the real DB consume/ack entrypoint with an explicit binding and
    # no root environment; the content was queued before the boundary repair.
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    raw_locator = companion.relative_to(vault) if form == "relative" else companion
    bad = {"uuid": SOURCE_UUID, "content": retained.decode(), locator: str(raw_locator)}
    good = {"uuid": SOURCE_UUID, "content": SOURCE_BODY, "source_ref": str(source), "title": "Source"}
    for index in range(2):
        write_outbox_event(
            new_event(event_type=INGEST_OBJECT_CREATED, payload=bad),
            idempotency_key=f"queued-companion-created:{location}:{locator}:{index}",
        )
    write_outbox_event(new_event(event_type=INGEST_OBJECT_CREATED, payload=good), idempotency_key="healthy-created")
    while fake_conn.undelivered_count():
        assert outbox_worker.run_once(vault_root=vault).state == "processed"
        assert_source_publication(boundary_index)
    assert ObjectStore().get_object(SOURCE_UUID).source_ref == original.source_ref
    assert companion.read_bytes() == retained
    assert source.read_text(encoding="utf-8").endswith(f"{SOURCE_BODY}\n")
