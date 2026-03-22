from __future__ import annotations

from app.domain.commitments import (
    FIRST_WAVE_COMMITMENT_KINDS,
    CommitmentHandle,
    build_commitment_handles_for_goal,
    make_commitment_handle,
)


def test_first_wave_commitment_family_is_representable() -> None:
    kinds = {handle.commitment_kind for handle in build_commitment_handles_for_goal("Project next action waiting review return")}

    assert set(FIRST_WAVE_COMMITMENT_KINDS) == {
        "open_loop",
        "project",
        "next_action",
        "waiting",
        "review_return",
    }
    assert {"project", "next_action", "waiting", "review_return"}.issubset(kinds)


def test_commitment_handle_is_distinct_from_artifact_state_axes() -> None:
    handle = make_commitment_handle(commitment_kind="waiting", target_ref="NOTE-1", summary="Waiting for reply")

    assert isinstance(handle, CommitmentHandle)
    payload = handle.to_dict()
    assert payload["commitment_kind"] == "waiting"
    assert "review_state" not in payload
    assert "maturity" not in payload
