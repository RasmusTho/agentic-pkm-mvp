"""
Tests that ingest/tracking writer does not create duplicate companion notes.

Issue #974: prod ingest writes duplicate companion notes in two system locations.

The tracking writer must write companion notes to exactly one canonical location
and never to the legacy _system/companions/ path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.services.companion_note import companion_path, find_duplicate_companions
from app.stores import reset_store_backends


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("COMPANION_RENAME_COOLDOWN_SECONDS", "0")
    reset_store_backends()


def _write_layout(vault_root: Path, system_folder: str = "⚙️ System") -> None:
    layout_path = vault_root / system_folder / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        f"---\nversion: '1'\nsystem_folder: '{system_folder}'\n"
        "inbox_folder: '📥 Inbox'\ndesk_folder: '🛠️ Workbench'\n---\n",
        encoding="utf-8",
    )


class TestTrackingWriterDoesNotCreateDuplicateCompanions:
    def test_tracking_writer_does_not_create_duplicate_companions(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        """Clean vault ingest must write companion to exactly one location."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "bbbb5555-6666-7777-8888-999900001111"
        note = vault_root / "Notes" / "Tracking Test Note.md"
        note.parent.mkdir()
        note.write_text(
            f"---\nuuid: {uuid}\ntitle: Tracking Test Note\n---\nSome content.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])

        # Canonical companion must exist
        canonical = vault_root / companion_path(uuid, vault_root)
        assert canonical.exists(), "canonical companion must be written after ingest"

        # Legacy companion must NOT exist
        legacy = vault_root / "_system" / "companions" / f"{uuid}.md"
        assert not legacy.exists(), (
            "_system/companions/ companion must not be written — dual-write removed"
        )

        # No duplicates via the detection API
        duplicates = find_duplicate_companions(vault_root)
        duplicate_uuids = [d.uuid for d in duplicates]
        assert uuid not in duplicate_uuids, (
            "find_duplicate_companions must not report a clean single-write as duplicate"
        )

    def test_second_ingest_does_not_create_duplicate(
        self, tmp_path: Path, _mock_env: None
    ) -> None:
        """Re-ingesting an already-tracked note must not create a second companion."""
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        _write_layout(vault_root)

        uuid = "cccc6666-7777-8888-9999-000011112222"
        note = vault_root / "Notes" / "Idempotent Note.md"
        note.parent.mkdir()
        note.write_text(
            f"---\nuuid: {uuid}\ntitle: Idempotent Note\n---\nContent.\n",
            encoding="utf-8",
        )

        run_vault_alpha_ingest_paths(vault_root, [note])
        run_vault_alpha_ingest_paths(vault_root, [note])

        # Canonical companion directory should have exactly one file for this uuid
        canonical_dir = (vault_root / companion_path(uuid, vault_root)).parent
        uuid_files = list(canonical_dir.glob(f"{uuid}.md"))
        assert len(uuid_files) == 1, f"expected exactly 1 companion, found {len(uuid_files)}"

        duplicates = find_duplicate_companions(vault_root)
        assert not any(d.uuid == uuid for d in duplicates)
