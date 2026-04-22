from __future__ import annotations

from app.domain.commitments import COMMITMENT_STATE_VALUES
from app.domain.state_axes import CANONICAL_MATURITY_VALUES, CANONICAL_REVIEW_STATES, LEGACY_REVIEW_STATES


def test_commitment_states_do_not_reuse_state_axes() -> None:
    commitment_states = set(COMMITMENT_STATE_VALUES)
    note_axis_values = set(CANONICAL_REVIEW_STATES) | set(CANONICAL_MATURITY_VALUES) | set(LEGACY_REVIEW_STATES)

    overlap = commitment_states & note_axis_values
    assert overlap == set()
