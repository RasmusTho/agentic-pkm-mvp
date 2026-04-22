from __future__ import annotations

from app.domain.commitments import CommitmentRecord, query_next_and_waiting_commitments


def test_query_next_and_waiting_commitments() -> None:
    commitments = (
        CommitmentRecord(commitment_id="c-next-1", commitment_kind="next_action", state="next", summary="Ship PR"),
        CommitmentRecord(commitment_id="c-wait-1", commitment_kind="waiting", state="waiting", summary="Await legal"),
        CommitmentRecord(commitment_id="c-open-1", commitment_kind="open_loop", state="open", summary="Clarify scope"),
    )

    result = query_next_and_waiting_commitments(commitments)

    assert [item.commitment_id for item in result.next_items] == ["c-next-1"]
    assert [item.commitment_id for item in result.waiting_items] == ["c-wait-1"]
    assert result.operator_summary["next_count"] == 1
    assert result.operator_summary["waiting_count"] == 1
    assert result.operator_summary["next_ids"] == ["c-next-1"]
    assert result.operator_summary["waiting_ids"] == ["c-wait-1"]
