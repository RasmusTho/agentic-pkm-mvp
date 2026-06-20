"""
Tests for cold rebuild from vault (issue #2254).

The cold-rebuild path is triggered inside ``_ingest_candidates`` when:
  - the store is empty (count == 0), AND
  - at least one companion note exists in the vault's companions dir.

This bypasses the watcher's per-note mtime / fingerprint skip so that a
store reset (e.g. container recreation) can be recovered by re-ingesting
every vault note idempotently.

Covers:
- Given N vault notes + empty store + companions dir populated, cold rebuild
  ingests all N notes (each UUID appears in the store after the run).
- Running the rebuild again (second pass) is idempotent: the store object count
  stays the same (no duplicate rows added).
- When the store is already non-empty, the cold-rebuild flag does NOT fire:
  unchanged notes are skipped via normal fingerprint dedup.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest
from app.services.companion_note import CompanionNote, write_companion
from app.stores import get_object_store, reset_store_backends


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    # Disable companion cooldown so freshly-created test fixtures get companions.
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    reset_store_backends()


def _write_layout(vault_root: Path) -> None:
    """Write a vault.layout.md that includes the whole vault (dot-includes)."""
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        '---\ninclude_folders:\n  - "."\n---\n\nVault layout for cold-rebuild test.\n',
        encoding="utf-8",
    )


def _seed_vault(vault_root: Path, note_count: int) -> list[str]:
    """Write ``note_count`` markdown notes and pre-create their companions.

    Returns the list of note UUIDs written.  Companions are created *before*
    the ingest run so the cold-rebuild trigger fires (companions dir non-empty
    + store empty).
    """
    vault_root.mkdir(parents=True, exist_ok=True)
    _write_layout(vault_root)

    uuids: list[str] = []
    for i in range(note_count):
        note_uuid = f"aabbccdd-0000-0000-0000-{i:012d}"
        note_path = vault_root / "Notes" / f"note-{i:03d}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(
            f"---\nuuid: {note_uuid}\ntitle: Test Note {i}\n---\nBody of note {i}.\n",
            encoding="utf-8",
        )
        companion = CompanionNote(
            uuid=note_uuid,
            source_ref=f"Notes/note-{i:03d}.md",
            title=f"Test Note {i}",
            content_hash="placeholder",
            ingest_state="tracked",
            last_ingested="2026-01-01T00:00:00+00:00",
            created_by_instance="test",
        )
        write_companion(vault_root, companion)
        uuids.append(note_uuid)
    return uuids


# ---------------------------------------------------------------------------
# Cold rebuild tests
# ---------------------------------------------------------------------------


def test_cold_rebuild_ingests_all_notes(tmp_path: Path) -> None:
    """Cold rebuild from empty store must ingest every vault note by UUID."""
    note_count = 5
    vault_root = tmp_path / "vault"
    note_uuids = _seed_vault(vault_root, note_count)

    # Precondition: store is empty.
    store = get_object_store()
    assert store.count_objects() == 0, "store must be empty before cold rebuild"

    summary = run_vault_alpha_ingest(vault_root, max_notes=note_count + 20, force=False)

    # All tracked note UUIDs must appear in the store.
    for raw_uuid in note_uuids:
        parsed = UUID(raw_uuid)
        assert store.get(parsed) is not None, (
            f"cold rebuild must have ingested note {raw_uuid}"
        )

    # At least note_count objects in the store (system notes may also be there).
    assert store.count_objects() >= note_count, (
        f"store must have at least {note_count} objects after cold rebuild; "
        f"got {store.count_objects()}"
    )
    # The cold rebuild message must have been emitted (stdout checked via summary).
    assert summary.ingested >= note_count, (
        f"cold rebuild must ingest at least {note_count} notes; got {summary.ingested}"
    )


def test_cold_rebuild_is_idempotent(tmp_path: Path) -> None:
    """Running the rebuild a second time must not add new store objects."""
    note_count = 4
    vault_root = tmp_path / "vault"
    note_uuids = _seed_vault(vault_root, note_count)

    store = get_object_store()

    # First pass — cold rebuild (store empty).
    summary1 = run_vault_alpha_ingest(vault_root, max_notes=note_count + 20, force=False)
    assert summary1.ingested >= note_count

    count_after_first = store.count_objects()
    assert count_after_first >= note_count

    # Second pass — store is no longer empty; normal dedup applies.
    run_vault_alpha_ingest(vault_root, max_notes=note_count + 20, force=False)

    count_after_second = store.count_objects()
    assert count_after_second == count_after_first, (
        f"second pass must not create additional objects; "
        f"first={count_after_first}, second={count_after_second}"
    )
    # All tracked notes must still be present.
    for raw_uuid in note_uuids:
        parsed = UUID(raw_uuid)
        assert store.get(parsed) is not None


def test_cold_rebuild_not_triggered_when_store_has_objects(tmp_path: Path) -> None:
    """When the store is non-empty the cold-rebuild path must NOT fire.

    Force=False with populated store and companions present: unchanged notes
    are skipped via normal fingerprint dedup (summary.ingested == 0 for the
    tracked notes).
    """
    note_count = 3
    vault_root = tmp_path / "vault"
    _seed_vault(vault_root, note_count)

    store = get_object_store()

    # Pre-populate the store with a force pass to simulate a healthy store.
    run_vault_alpha_ingest(vault_root, max_notes=note_count + 20, force=True)
    count_after_force = store.count_objects()
    assert count_after_force >= note_count

    # Non-forced pass with populated store — should NOT do a cold rebuild;
    # ingested count must be 0 (all content unchanged, fingerprints match).
    summary = run_vault_alpha_ingest(vault_root, max_notes=note_count + 20, force=False)
    assert summary.ingested == 0, (
        "with populated store, normal dedup must prevent re-ingest of unchanged notes"
    )
    # Object count must not grow.
    assert store.count_objects() == count_after_force
