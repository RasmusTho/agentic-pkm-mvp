from __future__ import annotations

"""Tests for salience/staleness-aware commitment query surfacing (Issue #695).

Each test corresponds to one AC in the issue contract.
"""

from app.domain.commitments import (
    CommitmentRecord,
    query_next_and_waiting_commitments,
)


# ---------------------------------------------------------------------------
# AC 1: next query consumes salience and staleness signals for ranking
# ---------------------------------------------------------------------------


def test_next_query_consumes_salience_and_staleness() -> None:
    """Verify that salience and staleness inputs influence ranking of next items.

    High salience / high staleness commitment must appear before a low salience /
    low staleness commitment in the returned next_items tuple.
    """
    commitments = (
        CommitmentRecord(
            commitment_id="c-next-low",
            commitment_kind="next_action",
            state="next",
            summary="Low priority next action",
        ),
        CommitmentRecord(
            commitment_id="c-next-high",
            commitment_kind="next_action",
            state="next",
            summary="High priority next action",
        ),
    )
    salience_scores = {
        "c-next-low": 0.2,
        "c-next-high": 0.9,
    }
    staleness_scores = {
        "c-next-low": 0.1,
        "c-next-high": 0.8,
    }

    result = query_next_and_waiting_commitments(
        commitments,
        salience_scores=salience_scores,
        staleness_scores=staleness_scores,
    )

    assert len(result.next_items) == 2
    # High salience/staleness item must rank first
    assert result.next_items[0].commitment_id == "c-next-high"
    assert result.next_items[1].commitment_id == "c-next-low"


# ---------------------------------------------------------------------------
# AC 2: waiting query exposes staleness metadata for operator follow-up
# ---------------------------------------------------------------------------


def test_waiting_query_exposes_staleness_metadata() -> None:
    """Verify that waiting-state items expose staleness metadata in operator_summary."""
    commitments = (
        CommitmentRecord(
            commitment_id="c-wait-fresh",
            commitment_kind="waiting",
            state="waiting",
            summary="Fresh waiting item",
        ),
        CommitmentRecord(
            commitment_id="c-wait-stale",
            commitment_kind="waiting",
            state="waiting",
            summary="Stale waiting item — needs follow-up",
        ),
    )
    staleness_scores = {
        "c-wait-fresh": 0.1,
        "c-wait-stale": 0.95,
    }

    result = query_next_and_waiting_commitments(
        commitments,
        staleness_scores=staleness_scores,
    )

    assert len(result.waiting_items) == 2
    # operator_summary must include staleness metadata for waiting items
    assert "waiting_staleness" in result.operator_summary
    staleness_map = result.operator_summary["waiting_staleness"]
    assert isinstance(staleness_map, dict)
    assert staleness_map.get("c-wait-stale") == 0.95
    assert staleness_map.get("c-wait-fresh") == 0.1


# ---------------------------------------------------------------------------
# AC 3: query remains safe when salience/staleness signals are missing or partial
# ---------------------------------------------------------------------------


def test_query_allows_missing_signal_inputs() -> None:
    """Verify graceful degradation when salience/staleness inputs are absent or partial.

    The query must not raise and must return all next/waiting items without ranking
    by signals that are absent.
    """
    commitments = (
        CommitmentRecord(
            commitment_id="c-next-1",
            commitment_kind="next_action",
            state="next",
            summary="Next action, no signals",
        ),
        CommitmentRecord(
            commitment_id="c-wait-1",
            commitment_kind="waiting",
            state="waiting",
            summary="Waiting item, no signals",
        ),
    )

    # No signals at all — must not raise
    result_none = query_next_and_waiting_commitments(commitments)
    assert len(result_none.next_items) == 1
    assert len(result_none.waiting_items) == 1

    # Partial salience only — must not raise
    result_partial = query_next_and_waiting_commitments(
        commitments,
        salience_scores={"c-next-1": 0.7},
    )
    assert len(result_partial.next_items) == 1
    assert len(result_partial.waiting_items) == 1

    # Empty dicts — must not raise
    result_empty = query_next_and_waiting_commitments(
        commitments,
        salience_scores={},
        staleness_scores={},
    )
    assert len(result_empty.next_items) == 1
    assert len(result_empty.waiting_items) == 1


# ---------------------------------------------------------------------------
# AC 4: returned surfaces remain commitment-typed (not note-state values)
# ---------------------------------------------------------------------------


def test_query_results_remain_commitment_typed() -> None:
    """Verify that query results are CommitmentRecord objects, not note-state scalars.

    Returned items must be CommitmentRecord instances and their state must come
    from the commitment state vocabulary, not note-state axes.
    """
    from app.domain.commitments import CommitmentRecord, COMMITMENT_STATE_VALUES
    from app.domain.state_axes import CANONICAL_REVIEW_STATES, CANONICAL_MATURITY_VALUES

    note_axis_values = set(CANONICAL_REVIEW_STATES) | set(CANONICAL_MATURITY_VALUES)

    commitments = (
        CommitmentRecord(
            commitment_id="c-next-typed",
            commitment_kind="next_action",
            state="next",
            summary="Typed next action",
        ),
        CommitmentRecord(
            commitment_id="c-wait-typed",
            commitment_kind="waiting",
            state="waiting",
            summary="Typed waiting item",
        ),
    )

    result = query_next_and_waiting_commitments(
        commitments,
        salience_scores={"c-next-typed": 0.5},
        staleness_scores={"c-wait-typed": 0.6},
    )

    for item in result.next_items:
        assert isinstance(item, CommitmentRecord), f"Expected CommitmentRecord, got {type(item)}"
        assert item.state in COMMITMENT_STATE_VALUES, f"state '{item.state}' not in commitment vocabulary"
        assert item.state not in note_axis_values, f"state '{item.state}' leaked note-axis value"

    for item in result.waiting_items:
        assert isinstance(item, CommitmentRecord), f"Expected CommitmentRecord, got {type(item)}"
        assert item.state in COMMITMENT_STATE_VALUES, f"state '{item.state}' not in commitment vocabulary"
        assert item.state not in note_axis_values, f"state '{item.state}' leaked note-axis value"
