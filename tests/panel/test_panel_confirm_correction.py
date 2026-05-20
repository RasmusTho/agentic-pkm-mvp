"""Panel confirmation correction path tests (Issue 3.2).

Verifies that correction.enabled=true applies corrected parameters before
execution, that the response is distinguishable from a plain confirm, and
that idempotency and WriteGuard semantics are preserved.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import app.panel.confirmation as confirm_module
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmRequest,
    CorrectionFields,
    PanelConfirmationService,
    ProposalStore,
    StagedProposal,
    _apply_correction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(
    action_id: str = "act-1",
    action_label: str = "update maturity",
    params: dict | None = None,
) -> PanelIntentEvent:
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid="note-uuid-1"),
            panel=PanelInfo(panel_id="panel-1", instruction="governance"),
            actions=[
                PanelIntentAction(
                    id=action_id,
                    label=action_label,
                    checked=True,
                    mapping=PanelActionMapping(
                        id=action_id,
                        intent_type="frontmatter_update",
                        downstream_event="panel.governance.requested",
                        trust_verb="APPLY",
                        params=params or {"field": "maturity", "value": "draft"},
                    ),
                )
            ],
        )
    )


def _service() -> tuple[PanelConfirmationService, ProposalStore, ConfirmIdempotencyStore]:
    ps = ProposalStore()
    ids = ConfirmIdempotencyStore()
    return PanelConfirmationService(ps, ids), ps, ids


# ---------------------------------------------------------------------------
# _apply_correction unit tests
# ---------------------------------------------------------------------------

def test_apply_correction_updates_params() -> None:
    event = _make_intent(params={"field": "maturity", "value": "draft"})
    correction = CorrectionFields(enabled=True, corrected_parameters={"value": "evergreen"})
    corrected = _apply_correction(event, correction)

    assert corrected.payload.actions[0].mapping.params["value"] == "evergreen"
    assert corrected.payload.actions[0].mapping.params["field"] == "maturity"


def test_apply_correction_does_not_mutate_original() -> None:
    event = _make_intent(params={"field": "maturity", "value": "draft"})
    correction = CorrectionFields(enabled=True, corrected_parameters={"value": "evergreen"})
    _apply_correction(event, correction)

    assert event.payload.actions[0].mapping.params["value"] == "draft"


def test_apply_correction_targets_specific_action_id() -> None:
    intent = PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid="note-uuid-1"),
            panel=PanelInfo(panel_id="p1", instruction="multi"),
            actions=[
                PanelIntentAction(
                    id="act-a",
                    label="action a",
                    checked=True,
                    mapping=PanelActionMapping(
                        id="act-a",
                        intent_type="t",
                        downstream_event="e",
                        params={"v": "old"},
                    ),
                ),
                PanelIntentAction(
                    id="act-b",
                    label="action b",
                    checked=True,
                    mapping=PanelActionMapping(
                        id="act-b",
                        intent_type="t",
                        downstream_event="e",
                        params={"v": "old"},
                    ),
                ),
            ],
        )
    )
    correction = CorrectionFields(
        enabled=True,
        corrected_action_id="act-a",
        corrected_parameters={"v": "new"},
    )
    corrected = _apply_correction(intent, correction)

    assert corrected.payload.actions[0].mapping.params["v"] == "new"
    assert corrected.payload.actions[1].mapping.params["v"] == "old"


def test_apply_correction_selects_corrected_action_without_parameters() -> None:
    intent = PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid="note-uuid-1"),
            panel=PanelInfo(panel_id="p1", instruction="multi"),
            actions=[
                PanelIntentAction(
                    id="act-original",
                    label="original action",
                    checked=True,
                    mapping=PanelActionMapping(
                        id="act-original",
                        intent_type="frontmatter_update",
                        downstream_event="panel.original",
                        params={"field": "maturity", "value": "draft"},
                    ),
                ),
                PanelIntentAction(
                    id="act-corrected",
                    label="corrected action",
                    checked=False,
                    mapping=PanelActionMapping(
                        id="act-corrected",
                        intent_type="frontmatter_update",
                        downstream_event="panel.corrected",
                        params={"field": "status", "value": "active"},
                    ),
                ),
            ],
        )
    )
    correction = CorrectionFields(enabled=True, corrected_action_id="act-corrected")

    corrected = _apply_correction(intent, correction)

    assert corrected.payload.actions[0].checked is False
    assert corrected.payload.actions[1].checked is True
    assert intent.payload.actions[0].checked is True
    assert intent.payload.actions[1].checked is False


# ---------------------------------------------------------------------------
# Service-level correction path
# ---------------------------------------------------------------------------

def test_correction_confirm_executes_corrected_intent() -> None:
    svc, ps, _ = _service()
    ps.stage(
        "prop-corr-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(params={"field": "maturity", "value": "draft"}),
            proposed_at=0.0,
        ),
    )

    captured: list[PanelIntentEvent] = []

    def _fake_execute(event: PanelIntentEvent):
        captured.append(event)
        result = MagicMock()
        result.actions = []
        result.emitted_events = []
        return result

    with patch.object(confirm_module, "execute_panel_intent", side_effect=_fake_execute):
        svc.confirm(
            ConfirmRequest(
                proposal_id="prop-corr-1",
                artifact_id="note-uuid-1",
                action="confirm",
                idempotency_key="ikey-corr-1",
                correction=CorrectionFields(
                    enabled=True,
                    corrected_parameters={"value": "evergreen"},
                ),
            )
        )

    assert len(captured) == 1
    assert captured[0].payload.actions[0].mapping.params["value"] == "evergreen"


def test_correction_confirm_receipt_is_marked_corrected() -> None:
    svc, ps, _ = _service()
    ps.stage(
        "prop-corr-2",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(),
            proposed_at=0.0,
        ),
    )

    mock_result = MagicMock()
    mock_result.actions = []
    mock_result.emitted_events = []

    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result):
        resp = svc.confirm(
            ConfirmRequest(
                proposal_id="prop-corr-2",
                artifact_id="note-uuid-1",
                action="confirm",
                idempotency_key="ikey-corr-2",
                correction=CorrectionFields(
                    enabled=True,
                    corrected_parameters={"value": "evergreen"},
                ),
            )
        )

    assert resp.receipt is not None
    assert resp.receipt.message == "corrected"


def test_plain_confirm_receipt_has_no_correction_message() -> None:
    svc, ps, _ = _service()
    ps.stage(
        "prop-plain-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(),
            proposed_at=0.0,
        ),
    )

    mock_result = MagicMock()
    mock_result.actions = []
    mock_result.emitted_events = []

    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result):
        resp = svc.confirm(
            ConfirmRequest(
                proposal_id="prop-plain-1",
                artifact_id="note-uuid-1",
                action="confirm",
                idempotency_key="ikey-plain-1",
            )
        )

    assert resp.receipt is not None
    assert resp.receipt.message is None


def test_correction_idempotency_returns_same_response() -> None:
    svc, ps, _ = _service()
    ps.stage(
        "prop-corr-3",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(),
            proposed_at=0.0,
        ),
    )

    mock_result = MagicMock()
    mock_result.actions = []
    mock_result.emitted_events = []

    req = ConfirmRequest(
        proposal_id="prop-corr-3",
        artifact_id="note-uuid-1",
        action="confirm",
        idempotency_key="ikey-corr-3",
        correction=CorrectionFields(enabled=True, corrected_parameters={"value": "evergreen"}),
    )

    with patch.object(confirm_module, "execute_panel_intent", return_value=mock_result):
        resp1 = svc.confirm(req)

    # Second call with same idempotency_key must not re-execute
    with patch.object(confirm_module, "execute_panel_intent") as mock_fn:
        resp2 = svc.confirm(req)
        mock_fn.assert_not_called()

    assert resp1.idempotency_key == resp2.idempotency_key
    assert resp1.status == resp2.status


def test_correction_requires_action_id_or_parameters() -> None:
    with pytest.raises(Exception):
        CorrectionFields(enabled=True)
