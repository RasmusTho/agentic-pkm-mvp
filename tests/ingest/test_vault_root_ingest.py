import os
import uuid
from pathlib import Path

import pytest

from app.ingest import vault_alpha, vault_root
from app.ingest.vault_root import ingest_vault_root, iter_vault_root_markdown
from app.observability.ingest_meta import reset_ingest_meta
from app.observability.status_service import get_system_status
from app.stores import get_object_store, reset_store_backends


def test_iter_vault_root_filters_and_limits(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("A", encoding="utf-8")
    (tmp_path / "b.md").write_text("B", encoding="utf-8")
    (tmp_path / "note.txt").write_text("C", encoding="utf-8")
    (tmp_path / ".hidden.md").write_text("hidden", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "c.md").write_text("Ignored", encoding="utf-8")

    files = list(iter_vault_root_markdown(tmp_path))
    assert [p.name for p in files] == ["a.md", "b.md"]

    limited = list(iter_vault_root_markdown(tmp_path, limit=1))
    assert [p.name for p in limited] == ["a.md"]


def test_ingest_vault_root_updates_status_and_store(tmp_path: Path, monkeypatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "first.md").write_text("# First\nContent", encoding="utf-8")
    (vault_root / "second.md").write_text("# Second\nMore", encoding="utf-8")

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}')
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("INGEST_STATUS_PATH", str(tmp_path / "ingest_status.json"))

    reset_store_backends()
    reset_ingest_meta()

    ingested = ingest_vault_root(vault_root, limit=2)
    assert ingested == 2

    store = get_object_store()
    assert len(getattr(store, "_objects", {})) >= 2

    status = get_system_status()
    assert status.ingestion.last_run_at is not None
    assert status.ingestion.last_run_ok is True


def test_ingest_vault_root_honors_layout_admission_for_root_files(
    tmp_path: Path, monkeypatch
) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "⚙️ System"
    system_dir.mkdir(parents=True)
    (vault_root / "root-note.md").write_text("# Root\nBody", encoding="utf-8")
    (system_dir / "vault.layout.md").write_text(
        "---\n"
        "system_folder: ⚙️ System\n"
        "inbox_folder: 📥 Inbox\n"
        "desk_folder: 🛠️ Workbench\n"
        "include_folders:\n"
        "  - Notes\n"
        "---\n\nLayout.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INGEST_STATUS_PATH", str(tmp_path / "ingest_status.json"))
    seen: list[Path] = []
    monkeypatch.setattr(
        "app.ingest.vault_root._ingest_file",
        lambda path, *, trace_id, vault_root=None: seen.append(path),
    )

    assert ingest_vault_root(vault_root) == 0
    assert seen == []


def test_ingest_vault_root_reuses_stable_product_identity_on_repeat(
    tmp_path: Path, monkeypatch
) -> None:
    from app.ingest import vault_root

    vault_root_path = tmp_path / "vault"
    vault_root_path.mkdir()
    note_path = vault_root_path / "root-note.md"
    note_path.write_text("# Root\nMeaning-bearing body", encoding="utf-8")
    upserted_ids: list[str] = []
    stored_ids: list[uuid.UUID] = []

    class FakeObjects:
        def upsert(self, *, id=None, **_kwargs):  # type: ignore[no-untyped-def]
            upserted_ids.append(str(id))
            return {"id": id}

    class FakeStore:
        def put(self, object_id, **_kwargs):  # type: ignore[no-untyped-def]
            stored_ids.append(object_id)

    def fake_normalize(_path, *, trace_id):  # type: ignore[no-untyped-def]
        fresh_id = str(uuid.uuid4())
        return {
            "object_id": fresh_id,
            "uuid": fresh_id,
            "core6": {"id": fresh_id, "title": "Root"},
            "payload": {"raw_text": "# Root\nMeaning-bearing body"},
        }

    monkeypatch.setattr(vault_root, "normalize_run", fake_normalize)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(vault_root, "resolve_canonical_object_id", lambda value: value)
    monkeypatch.setattr(vault_root, "get_stores", lambda: (FakeObjects(), None))
    monkeypatch.setattr(vault_root, "get_object_store", lambda: FakeStore())
    monkeypatch.setattr(vault_root, "classify_run", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(vault_root, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(vault_root, "append_jsonl", lambda *_args, **_kwargs: None)

    vault_root._ingest_file(note_path, trace_id="trace", vault_root=vault_root_path)
    vault_root._ingest_file(note_path, trace_id="trace", vault_root=vault_root_path)

    assert len(upserted_ids) == 2
    assert upserted_ids[0] == upserted_ids[1]
    assert len(stored_ids) == 2
    assert stored_ids[0] == stored_ids[1]


@pytest.mark.parametrize(
    "identity_key,identity_value",
    [
        ("id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("uuid", ["[[bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb]]"]),
    ],
)
def test_vault_root_and_vault_alpha_resolve_declared_identity_the_same_way(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_key: str,
    identity_value: object,
) -> None:
    vault_root_path = tmp_path / "vault"
    vault_root_path.mkdir()
    note_path = vault_root_path / "root-note.md"
    note_path.write_text(
        f"---\n{identity_key}: {identity_value!r}\n---\n\nMeaning-bearing body.\n",
        encoding="utf-8",
    )
    root_ids: list[str] = []

    class FakeObjects:
        def upsert(self, *, id=None, **_kwargs):  # type: ignore[no-untyped-def]
            root_ids.append(str(id))
            return {"id": id}

    class FakeStore:
        def put(self, object_id, **_kwargs):  # type: ignore[no-untyped-def]
            del object_id

    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(vault_root, "resolve_canonical_object_id", lambda value: value)
    monkeypatch.setattr(vault_root, "get_stores", lambda: (FakeObjects(), None))
    monkeypatch.setattr(vault_root, "get_object_store", lambda: FakeStore())
    monkeypatch.setattr(
        vault_root,
        "normalize_run",
        lambda *_args, **_kwargs: {
            "object_id": str(uuid.uuid4()),
            "core6": {"title": "Root"},
            "payload": {},
        },
    )
    monkeypatch.setattr(vault_root, "classify_run", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(vault_root, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(vault_root, "append_jsonl", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "resolve_canonical_object_id", lambda value: value)
    monkeypatch.setattr(vault_alpha, "read_companion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "_find_companion_by_fingerprint", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        vault_alpha,
        "load_companion_settings",
        lambda *_args, **_kwargs: type(
            "Settings",
            (),
            {"rename_cooldown_seconds": 0.0, "create_cooldown_seconds": 0.0},
        )(),
    )
    monkeypatch.setattr(
        vault_alpha,
        "check_companion_eligibility",
        lambda *_args, **_kwargs: type(
            "Eligibility",
            (),
            {"eligible": False, "reason": "system_path", "next_check_after": None},
        )(),
    )
    monkeypatch.setattr(
        vault_alpha,
        "ObjectStore",
        lambda: type("LegacyStore", (), {"save_object": lambda self, *args, **kwargs: None})(),
    )
    monkeypatch.setattr(vault_alpha, "classify_run", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(vault_alpha, "get_object_store", lambda: FakeStore())
    monkeypatch.setattr(vault_alpha, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "append_jsonl", lambda *_args, **_kwargs: None)

    vault_root._ingest_file(note_path, trace_id="trace", vault_root=vault_root_path)
    alpha_id = vault_alpha._ingest_single(
        note_path,
        vault_root=vault_root_path,
        trace_id="trace",
        write_companion_record=False,
    )

    assert root_ids == [alpha_id]
