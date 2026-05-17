"""Panel confirmation blocked-state projection tests (issue #1054)."""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

import app.panel.confirmation as confirm_module
from app.agents.panel.writeback import AI_STATUS_HEADER, stable_action_id
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmRequest,
    PanelConfirmationService,
    ProposalStore,
    StagedProposal,
)
from app.write_guard import WriteGuard, WritesBlockedError


def _make_intent(
    note_uuid: str = "note-uuid-1",
    note_path: str | None = None,
    action_label: str = "send report",
) -> PanelIntentEvent:
    aid = stable_action_id(action_label)
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=note_uuid, path=note_path),
            panel=PanelInfo(panel_id="panel-1", instruction="do it"),
            actions=[PanelIntentAction(id=aid, label=action_label, checked=True)],
        )
    )


def _service_with_blocked_guard() -> tuple[PanelConfirmationService, ProposalStore, ConfirmIdempotencyStore]:
    mock_guard = MagicMock(spec=WriteGuard)
    mock_guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "blocked", "tag allowlist check failed", "panel.confirm"
    )
    ps = ProposalStore()
    ids = ConfirmIdempotencyStore()
    svc = PanelConfirmationService(ps, ids, write_guard=mock_guard)
    return svc, ps, ids


# ---------------------------------------------------------------------------
# Blocked: preserves checkbox
# ---------------------------------------------------------------------------

def test_panel_projection_blocked_preserves_checkbox(tmp_path: pathlib.Path) -> None:
    action_label = "send report"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    svc, ps, _ = _service_with_blocked_guard()
    ps.stage(
        "prop-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(note_path=str(note_file), action_label=action_label),
            proposed_at=0.0,
        ),
    )

    svc.confirm(ConfirmRequest(
        proposal_id="prop-1",
        artifact_id="note-uuid-1",
        action="confirm",
        idempotency_key="ikey-b1",
    ))

    content = note_file.read_text(encoding="utf-8")
    assert f"- [ ] {action_label}" in content


# ---------------------------------------------------------------------------
# Blocked: writes blocked receipt
# ---------------------------------------------------------------------------

def test_panel_projection_blocked_writes_blocked_receipt(tmp_path: pathlib.Path) -> None:
    action_label = "send report"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    svc, ps, _ = _service_with_blocked_guard()
    ps.stage(
        "prop-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(note_path=str(note_file), action_label=action_label),
            proposed_at=0.0,
        ),
    )

    svc.confirm(ConfirmRequest(
        proposal_id="prop-1",
        artifact_id="note-uuid-1",
        action="confirm",
        idempotency_key="ikey-b2",
    ))

    content = note_file.read_text(encoding="utf-8")
    assert "🚫" in content
    assert AI_STATUS_HEADER in content
    assert "writeguard" in content.lower() or "blocked" in content.lower()


# ---------------------------------------------------------------------------
# Blocked: emits panel.action.blocked event
# ---------------------------------------------------------------------------

def test_panel_projection_blocked_emits_blocked_event(tmp_path: pathlib.Path) -> None:
    action_label = "send report"
    note_file = tmp_path / "test.md"
    note_file.write_text(f"# Note\n- [ ] {action_label}\n", encoding="utf-8")

    svc, ps, _ = _service_with_blocked_guard()
    ps.stage(
        "prop-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(note_path=str(note_file), action_label=action_label),
            proposed_at=0.0,
        ),
    )

    resp = svc.confirm(ConfirmRequest(
        proposal_id="prop-1",
        artifact_id="note-uuid-1",
        action="confirm",
        idempotency_key="ikey-b3",
    ))

    assert resp.status == "blocked"
    assert "panel.action.blocked" in resp.events_emitted
