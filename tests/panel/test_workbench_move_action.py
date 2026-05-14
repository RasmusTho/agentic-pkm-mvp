"""Tests for the Vault Action Layer: move_note_to_zone (inbox → workbench).

These tests do NOT require a live database, LLM, or Obsidian connection.
They run entirely against a tmp_path fixture with a minimal VaultLayout stub.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.vault.actions import move_note_to_zone
from app.vault.layout import VaultLayout
from app.write_guard import WriteGuard, WritesBlockedError


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


def _blocking_write_guard() -> MagicMock:
    guard = MagicMock(spec=WriteGuard)
    guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "blocked", "test: writes blocked", "move_note_to_zone"
    )
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
    assert result.mutation_applied is True
    assert result.collision_resolved is False

    expected_dest = workbench / "my-note.md"
    assert result.destination_path == expected_dest.resolve()
    assert expected_dest.exists()
    assert not note.exists()


# ---------------------------------------------------------------------------
# AC2: idempotency — re-running does not re-move or error
# ---------------------------------------------------------------------------


def test_workbench_move_action_is_idempotent(tmp_path: Path) -> None:
    """Re-running with the original source path returns source_missing_unverified.

    Without receipt/uuid evidence we cannot distinguish a prior successful move
    from a deletion or manual relocation, so the conservative result is
    source_missing_unverified with success=False.
    """
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    inbox = vault_root / layout.inbox_folder
    workbench = vault_root / layout.desk_folder
    workbench.mkdir(parents=True, exist_ok=True)

    note = _write_note(inbox / "my-note.md")
    guard = _permissive_write_guard()

    result1 = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=guard,
    )
    assert result1.success is True
    assert result1.mutation_applied is True

    # Second call: source gone — conservative rule; cannot verify without receipt/uuid.
    result2 = move_note_to_zone(
        note_path=note,  # original inbox path (already gone)
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=guard,
    )
    assert result2.skipped is True
    assert result2.mutation_applied is False
    assert result2.reason == "source_missing_unverified"
    assert result2.success is False  # conservative: cannot verify without evidence

    # Note is still in workbench from the first move.
    assert (workbench / "my-note.md").exists()
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
    assert existing.read_text(encoding="utf-8") == existing_content

    expected_collision = workbench / "my-note_2.md"
    assert result.destination_path == expected_collision.resolve()
    assert expected_collision.exists()
    assert "Incoming" in expected_collision.read_text(encoding="utf-8")
    assert not note.exists()


def test_collision_rerun_does_not_falsely_verify_idempotency(tmp_path: Path) -> None:
    """Rerun after a collision move must NOT return already_moved_verified.

    Scenario:
    - workbench/my-note.md already exists (pre-existing unrelated file).
    - inbox/my-note.md is moved to workbench/my-note_2.md (collision resolved).
    - Rerun with original source path: source gone, workbench/my-note.md present.
    - Must NOT return already_moved_verified — that file is not the moved artifact.
    """
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    inbox = vault_root / layout.inbox_folder
    workbench = vault_root / layout.desk_folder
    workbench.mkdir(parents=True, exist_ok=True)

    # Pre-existing file with the same name in workbench.
    _write_note(workbench / "my-note.md", content="# Pre-existing\n")
    note = _write_note(inbox / "my-note.md", content="# Incoming\n")
    guard = _permissive_write_guard()

    # First move — lands at my-note_2.md due to collision.
    result1 = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=guard,
    )
    assert result1.success is True
    assert result1.collision_resolved is True
    assert (workbench / "my-note_2.md").exists()
    assert not note.exists()

    # Rerun: source missing, workbench/my-note.md present (pre-existing, not our artifact).
    result2 = move_note_to_zone(
        note_path=note,  # original path, no longer exists
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=guard,
    )
    # Must not falsely claim the pre-existing workbench/my-note.md is our moved artifact.
    assert result2.reason != "already_moved_verified", (
        "Collision rerun must not return already_moved_verified based solely on "
        "workbench/my-note.md presence — that file is a pre-existing artifact, "
        "not the collision-resolved my-note_2.md"
    )
    assert result2.skipped is True
    assert result2.mutation_applied is False


# ---------------------------------------------------------------------------
# AC4: receipt written into moved note
# ---------------------------------------------------------------------------


def test_workbench_move_action_writes_receipt(tmp_path: Path) -> None:
    """Moved note receives a receipt HTML comment with vault-relative paths."""
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
        trace_id="trace-456",
        write_guard=_permissive_write_guard(),
    )

    assert result.success is True
    assert result.receipt_written is True
    assert result.receipt_path is not None

    moved_content = result.destination_path.read_text(encoding="utf-8")
    assert "vault-action-receipt" in moved_content
    assert "move_note_to_zone" in moved_content
    assert "panel_agent" in moved_content
    assert "intent-receipt-123" in moved_content
    assert "trace-456" in moved_content
    assert "workbench" in moved_content
    # Receipt must use vault-relative paths, not absolute machine paths.
    assert str(vault_root) not in moved_content, (
        "Receipt must not embed absolute vault_root paths"
    )
    # Expect relative paths like "inbox/my-note.md" and "workbench/my-note.md"
    assert "inbox/my-note.md" in moved_content
    assert "workbench/my-note.md" in moved_content


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------


def test_wrong_source_zone_is_rejected(tmp_path: Path) -> None:
    """Note not in inbox zone is rejected without moving."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    # Place note in workbench (not inbox) — wrong source zone.
    note = _write_note(vault_root / layout.desk_folder / "already-in-workbench.md")

    result = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=_permissive_write_guard(),
    )

    assert result.success is False
    assert result.mutation_applied is False
    assert "source_zone_invalid" in result.reason
    assert note.exists(), "Note must not be moved when source zone is invalid"


def test_wrong_destination_zone_is_rejected(tmp_path: Path) -> None:
    """Destination zone other than workbench is rejected without moving."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    note = _write_note(vault_root / layout.inbox_folder / "my-note.md")

    result = move_note_to_zone(
        note_path=note,
        destination_zone="archive",  # not supported in this slice
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=_permissive_write_guard(),
    )

    assert result.success is False
    assert result.mutation_applied is False
    assert "destination_zone_invalid" in result.reason
    assert note.exists(), "Note must not be moved when destination zone is invalid"


def test_write_guard_denied_means_no_move(tmp_path: Path) -> None:
    """Write guard denial prevents the move and returns success=False."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    note = _write_note(vault_root / layout.inbox_folder / "my-note.md")

    result = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=_blocking_write_guard(),
    )

    assert result.success is False
    assert result.mutation_applied is False
    assert "write_guard_denied" in result.reason
    assert note.exists(), "Note must not be moved when write guard denies"


def test_source_missing_not_reported_as_clean_success(tmp_path: Path) -> None:
    """Source path missing with no destination evidence returns an unverified reason."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    # Fabricate a source path that never existed.
    note = vault_root / layout.inbox_folder / "ghost-note.md"

    result = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=_permissive_write_guard(),
    )

    # Must not return success=True with reason="ok" when source is unverifiably missing.
    assert result.success is False or "unverified" in result.reason, (
        "A missing source with no destination evidence must not be reported as clean success; "
        f"got success={result.success}, reason={result.reason!r}"
    )
    assert result.mutation_applied is False


def test_receipt_failure_not_reported_as_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Receipt write failure returns moved_without_receipt, not reason='ok'."""
    vault_root = tmp_path / "vault"
    layout = _make_layout(vault_root)
    inbox = vault_root / layout.inbox_folder
    workbench = vault_root / layout.desk_folder
    workbench.mkdir(parents=True, exist_ok=True)
    note = _write_note(inbox / "my-note.md")

    import app.vault.actions as actions_module

    def _failing_receipt(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("simulated receipt write failure")

    monkeypatch.setattr(actions_module, "_append_receipt", _failing_receipt)

    result = move_note_to_zone(
        note_path=note,
        destination_zone="workbench",
        vault_root=vault_root,
        layout=layout,
        actor="panel_agent",
        write_guard=_permissive_write_guard(),
    )

    # Mutation should have succeeded but receipt failure must be surfaced.
    assert result.mutation_applied is True
    assert result.receipt_written is False
    assert result.reason == "moved_without_receipt", (
        f"Expected 'moved_without_receipt', got {result.reason!r}"
    )
    # Note is in workbench despite receipt failure.
    assert (workbench / "my-note.md").exists()


# ---------------------------------------------------------------------------
# Event routing: panel-actions catalog → downstream event → worker handler
# ---------------------------------------------------------------------------


def test_note_move_workbench_downstream_event_is_wired() -> None:
    """Structural test: note.move.workbench is routable end-to-end.

    Verifies:
    1. The panel-actions catalog declares downstream_event: note.move.workbench.
    2. app.events.types.NOTE_MOVE_WORKBENCH equals "note.move.workbench".
    3. The worker imports and handles NOTE_MOVE_WORKBENCH (prevents dead handler).
    """
    from pathlib import Path as _Path
    import importlib

    repo_root = _Path(__file__).resolve().parents[2]
    catalog_path = repo_root / "docs" / "settings" / "panel-actions.md"
    assert catalog_path.exists(), f"panel-actions catalog missing: {catalog_path}"

    raw = catalog_path.read_text(encoding="utf-8")
    # Extract YAML frontmatter between the first pair of --- fences.
    parts = raw.split("---", 2)
    assert len(parts) >= 3, "panel-actions.md must have YAML frontmatter"
    catalog = yaml.safe_load(parts[1]) or {}
    mappings = catalog.get("mappings", [])

    move_mapping = next(
        (m for m in mappings if m.get("id") == "note.move.workbench"),
        None,
    )
    assert move_mapping is not None, (
        "panel-actions catalog must contain a mapping with id='note.move.workbench'"
    )
    assert move_mapping.get("downstream_event") == "note.move.workbench", (
        "note.move.workbench mapping must declare downstream_event: note.move.workbench"
    )

    # Verify the event constant exists and has the expected value.
    from app.events.types import NOTE_MOVE_WORKBENCH  # noqa: PLC0415
    assert NOTE_MOVE_WORKBENCH == "note.move.workbench"

    # Verify the worker module imports NOTE_MOVE_WORKBENCH (proves handler is wired).
    worker_module = importlib.import_module("app.workers.outbox_worker")
    assert hasattr(worker_module, "handle_note_move_workbench"), (
        "outbox_worker must export handle_note_move_workbench"
    )


def test_execute_panel_intent_emits_note_move_workbench(tmp_path: Path) -> None:
    """execute_panel_intent must emit note.move.workbench when a zone_move action is checked.

    Addresses Codex review concern: the graph logs 'unhandled_action' for zone_move intent
    types, but the runtime's downstream-event emission loop must still produce the outbox
    message so the worker handler and Vault Action Layer are reachable.
    """
    import uuid
    from unittest.mock import patch, MagicMock as _MagicMock

    from app.agents.panel_agent import execute_panel_intent
    from app.components.settings.panel_actions_loader import (
        PanelActionCatalog,
        PanelActionDescriptor,
    )
    from app.events.panel import (
        NoteRef,
        PanelEventSource,
        PanelInfo,
        PanelIntentAction,
        PanelIntentEvent,
        PanelIntentPayload,
        PanelActionMapping,
    )

    note_uuid = uuid.uuid4().hex
    note_ref = NoteRef(uuid=note_uuid, path="/vault/inbox/test-note.md")
    action = PanelIntentAction(
        id="note.move.workbench",
        label="Move this note to Workbench",
        checked=True,
        mapping=PanelActionMapping(
            id="note.move.workbench",
            intent_type="zone_move",
            downstream_event="note.move.workbench",
            trust_verb="APPLY",
            params={"source_zone": "inbox", "destination_zone": "workbench"},
        ),
    )
    panel = PanelInfo(panel_id="panel-1", instruction="", raw_block="")
    payload = PanelIntentPayload(note=note_ref, panel=panel, actions=[action])
    intent_event = PanelIntentEvent(
        payload=payload,
        trace_id="test-trace",
        source=PanelEventSource(trigger="watcher", component="panel_agent_test", sot="test"),
    )

    outbox_file = tmp_path / "outbox.jsonl"

    # Stub out side-effecting I/O (ObjectStore, DB outbox write).
    dummy_store = _MagicMock()
    dummy_store.get_object.return_value = None

    with (
        patch("app.agents.panel_agent.runtime.ObjectStore", return_value=dummy_store),
        patch("app.agents.panel_agent.runtime._write_db_outbox_events"),
        patch("app.agents.panel_agent.runtime._persist_log"),
        patch("app.agents.panel_agent.runtime._apply_note_writeback"),
        patch("app.agents.panel_agent.runtime.load_panel_action_catalog", return_value=PanelActionCatalog.from_descriptors([
            PanelActionDescriptor(
                id="note.move.workbench",
                intent_type="zone_move",
                downstream_event="note.move.workbench",
                labels=["Move this note to Workbench"],
                description="Move inbox note to workbench",
            )
        ])),
    ):
        result = execute_panel_intent(intent_event, outbox_path=outbox_file)

    emitted_topics = [
        getattr(ev, "event", None) or getattr(ev, "event_type", None)
        for ev in result.emitted_events
    ]
    assert "note.move.workbench" in emitted_topics, (
        f"execute_panel_intent must emit note.move.workbench; got: {emitted_topics}"
    )
