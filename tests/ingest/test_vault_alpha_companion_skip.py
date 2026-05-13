"""
Tests for companion-based fingerprint skip and ignore_glob protection.

Covers:
- Re-ingest is skipped when companion content_hash matches current text sha256
- Companion notes under _system/companions/ are excluded by default ignore_glob
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.ingest.config import _BASE_IGNORES
from app.ingest.vault_alpha import run_vault_alpha_ingest, run_vault_alpha_ingest_paths
from app.services.companion_note import CompanionNote, companion_path, read_companion, write_companion
from app.stores import reset_store_backends


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    reset_store_backends()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        '---\ninclude_folders:\n  - "."\n---\n\nVault layout.\n',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fingerprint skip
# ---------------------------------------------------------------------------

def test_fingerprint_skip_when_content_hash_matches(tmp_path: Path, _mock_env: None) -> None:
    """Second ingest with identical content should be skipped (ingested==0)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_uuid = "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee"
    note_path = vault_root / "Notes" / "skip-me.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    body = "Stable content for fingerprint skip test."
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Skip Me\n---\n{body}\n",
        encoding="utf-8",
    )

    # First ingest — must succeed
    s1 = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert s1.ingested == 1

    # Verify companion was written with correct content_hash
    companion = read_companion(vault_root, note_uuid)
    assert companion is not None
    assert companion.content_hash == _sha256(body)

    # Second ingest — same content, should be skipped
    s2 = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert s2.ingested == 0, "unchanged content should be skipped via content_hash comparison"


def test_fingerprint_skip_not_triggered_when_content_changes(tmp_path: Path, _mock_env: None) -> None:
    """If content changes, ingest should NOT be skipped."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_uuid = "bbbb2222-cccc-dddd-eeee-ffffffffffff"
    note_path = vault_root / "Notes" / "change-me.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Change Me\n---\nOriginal content.\n",
        encoding="utf-8",
    )

    s1 = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert s1.ingested == 1

    # Modify content
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Change Me\n---\nModified content now.\n",
        encoding="utf-8",
    )

    s2 = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert s2.ingested == 1, "changed content must be re-ingested"


# ---------------------------------------------------------------------------
# Ignore glob — companion notes must not be ingested
# ---------------------------------------------------------------------------

def test_companion_dir_in_base_ignores() -> None:
    """_system/companions/** must be in the default ignore list."""
    assert "_system/companions/**" in _BASE_IGNORES


def test_companion_notes_excluded_from_full_ingest(tmp_path: Path, _mock_env: None) -> None:
    """A companion .md under _system/companions/ must not appear as a candidate."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    # Write a real note
    note_uuid = "cccc3333-dddd-eeee-ffff-aaaaaaaaaaaa"
    note_path = vault_root / "Notes" / "real.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Real Note\n---\nBody.\n",
        encoding="utf-8",
    )

    # Pre-create a companion note (simulates a previous ingest)
    companion = CompanionNote(
        uuid=note_uuid,
        source_ref="Notes/real.md",
        title="Real Note",
        content_hash="fakehash",
        ingest_state="tracked",
        last_ingested="2025-01-01T00:00:00+00:00",
        created_by_instance="",
    )
    write_companion(vault_root, companion)

    # Full ingest — companion should NOT be scanned as an input note
    summary = run_vault_alpha_ingest(vault_root, max_notes=100, force=True)

    # The companion file itself must not be in the processed list
    companion_rel = str(companion_path(note_uuid))
    assert companion_rel not in summary.processed_notes, (
        "companion notes must be excluded from ingest via ignore_glob"
    )
    # The real note should be ingested
    assert summary.ingested >= 1


def test_layout_system_companion_dir_added_to_ignore_glob(tmp_path: Path, _mock_env: None) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    note_uuid = "dddd4444-eeee-ffff-aaaa-bbbbbbbbbbbb"
    note_path = vault_root / "Notes" / "real.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Real Note\n---\nBody.\n",
        encoding="utf-8",
    )

    companion = CompanionNote(
        uuid=note_uuid,
        source_ref="Notes/real.md",
        title="Real Note",
        content_hash="fakehash",
        ingest_state="tracked",
        last_ingested="2025-01-01T00:00:00+00:00",
        created_by_instance="",
    )
    write_companion(vault_root, companion)

    summary = run_vault_alpha_ingest(vault_root, max_notes=100, force=True)

    assert f"⚙️ System/companions/{note_uuid}.md" not in summary.processed_notes
