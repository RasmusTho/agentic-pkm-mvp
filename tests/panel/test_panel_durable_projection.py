"""Durable vault-visible Panel projection tests (issue #1054).

Tests outcome → vault-state mapping per PANEL_DURABLE_PROJECTION_MAPPING.md.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import pytest

import app.panel.confirmation as confirm_module
import app.agents.panel_agent.runtime as runtime_module
from app.agents.panel.writeback import AI_STATUS_HEADER, stable_action_id, write_receipts
from app.agents.panel_agent.state import PanelAgentState
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentEvent,
    PanelIntentPayload,
    PanelIntentAction,
    PanelRuntimeActionResult,
)
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmRequest,
    PanelConfirmationService,
    ProposalStore,
    StagedProposal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(
    note_uuid: str = "note-uuid-1",
    note_path: str | None = None,
    action_label: str = "send email",
    action_id: str | None = None,
) -> PanelIntentEvent:
    _id = action_id or stable_action_id(action_label)
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=note_uuid, path=note_path),
            panel=PanelInfo(panel_id="panel-1", instruction="do the thing"),
            actions=[PanelIntentAction(id=_id, label=action_label, checked=True)],
        )
    )


def _stage(
    store: ProposalStore,
    proposal_id: str = "prop-1",
    note_uuid: str = "note-uuid-1",
    note_path: str | None = None,
    action_label: str = "send email",
) -> None:
    store.stage(
        proposal_id,
        StagedProposal(
            artifact_id=note_uuid,
            intent_event=_make_intent(note_uuid, note_path, action_label),
            proposed_at=0.0,
        ),
    )


def _service() -> tuple[PanelConfirmationService, ProposalStore, ConfirmIdempotencyStore]:
    ps = ProposalStore()
    ids = ConfirmIdempotencyStore()
    svc = PanelConfirmationService(ps, ids)
    return svc, ps, ids


def _confirm_request(
    proposal_id: str = "prop-1",
    artifact_id: str = "note-uuid-1",
    action: str = "confirm",
    ikey: str = "ikey-1",
) -> ConfirmRequest:
    return ConfirmRequest(
        proposal_id=proposal_id,
        artifact_id=artifact_id,
        action=action,
        idempotency_key=ikey,
    )


def _mock_execute_result(
    status: str = "triggered",
    action_label: str = "send email",
    events: list[str] | None = None,
    inverse_action_id: str | None = None,
) -> MagicMock:
    _id = stable_action_id(action_label)
    result = MagicMock()
    details: dict = {}
    if inverse_action_id:
        details["inverse_action_id"] = inverse_action_id
    result.actions = [
        PanelRuntimeActionResult(
            id=_id,
            label=action_label,
            checked=True,
            status=status,
            details=details,
        )
    ]
    result.emitted_events = [{"event": e} for e in (events or ["panel.intent.executed", "panel.action.triggered"])]
    return result


# ---------------------------------------------------------------------------
# Helpers for graph-level mocking (lets _apply_note_writeback run)
# ---------------------------------------------------------------------------

def _make_graph_state(
    intent: PanelIntentEvent,
    action_label: str,
    status: str = "triggered",
    note_path: str | None = None,
) -> PanelAgentState:
    """Build a minimal PanelAgentState as run_panel_graph would return."""
    aid = stable_action_id(action_label)
    action = PanelIntentAction(id=aid, label=action_label, checked=True)
    result = PanelRuntimeActionResult(id=aid, label=action_label, checked=True, status=status)
    from app.events.schema import make_outbox_event
    emitted = [make_outbox_event(event="panel.intent.executed", source="test", payload={})]
    return PanelAgentState(
        trace_id="test-trace",
        note=intent.payload.note,
        panel=intent.payload.panel,
        actions=[action],
        action_results=[result],
        emitted_events=emitted,
        executed_action_ids=[aid] if status == "triggered" else [],
        vault_root=None,
        intent_event=intent,
    )


# ---------------------------------------------------------------------------
# Executed: checkbox removal
# ---------------------------------------------------------------------------

def test_panel_projection_executed_removes_checkbox(tmp_path: pathlib.Path) -> None:
    action_label = "send email"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    svc, ps, _ = _service()
    intent = _make_intent(note_path=str(note_file), action_label=action_label)
    ps.stage("prop-1", StagedProposal(artifact_id="note-uuid-1", intent_event=intent, proposed_at=0.0))

    graph_state = _make_graph_state(intent, action_label, note_path=str(note_file))
    with patch.object(runtime_module, "run_panel_graph", return_value=graph_state), \
         patch.object(runtime_module, "load_panel_action_catalog", return_value=None), \
         patch.object(runtime_module, "_write_db_outbox_events"):
        svc.confirm(_confirm_request())

    content = note_file.read_text(encoding="utf-8")
    assert f"- [ ] {action_label}" not in content


# ---------------------------------------------------------------------------
# Executed: receipt callout written
# ---------------------------------------------------------------------------

def test_panel_projection_executed_writes_receipt_callout(tmp_path: pathlib.Path) -> None:
    action_label = "archive note"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    svc, ps, _ = _service()
    intent = _make_intent(note_path=str(note_file), action_label=action_label)
    ps.stage("prop-1", StagedProposal(artifact_id="note-uuid-1", intent_event=intent, proposed_at=0.0))

    graph_state = _make_graph_state(intent, action_label, note_path=str(note_file))
    with patch.object(runtime_module, "run_panel_graph", return_value=graph_state), \
         patch.object(runtime_module, "load_panel_action_catalog", return_value=None), \
         patch.object(runtime_module, "_write_db_outbox_events"):
        svc.confirm(_confirm_request())

    content = note_file.read_text(encoding="utf-8")
    # The existing writeback writes ✅ receipt via _apply_note_writeback
    assert "✅" in content or AI_STATUS_HEADER in content


# ---------------------------------------------------------------------------
# Executed: inverse action declared in receipt
# ---------------------------------------------------------------------------

def test_panel_projection_inverse_action_declared(tmp_path: pathlib.Path) -> None:
    action_label = "promote note"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    svc, ps, _ = _service()
    _stage(ps, note_path=str(note_file), action_label=action_label)

    mock_result = _mock_execute_result(action_label=action_label, inverse_action_id="demote-note-abc")
    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result):
        resp = svc.confirm(_confirm_request())

    # inverse_action is captured in receipt (may be None if no inverse)
    assert resp.receipt is not None
    # When declared, must be non-empty
    assert resp.receipt.inverse_action == "demote-note-abc"


def test_panel_projection_inverse_action_none_when_undeclared(tmp_path: pathlib.Path) -> None:
    action_label = "tag note"
    note_file = tmp_path / "test.md"
    note_file.write_text(f"# Note\n- [ ] {action_label}\n", encoding="utf-8")

    svc, ps, _ = _service()
    _stage(ps, note_path=str(note_file), action_label=action_label)

    mock_result = _mock_execute_result(action_label=action_label)
    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result):
        resp = svc.confirm(_confirm_request())

    assert resp.receipt is not None
    assert resp.receipt.inverse_action is None


# ---------------------------------------------------------------------------
# Executed: event emission
# ---------------------------------------------------------------------------

def test_panel_projection_execution_emits_intent_executed_event(tmp_path: pathlib.Path) -> None:
    note_file = tmp_path / "test.md"
    note_file.write_text("# Note\n- [ ] do work\n", encoding="utf-8")

    svc, ps, _ = _service()
    _stage(ps, note_path=str(note_file))

    mock_result = _mock_execute_result(events=["panel.intent.executed", "panel.action.triggered"])
    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result):
        resp = svc.confirm(_confirm_request())

    assert "panel.intent.executed" in resp.events_emitted


# ---------------------------------------------------------------------------
# Logged: event emission
# ---------------------------------------------------------------------------

def test_panel_projection_logged_emits_logged_event(tmp_path: pathlib.Path) -> None:
    action_label = "log this"
    note_file = tmp_path / "test.md"
    note_file.write_text(f"# Note\n- [ ] {action_label}\n", encoding="utf-8")

    svc, ps, _ = _service()
    _stage(ps, note_path=str(note_file), action_label=action_label)

    # All actions logged → logged outcome
    mock_result = _mock_execute_result(
        status="logged",
        action_label=action_label,
        events=["panel.action.logged"],
    )
    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result):
        resp = svc.confirm(_confirm_request())

    assert "panel.action.logged" in resp.events_emitted


# ---------------------------------------------------------------------------
# Watcher compatibility: vault state parseable without special-casing
# ---------------------------------------------------------------------------

def test_panel_projection_watcher_compatible(tmp_path: pathlib.Path) -> None:
    """Vault state written via confirm path must be parseable by the Panel watcher."""
    from app.agents.panel.parser import parse_panel

    action_label = "move note"
    aid = stable_action_id(action_label)
    # Minimal note with panel block using the standard panel fence format
    note_content = (
        "# Note\n"
        "%% AI panel %%\n"
        f"- [ ] {action_label} <!--ai:id={aid}-->\n"
        "%% AI panel end %%\n"
    )
    note_file = tmp_path / "watcher_compat.md"
    note_file.write_text(note_content, encoding="utf-8")

    # Write a receipt directly (simulating executed projection outcome)
    updated = write_receipts(note_content, [f"✅ {action_label} — success — 2026-05-17T12:00:00Z"])
    note_file.write_text(updated, encoding="utf-8")

    content = note_file.read_text(encoding="utf-8")
    # Parser must not raise; the panel block must still be parseable
    parsed = parse_panel(content)
    # Receipt block is outside the panel action scope — parser simply ignores it
    assert parsed is not None


# ---------------------------------------------------------------------------
# Architecture: companion_ui must not write vault directly
# ---------------------------------------------------------------------------

def test_companion_ui_does_not_write_vault_directly() -> None:
    import ast

    vault_write_calls = {"write_text", "write_bytes", "open"}
    companion_ui_root = pathlib.Path(__file__).parents[2] / "companion-ui"
    if not companion_ui_root.exists():
        pytest.skip("companion-ui directory not present")

    violations: list[str] = []
    for py_file in companion_ui_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in vault_write_calls:
                violations.append(f"{py_file}:{node.col_offset} uses .{node.attr}")

    assert not violations, (
        "companion_ui modules must not write vault files directly:\n"
        + "\n".join(violations)
    )
