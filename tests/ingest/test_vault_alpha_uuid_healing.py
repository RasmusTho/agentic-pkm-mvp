from __future__ import annotations

import uuid
from pathlib import Path

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
