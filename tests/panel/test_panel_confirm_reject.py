"""Panel confirmation rejection projection tests (issue #1054)."""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import app.panel.confirmation as confirm_module
from app.agents.panel.writeback import stable_action_id
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


def _make_intent(
    note_uuid: str = "note-uuid-1",
    note_path: str | None = None,
    action_label: str = "delete file",
) -> PanelIntentEvent:
    aid = stable_action_id(action_label)
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=note_uuid, path=note_path),
            panel=PanelInfo(panel_id="panel-1", instruction="do it"),
            actions=[PanelIntentAction(id=aid, label=action_label, checked=True)],
        )
    )


def _service() -> tuple[PanelConfirmationService, ProposalStore, ConfirmIdempotencyStore]:
    ps = ProposalStore()
    ids = ConfirmIdempotencyStore()
    return PanelConfirmationService(ps, ids), ps, ids


# ---------------------------------------------------------------------------
# Rejected: checkbox removed, no execution receipt
# ---------------------------------------------------------------------------

def test_panel_projection_rejected_removes_checkbox_no_execution_receipt(tmp_path: pathlib.Path) -> None:
    action_label = "delete file"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    svc, ps, _ = _service()
    ps.stage(
        "prop-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(note_path=str(note_file), action_label=action_label),
            proposed_at=0.0,
        ),
    )

    mock_exec = patch.object(confirm_module, "execute_panel_intent")
    with mock_exec as mock_fn:
        resp = svc.confirm(ConfirmRequest(
            proposal_id="prop-1",
            artifact_id="note-uuid-1",
            action="reject",
            idempotency_key="ikey-r1",
        ))

    # execute_panel_intent must never be called on rejection
    mock_fn.assert_not_called()

    assert resp.status == "rejected"
    # No execution receipt
    assert resp.receipt is None

    content = note_file.read_text(encoding="utf-8")
    # Checkbox removed
    assert f"- [ ] {action_label}" not in content
    # No execution-success marker
    assert "✅" not in content
