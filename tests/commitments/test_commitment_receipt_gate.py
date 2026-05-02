"""Tests for the receipt-governed APPLY gate on commitment state mutations.

AC source: GitHub issue #694
"""
from __future__ import annotations

import pytest

from app.domain.commitments import (
    CommitmentRecord,
    CommitmentTransitionResult,
    apply_commitment_mutation,
)


def _base_request() -> dict:
    return {
        "verb": "APPLY",
        "authority": "user",
        "basis": "user marked complete",
        "outcome": "done",
        "artifact_linkage": "note:abc",
        "instance_provenance": "session:xyz",
    }


def _sample_commitment() -> CommitmentRecord:
    return CommitmentRecord(
        commitment_id="c-001",
        commitment_kind="next_action",
        state="next",
        summary="Reply to Alice",
        target_ref="note:abc",
    )


# ---------------------------------------------------------------------------
# AC 1: rejects non-APPLY trust verbs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verb", ["ASSERT", "SUGGEST", "assert", "suggest", "observe", ""])
def test_commitment_write_rejects_non_apply_verb(verb: str) -> None:
    req = {**_base_request(), "verb": verb}
    with pytest.raises(ValueError, match="APPLY"):
        apply_commitment_mutation(_sample_commitment(), to_state="done", receipt_request=req)


# ---------------------------------------------------------------------------
# AC 2: rejects missing required receipt fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing_field", [
    "verb",
    "authority",
    "basis",
    "outcome",
    "artifact_linkage",
    "instance_provenance",
])
def test_commitment_write_requires_receipt_fields(missing_field: str) -> None:
    req = {k: v for k, v in _base_request().items() if k != missing_field}
    with pytest.raises(ValueError, match=missing_field):
        apply_commitment_mutation(_sample_commitment(), to_state="done", receipt_request=req)


# ---------------------------------------------------------------------------
# AC 3: successful mutation returns updated state + receipt-linkage metadata
# ---------------------------------------------------------------------------

def test_commitment_write_returns_transition_and_receipt_linkage() -> None:
    result = apply_commitment_mutation(
        _sample_commitment(),
        to_state="done",
        receipt_request=_base_request(),
    )

    assert isinstance(result, CommitmentTransitionResult)
    assert result.updated.state == "done"
    assert result.updated.commitment_id == "c-001"

    meta = result.receipt_metadata
    assert meta["verb"] == "APPLY"
    assert meta["authority"] == "user"
    assert meta["basis"] == "user marked complete"
    assert meta["outcome"] == "done"
    assert meta["artifact_linkage"] == "note:abc"
    assert meta["instance_provenance"] == "session:xyz"
    assert meta["before_state"] == "next"
    assert meta["after_state"] == "done"
    assert meta["commitment_id"] == "c-001"


# ---------------------------------------------------------------------------
# AC 4: mutation does not touch note-state axes
# ---------------------------------------------------------------------------

def test_commitment_write_does_not_touch_note_state_axes() -> None:
    result = apply_commitment_mutation(
        _sample_commitment(),
        to_state="done",
        receipt_request=_base_request(),
    )

    updated = result.updated
    # CommitmentRecord must not gain maturity, review_state, or execution-plan fields
    assert not hasattr(updated, "maturity")
    assert not hasattr(updated, "review_state")
    assert not hasattr(updated, "execution_plan")
    assert not hasattr(updated, "note_state")

    meta = result.receipt_metadata
    for key in ("maturity", "review_state", "execution_plan", "note_state"):
        assert key not in meta
