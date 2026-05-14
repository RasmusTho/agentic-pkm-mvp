"""Tests for the Vault Action Layer: move_note_to_zone (inbox → workbench).

These tests do NOT require a live database, LLM, or Obsidian connection.
They run entirely against a tmp_path fixture with a minimal VaultLayout stub.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.vault.actions import MoveResult, move_note_to_zone
from app.vault.layout import VaultLayout
from app.write_guard import WriteGuard


pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_layout(vault_root: Path) -> VaultLayout:
    """Return a minimal VaultLayout pointing at tmp_path subdirectories."""
    return VaultLayout(
        system_folder="system",
        inbox_folder="inbox",
        desk_folder="workbench",
        root_folders=["system", "inbox", "workbench"],
        include_folders=None,
        ignore_glob=None,
        note_path=vault_root / "system" / "vault.layout.md",
    )


def _write_note(path: Path, content: str = "# Test Note\n\nHello.\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _permissive_write_guard() -> MagicMock:
    guard = MagicMock(spec=WriteGuard)
    guard.assert_writes_allowed.return_value = None  # no-op = allowed
    return guard


# ---------------------------------------------------------------------------
# AC1: happy path — note moves from inbox to workbench
# ---------------------------------------------------------------------------


def test_panel_instruction_moves_inbox_note_to_workbench(tmp_path: Path) -> None:
    """Note moves from Inbox to Workbench when panel instruction requests it."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    inbox = vault_root / layout.inbox_folder
    workbench = vault_root / layout.desk_folder
    workbench.mkdir(parents=True, exist_ok=True)

    note = _write_note(inbox / "my-note.md")

    result = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        intent_id="intent-001",
        write_guard=_permissive_write_guard(),
    )

    assert result.success is True
    assert result.skipped is False
    assert result.collision_resolved is False

    # Note is now in workbench, not in inbox
    expected_dest = workbench / "my-note.md"
    assert result.destination_path == expected_dest.resolve()
    assert expected_dest.exists()
    assert not note.exists()


# ---------------------------------------------------------------------------
# AC2: idempotency — re-running does not re-move or error
# ---------------------------------------------------------------------------


def test_workbench_move_action_is_idempotent(tmp_path: Path) -> None:
    """Re-running the move does not duplicate or re-move the note."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    inbox = vault_root / layout.inbox_folder
    workbench = vault_root / layout.desk_folder
    workbench.mkdir(parents=True, exist_ok=True)

    note = _write_note(inbox / "my-note.md")
    guard = _permissive_write_guard()

    # First move — should succeed
    result1 = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=guard,
    )
    assert result1.success is True
    assert result1.skipped is False

    # Second call with the original source path — note no longer exists there
    result2 = move_note_to_zone(
        note_path=note,  # original inbox path (already gone)
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=guard,
    )
    assert result2.success is True
    assert result2.skipped is True

    # Note is still in workbench exactly once
    workbench_note = workbench / "my-note.md"
    assert workbench_note.exists()
    assert not note.exists()


# ---------------------------------------------------------------------------
# AC3: collision handling — suffix appended, no overwrite
# ---------------------------------------------------------------------------


def test_workbench_move_action_handles_name_collision(tmp_path: Path) -> None:
    """When same name exists in Workbench, a suffix is appended without overwriting."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    inbox = vault_root / layout.inbox_folder
    workbench = vault_root / layout.desk_folder
    workbench.mkdir(parents=True, exist_ok=True)

    # Pre-create a note with the same name in workbench
    existing_content = "# Existing\n"
    existing = _write_note(workbench / "my-note.md", content=existing_content)

    note = _write_note(inbox / "my-note.md", content="# Incoming\n")

    result = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=_permissive_write_guard(),
    )

    assert result.success is True
    assert result.collision_resolved is True

    # Original workbench note is untouched
    assert existing.read_text(encoding="utf-8") == existing_content

    # Moved note received a collision suffix
    expected_collision = workbench / "my-note_2.md"
    assert result.destination_path == expected_collision.resolve()
    assert expected_collision.exists()
    assert "Incoming" in expected_collision.read_text(encoding="utf-8")

    # Source no longer in inbox
    assert not note.exists()


# ---------------------------------------------------------------------------
# AC4: receipt written into moved note
# ---------------------------------------------------------------------------


def test_workbench_move_action_writes_receipt(tmp_path: Path) -> None:
    """Moved note receives a receipt HTML comment with move metadata."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    inbox = vault_root / layout.inbox_folder
    workbench = vault_root / layout.desk_folder
    workbench.mkdir(parents=True, exist_ok=True)

    note = _write_note(inbox / "my-note.md", content="# Receipt Test\n\nBody.\n")

    result = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        intent_id="intent-receipt-123",
        write_guard=_permissive_write_guard(),
    )

    assert result.success is True
    assert result.receipt_path is not None

    moved_content = result.destination_path.read_text(encoding="utf-8")
    assert "vault-action-receipt" in moved_content
    assert "move_note_to_zone" in moved_content
    assert "panel_agent" in moved_content
    assert "intent-receipt-123" in moved_content
    assert "workbench" in moved_content
