from __future__ import annotations

from app.domain.commitments import (
    CommitmentRecord,
    apply_commitment_state_transition,
)


def test_commitment_transition_links_receipt_metadata() -> None:
    commitment = CommitmentRecord(
        commitment_id="c-123",
        commitment_kind="next_action",
        state="next",
        summary="Send status update",
        target_ref="note:abc",
    )

    transition = apply_commitment_state_transition(
        commitment,
        to_state="waiting",
        receipt_event_id="evt-commit-1",
        trace_id="trace-commit-1",
        cause="waiting on reply from Alice",
    )

    assert transition.updated.state == "waiting"
    assert transition.receipt_metadata["commitment_id"] == "c-123"
    assert transition.receipt_metadata["receipt_event_id"] == "evt-commit-1"
    assert transition.receipt_metadata["trace_id"] == "trace-commit-1"
    assert transition.receipt_metadata["before_state"] == "next"
    assert transition.receipt_metadata["after_state"] == "waiting"
    assert transition.receipt_metadata["transition_family"] == "commitment_state"
    assert transition.receipt_metadata["cause"] == "waiting on reply from Alice"
