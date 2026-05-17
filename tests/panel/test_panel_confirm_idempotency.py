"""Panel confirmation idempotency projection tests (issue #1054).

Verifies that duplicate confirm requests with the same idempotency key
do not produce double vault writes.
"""

from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, patch

import app.panel.confirmation as confirm_module
from app.agents.panel.writeback import stable_action_id
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
    PanelRuntimeActionResult,
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
    action_label: str = "tag note",
) -> PanelIntentEvent:
    aid = stable_action_id(action_label)
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=note_uuid, path=note_path),
            panel=PanelInfo(panel_id="panel-1", instruction="do it"),
            actions=[PanelIntentAction(id=aid, label=action_label, checked=True)],
        )
    )


def _mock_result(action_label: str = "tag note") -> MagicMock:
    aid = stable_action_id(action_label)
    result = MagicMock()
    result.actions = [
        PanelRuntimeActionResult(id=aid, label=action_label, checked=True, status="triggered")
    ]
    result.emitted_events = [{"event": "panel.intent.executed"}]
    return result


# ---------------------------------------------------------------------------
# Idempotency: duplicate confirm does not double-write
# ---------------------------------------------------------------------------

def test_confirm_idempotent_does_not_double_write_receipt(tmp_path: pathlib.Path) -> None:
    action_label = "tag note"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    ps = ProposalStore()
    ids = ConfirmIdempotencyStore()
    svc = PanelConfirmationService(ps, ids)

    ps.stage(
        "prop-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(note_path=str(note_file), action_label=action_label),
            proposed_at=0.0,
        ),
    )

    req = ConfirmRequest(
        proposal_id="prop-1",
        artifact_id="note-uuid-1",
        action="confirm",
        idempotency_key="ikey-idem-1",
    )

    mock_result = _mock_result(action_label)

    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result) as mock_fn:
        resp1 = svc.confirm(req)
        resp2 = svc.confirm(req)  # duplicate — same idempotency key

    # execute_panel_intent called exactly once
    assert mock_fn.call_count == 1

    # Both responses are identical (idempotent)
    assert resp1.status == resp2.status
    assert resp1.outcome == resp2.outcome
    assert resp1.idempotency_key == resp2.idempotency_key
