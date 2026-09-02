from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingest import vault_alpha
from app.ingest.vault_alpha import VaultAlphaSummary, run_vault_alpha_ingest_paths
from app.services import note_uuid
from app.write_guard import SOURCE_BACKED_REBUILD_ACTION, WriteGuard, WritesBlockedError
from app.stores import reset_store_backends
from scripts.yaml_roundtrip import load_frontmatter


def test_ingest_writes_uuid_for_notes_without_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_path = vault_root / "Notes" / "no-uuid.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        """---\ntitle: Missing UUID\n---\nContent without a UUID in frontmatter.\n""",
        encoding="utf-8",
    )
    system_dir = vault_root / "⚙️ System"
    system_dir.mkdir(parents=True)
    (system_dir / "vault.layout.md").write_text(
        "---\ninclude_folders:\n  - Notes\n---\n\nLayout for UUID-healing test.\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    reset_store_backends()

    summary = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert summary.ingested == 1

    frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    note_uuid = str(frontmatter.get("uuid") or "").strip()
    assert note_uuid
    uuid.UUID(note_uuid)


def test_uuid_repair_preserves_inline_frontmatter_scalars(tmp_path: Path) -> None:
    note = tmp_path / "inline.md"
    note.write_text(
        '---\ntitle: "Inline --- scalar"\n---\nBody\n', encoding="utf-8"
    )

    note_uuid.ensure_note_uuid(note, vault_root=tmp_path, preferred_uuid="11111111-1111-4111-8111-111111111111")

    repaired = note.read_text(encoding="utf-8")
    assert 'title: Inline --- scalar' in repaired or 'title: "Inline --- scalar"' in repaired
    from app.rebuildability import parse_markdown_text

    frontmatter, _ = parse_markdown_text(repaired)
    assert frontmatter["uuid"] == "11111111-1111-4111-8111-111111111111"


def test_targeted_ingest_uses_layout_admission_before_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    system_dir = vault_root / "⚙️ System"
    system_dir.mkdir(parents=True)
    root_note = vault_root / "excluded.md"
    root_note.write_text("---\ntitle: Excluded\n---\n\nBody\n", encoding="utf-8")
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
    captured: dict[str, object] = {}

    def fake_ingest_candidates(root, *, candidates, included_folders, force, resume_from, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(root=root, candidates=list(candidates), included_folders=included_folders)
        return VaultAlphaSummary(scanned=len(candidates), ingested=0, included_folders=included_folders)

    monkeypatch.setattr(vault_alpha, "_ingest_candidates", fake_ingest_candidates)
    summary = run_vault_alpha_ingest_paths(vault_root, [root_note])

    assert summary.scanned == 0
    assert captured["candidates"] == []


def test_source_backed_rebuild_ignores_ordinary_note_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_select(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured["max_notes"] = kwargs["max_notes"]
        return [], ["Notes"]

    def fake_ingest_candidates(*_args, **kwargs):  # type: ignore[no-untyped-def]
        return VaultAlphaSummary(scanned=0, ingested=0, included_folders=kwargs["included_folders"])

    monkeypatch.setattr(vault_alpha, "ensure_vault_layout", lambda _root: None)
    monkeypatch.setattr(
        vault_alpha,
        "resolve_ingest_config",
        lambda _root: SimpleNamespace(include_folders=["Notes"], ignore_glob=[]),
    )
    monkeypatch.setattr(vault_alpha, "_select_candidates", fake_select)
    monkeypatch.setattr(vault_alpha, "_ingest_candidates", fake_ingest_candidates)

    vault_alpha.run_vault_alpha_ingest(tmp_path, max_notes=1, source_backed_rebuild=True)

    assert captured["max_notes"] == 0


def test_source_backed_uuid_repair_uses_named_guard_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    note = tmp_path / "note.md"
    note.write_text("Body\n", encoding="utf-8")
    blocked = WriteGuard(snapshot_fn=lambda: {"state": "unhealthy", "reason": "unready"})
    captured: dict[str, object] = {}

    def fake_write(path, content, *, vault_root, action, expected_version):  # type: ignore[no-untyped-def]
        captured["action"] = action

    monkeypatch.setattr(note_uuid, "DEFAULT_WRITE_GUARD", blocked)
    monkeypatch.setattr(note_uuid, "write_note_from_absolute", fake_write)

    note_uuid.ensure_note_uuid(
        note,
        vault_root=tmp_path,
        preferred_uuid="rebuild-uuid",
        write_action=SOURCE_BACKED_REBUILD_ACTION,
    )
    assert captured["action"] == SOURCE_BACKED_REBUILD_ACTION

    note.write_text("Body\n", encoding="utf-8")
    with pytest.raises(WritesBlockedError):
        note_uuid.ensure_note_uuid(note, vault_root=tmp_path, preferred_uuid="ordinary-uuid")


def test_source_backed_rebuild_forces_projection_reconciliation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(vault_alpha, "ensure_vault_layout", lambda _root: None)
    monkeypatch.setattr(
        vault_alpha,
        "resolve_ingest_config",
        lambda _root: SimpleNamespace(include_folders=["Notes"], ignore_glob=[]),
    )
    monkeypatch.setattr(vault_alpha, "_select_candidates", lambda *_args, **_kwargs: ([], ["Notes"]))

    def fake_ingest_candidates(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return vault_alpha.VaultAlphaSummary(scanned=0, ingested=0, included_folders=[])

    monkeypatch.setattr(vault_alpha, "_ingest_candidates", fake_ingest_candidates)

    vault_alpha.run_vault_alpha_ingest(tmp_path, source_backed_rebuild=True)

    assert captured["force"] is True


def test_source_backed_ingest_uses_atomic_projection_reconciliation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    note_path = tmp_path / "Notes" / "recovered.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("---\ntitle: Recovered\n---\n\nBody\n", encoding="utf-8")
    captured: dict[str, object] = {}
    authoritative_id = uuid.uuid4()

    class RecoveryStore:
        def put_and_reconcile_source_backed(self, object_id, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(object_id=object_id, **kwargs)
            return str(authoritative_id)

        def put(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("source-backed recovery must use the atomic seam")

    monkeypatch.setattr(
        vault_alpha,
        "resolve_canonical_object_id",
        lambda _value: (_ for _ in ()).throw(
            AssertionError("source-backed recovery must not use ordinary alias resolution")
        ),
    )
    monkeypatch.setattr(vault_alpha, "get_object_store", lambda: RecoveryStore())
    monkeypatch.setattr(vault_alpha, "read_companion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "_find_companion_by_fingerprint", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        vault_alpha,
        "check_companion_eligibility",
        lambda *_args, **_kwargs: SimpleNamespace(
            eligible=False, reason="system_path", next_check_after=None
        ),
    )
    monkeypatch.setattr(vault_alpha, "classify_run", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(vault_alpha, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "append_jsonl", lambda *_args, **_kwargs: None)

    object_id = vault_alpha._ingest_single(
        note_path,
        vault_root=tmp_path,
        trace_id="trace",
        reconcile_existing_projection=True,
        write_companion_record=False,
    )

    assert object_id == str(authoritative_id)
    assert str(captured["object_id"]) != object_id
    assert captured["source_identity"] == "Notes/recovered.md"
    assert captured["source_ref"] == str(note_path)
    assert captured["vault_uuid"] != object_id


def test_source_backed_uuid_persistence_failure_is_fail_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    note_path = vault_root / "Notes" / "recovery.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("---\ntitle: Recovery\n---\n\nBody\n", encoding="utf-8")
    layout = vault_root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir(parents=True)
    layout.write_text("---\ninclude_folders:\n  - Notes\n---\n\nLayout.\n", encoding="utf-8")

    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()

    def refuse_uuid_write(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(vault_alpha, "ensure_note_uuid", refuse_uuid_write)
    monkeypatch.setattr(
        vault_alpha,
        "_ingest_single",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recovery must not project a note without durable UUID")
        ),
    )

    with pytest.raises(PermissionError, match="permission denied"):
        vault_alpha.run_vault_alpha_ingest_paths(
            vault_root, [note_path], source_backed_rebuild=True
        )


def test_source_backed_rebuild_rejects_duplicate_declared_uuid_before_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    notes_dir = vault_root / "Notes"
    notes_dir.mkdir(parents=True)
    shared_uuid = str(uuid.uuid4())
    for name in ("first.md", "second.md"):
        (notes_dir / name).write_text(
            f"---\nuuid: {shared_uuid}\ntitle: {name}\n---\n\nBody.\n",
            encoding="utf-8",
        )
    layout = vault_root / "⚙️ System" / "vault.layout.md"
    layout.parent.mkdir(parents=True)
    layout.write_text("---\ninclude_folders:\n  - Notes\n---\n\nLayout.\n", encoding="utf-8")

    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    monkeypatch.setattr(
        vault_alpha,
        "_ingest_single",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("duplicate claims must be rejected before projection writes")
        ),
    )

    with pytest.raises(RuntimeError, match="duplicate retained UUID claim"):
        vault_alpha.run_vault_alpha_ingest(vault_root, source_backed_rebuild=True)


def test_source_backed_locked_retry_forwards_recovery_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(vault_alpha, "ensure_vault_layout", lambda _root: None)
    monkeypatch.setattr(vault_alpha, "_read_locked_paths", lambda: ["Notes/retry.md"])

    def fake_paths(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return vault_alpha.VaultAlphaSummary(
            scanned=1, ingested=1, included_folders=["Notes"], processed_notes=["Notes/retry.md"]
        )

    monkeypatch.setattr(vault_alpha, "run_vault_alpha_ingest_paths", fake_paths)
    monkeypatch.setattr(vault_alpha, "_write_locked_paths", lambda _paths: None)

    vault_alpha.run_vault_alpha_ingest_locked_only(tmp_path, source_backed_rebuild=True)

    assert captured["source_backed_rebuild"] is True
    assert captured["force"] is True
