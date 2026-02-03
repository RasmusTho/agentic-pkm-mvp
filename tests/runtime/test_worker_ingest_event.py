from __future__ import annotations

import uuid
from pathlib import Path

from app.store.object_store import ObjectStore
from app.workers import outbox_worker
from scripts.yaml_roundtrip import load_frontmatter
from tests.helpers.pkm_alpha_helper import reset_memory_stores


def _write_layout_note(vault_root: Path, *, inbox_folder: str) -> None:
    system = vault_root / "⚙️ System"
    system.mkdir(parents=True, exist_ok=True)
    note = system / "vault.layout.md"
    note.write_text(
        "---\n"
        "version: '1'\n"
        "system_folder: '⚙️ System'\n"
        f"inbox_folder: '{inbox_folder}'\n"
        "desk_folder: '🛠️ Workbench'\n"
        "root_folders: []\n"
        "---\n\n"
        "# layout\n",
        encoding="utf-8",
    )


def test_handle_ingest_vault_changed_ingests_note(tmp_path: Path, monkeypatch) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    inbox = vault_root / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "_gap_test.md"

    note_uuid = str(uuid.uuid4())
    note_path.write_text(
        f"---\nuuid: [[{note_uuid}]]\n---\n\nGAP_TEST_MARKER: worker-ingest\n",
        encoding="utf-8",
    )

    payload = {
        "vault_path": str(note_path),
        "relative_path": "Inbox/_gap_test.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1

    obj = ObjectStore().get_object(note_uuid)
    assert obj is not None
    assert "GAP_TEST_MARKER" in str(obj.payload.get("raw_text") or obj.payload.get("text") or "")


def test_handle_ingest_vault_changed_heals_uuid_using_vault_layout_inbox(
    tmp_path: Path, monkeypatch
) -> None:
    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")

    vault_root = tmp_path / "vault"
    _write_layout_note(vault_root, inbox_folder="📥 Inbox")

    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    note_path = inbox / "uuidless.md"
    note_path.write_text(
        "---\n"
        "title: uuidless\n"
        "---\n\n"
        "Body\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)

    payload = {
        "vault_path": str(note_path),
        "relative_path": "📥 Inbox/uuidless.md",
        "hash": "test-hash",
        "mtime": 123.0,
    }

    summary = outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
    assert summary.ingested == 1

    healed_raw = note_path.read_text(encoding="utf-8")
    frontmatter, _ = load_frontmatter(healed_raw)
    assert isinstance(frontmatter, dict)
    healed_uuid = str(frontmatter.get("uuid") or "").strip()
    assert healed_uuid

    obj = ObjectStore().get_object(healed_uuid)
    assert obj is not None
