"""
Verifies that vault_alpha ingest writes a companion note (replacing the old VaultMirror).

Replaces the legacy test_vault_alpha_mirror_port.py which tested _write_mirror().
The companion note is now the system identity surface for each vault note.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.services.companion_note import companion_path, read_companion
from app.stores import reset_store_backends


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    # Disable companion cooldown so tests with freshly-created files still get companions.
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    reset_store_backends()


def test_ingest_writes_companion_note(tmp_path: Path, _mock_env: None) -> None:
    """After ingest the companion file must exist under _system/companions/<uuid>.md."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_uuid = "aaaabbbb-cccc-dddd-eeee-111111111111"
    note_path = vault_root / "Concepts" / "Example.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Example\n---\nSome content here.\n",
        encoding="utf-8",
    )

    summary = run_vault_alpha_ingest_paths(vault_root, [note_path])

    assert summary.ingested == 1
    companion = read_companion(vault_root, note_uuid)
    assert companion is not None, "companion note should have been created by ingest"
    assert companion.uuid == note_uuid
    assert companion.source_ref == "Concepts/Example.md"
    assert companion.ingest_state == "tracked"
    assert companion.content_hash  # non-empty sha256


def test_ingest_companion_lives_at_flat_uuid_path(tmp_path: Path, _mock_env: None) -> None:
    """Companion file must be at _system/companions/<uuid>.md — NOT under System/Metadata/VaultMirror."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_uuid = "12341234-5678-5678-5678-abcdabcdabcd"
    note_path = vault_root / "Cards" / "Deep" / "nested.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Nested\n---\nNested content.\n",
        encoding="utf-8",
    )

    run_vault_alpha_ingest_paths(vault_root, [note_path])

    # Use vault_root to resolve the layout-aware canonical companion path.
    expected_companion = vault_root / companion_path(note_uuid, vault_root)
    assert expected_companion.exists(), f"companion not found at {expected_companion}"

    # Legacy paths must NOT be written (dual-write removed).
    legacy_companion = vault_root / "_system" / "companions" / f"{note_uuid}.md"
    assert not legacy_companion.exists(), "_system/companions/ must not be written"
    legacy_root = vault_root / "System" / "Metadata" / "VaultMirror"
    assert not legacy_root.exists(), "VaultMirror directory must not be created"


def test_ingest_companion_has_no_forbidden_fields(tmp_path: Path, _mock_env: None) -> None:
    """Companion must not contain review_state, maturity, or ingest_fingerprint (dict)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_uuid = "deadbeef-dead-beef-dead-beefdeadbeef"
    note_path = vault_root / "Notes" / "policy-check.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\nuuid: {note_uuid}\ntitle: Policy Check\nreview_state: provisional\nmaturity: note\n---\nBody.\n",
        encoding="utf-8",
    )

    run_vault_alpha_ingest_paths(vault_root, [note_path])

    # Use vault_root-aware path to find the canonical companion.
    companion_file = vault_root / companion_path(note_uuid, vault_root)
    text = companion_file.read_text(encoding="utf-8")
    assert "review_state" not in text, "companion must not copy review_state from vault note"
    assert "maturity" not in text, "companion must not copy maturity from vault note"
    assert "ingest_fingerprint" not in text, "companion must not use legacy ingest_fingerprint dict"
