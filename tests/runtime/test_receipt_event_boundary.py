"""Runtime boundary tests: receipt vs event-trace semantics for governed loops.

These tests enforce the structural separation between:
  - OutboxEvent  — operational trace (trace_id, event_id, source, no accountability fields)
  - Receipt      — accountability record (action_taken, inverse_action, no trace coordinates)
  - ConfirmResponse — governed mutation response carrying BOTH a Receipt and event trace names

Issue #1600 acceptance criteria:
  AC2: test_governed_mutation_receipt_is_distinct_from_event_trace
  AC3: test_read_only_projection_trace_has_no_mutation_authority
"""

from __future__ import annotations

from unittest.mock import MagicMock

import app.panel.confirmation as confirm_module
from app.events.panel import NoteRef, PanelInfo, PanelIntentEvent, PanelIntentPayload
from app.events.schema import OutboxEvent
from app.panel.confirmation import (
    ConfirmRequest,
    ConfirmResponse,
    ProposalStore,
    ConfirmIdempotencyStore,
    PanelConfirmationService,
    Receipt,
    StagedProposal,
)


# ---------------------------------------------------------------------------
# Helpers (mirror pattern from tests/api/test_panel_confirm_api.py)
# ---------------------------------------------------------------------------


def _make_intent(proposal_id: str = "prop-1600", artifact_id: str = "note-uuid-1600") -> PanelIntentEvent:
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=artifact_id, path="notes/boundary_test.md"),
            panel=PanelInfo(panel_id=proposal_id, instruction="boundary check action"),
        )
    )


def _make_staged_proposal(proposal_id: str = "prop-1600", artifact_id: str = "note-uuid-1600") -> StagedProposal:
    """Return a StagedProposal safely outside the same-turn execution window."""
    return StagedProposal(
        artifact_id=artifact_id,
        intent_event=_make_intent(proposal_id, artifact_id),
        proposed_at=0.0,  # epoch past — outside same-turn window
    )


def _make_service_with_proposal(
    proposal_id: str = "prop-1600",
    artifact_id: str = "note-uuid-1600",
) -> tuple[PanelConfirmationService, str, str]:
    """Return (service, proposal_id, artifact_id) with one staged proposal."""
    store = ProposalStore()
    idempotency = ConfirmIdempotencyStore()
    service = PanelConfirmationService(store, idempotency)
    store.stage(proposal_id, _make_staged_proposal(proposal_id, artifact_id))
    return service, proposal_id, artifact_id


# ---------------------------------------------------------------------------
# AC2: governed mutation path — receipt is distinct from event trace
# ---------------------------------------------------------------------------


def test_governed_mutation_receipt_is_distinct_from_event_trace(monkeypatch) -> None:
    """Receipt and OutboxEvent are structurally distinct at model level and on a live execution path.

    Model-level assertions:
    - Receipt has action_taken; OutboxEvent does NOT.
    - OutboxEvent has trace_id; Receipt does NOT.

    Execution-level assertions:
    - A confirmed ConfirmRequest returns a non-None Receipt instance.
    - ConfirmResponse.events_emitted is a list of strings (trace names), not Receipt objects.
    """
    # --- Model-level boundary checks ---
    # Receipt carries accountability fields
    assert "action_taken" in Receipt.model_fields, "Receipt must have action_taken"
    assert "inverse_action" in Receipt.model_fields, "Receipt must have inverse_action"

    # OutboxEvent has NO accountability fields — it is an operational trace
    assert "action_taken" not in OutboxEvent.model_fields, (
        "OutboxEvent must NOT have action_taken (that is a receipt field)"
    )

    # OutboxEvent carries trace coordination fields
    assert "trace_id" in OutboxEvent.model_fields, "OutboxEvent must have trace_id"
    assert "event_id" in OutboxEvent.model_fields, "OutboxEvent must have event_id"

    # Receipt has NO trace coordination fields — it is an accountability record
    assert "trace_id" not in Receipt.model_fields, (
        "Receipt must NOT have trace_id (that is an event-trace field)"
    )
    assert "event_id" not in Receipt.model_fields, (
        "Receipt must NOT have event_id (that is an event-trace field)"
    )

    # --- Execution-level boundary check: real governed mutation path ---
    proposal_id = "prop-1600-ac2"
    artifact_id = "note-uuid-1600-ac2"
    service, proposal_id, artifact_id = _make_service_with_proposal(proposal_id, artifact_id)

    # Patch execute_panel_intent so we do not need a real vault/LLM
    mock_result = MagicMock()
    mock_result.emitted_events = [{"event": "panel.intent.executed"}]
    mock_action = MagicMock()
    mock_action.checked = True
    mock_action.status = "triggered"
    mock_action.details = {}
    mock_result.actions = [mock_action]
    monkeypatch.setattr(confirm_module, "execute_panel_intent", MagicMock(return_value=mock_result))

    request = ConfirmRequest(
        proposal_id=proposal_id,
        artifact_id=artifact_id,
        action="confirm",
        idempotency_key="idem-1600-ac2",
    )
    response: ConfirmResponse = service.confirm(request)

    # ConfirmResponse carries a Receipt (accountability) AND event trace names (operational)
    assert response.receipt is not None, (
        "Governed mutation path must return a non-None Receipt"
    )
    assert isinstance(response.receipt, Receipt), (
        "response.receipt must be a Receipt instance, not an OutboxEvent or raw dict"
    )
    assert isinstance(response.events_emitted, list), (
        "events_emitted must be a list"
    )
    # events_emitted contains strings (event names) — NOT Receipt objects or OutboxEvent objects
    for item in response.events_emitted:
        assert isinstance(item, str), (
            f"events_emitted items must be strings (event trace names), got {type(item)}"
        )
    # The receipt carries action accountability, not a trace coordinate
    assert response.receipt.action_taken == "confirm"
    assert response.receipt.outcome in ("success", "logged")


# ---------------------------------------------------------------------------
# AC3: read-only projection traces cannot authorize mutation
# ---------------------------------------------------------------------------


def test_read_only_projection_trace_has_no_mutation_authority() -> None:
    """OutboxEvent (operational trace) carries no mutation-enabling receipt fields.

    Model-level assertions:
    - OutboxEvent.model_fields does NOT contain action_taken.
    - OutboxEvent.model_fields does NOT contain inverse_action.
    - OutboxEvent.model_fields does NOT contain receipt.

    Optional: read-only response models (e.g. WorkspaceOrientationResponse) carry
    no top-level receipt field, confirming read-only paths emit no accountability receipts.
    """
    # Operational trace envelope must not contain any mutation-authorization fields
    assert "action_taken" not in OutboxEvent.model_fields, (
        "OutboxEvent must not have action_taken — traces cannot authorize mutation"
    )
    assert "inverse_action" not in OutboxEvent.model_fields, (
        "OutboxEvent must not have inverse_action — traces carry no reversal authority"
    )
    assert "receipt" not in OutboxEvent.model_fields, (
        "OutboxEvent must not have a receipt field — traces are not accountability records"
    )

    # Read-only orientation response has no top-level Receipt field
    # This confirms that read-only projection paths emit no accountability receipt
    from app.api.routes.companion import WorkspaceOrientationResponse

    orientation_fields = WorkspaceOrientationResponse.model_fields
    assert "receipt" not in orientation_fields, (
        "WorkspaceOrientationResponse must not carry a top-level receipt field — "
        "read-only projections do not emit accountability receipts"
    )
