"""CAL-02 contract tests for the decision revisit scheduler."""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest


def _decision(*, decided_on: date) -> dict[str, object]:
    return {
        "decision_object_id": str(uuid4()),
        "decision_uuid": str(uuid4()),
        "title": "Use the canonical store",
        "decided_on": decided_on.isoformat(),
    }


def test_ladder_declared_once_and_imported() -> None:
    from app.calibration.ladder import DEFAULT_REVISIT_LADDER
    from app.calibration.scheduler import DEFAULT_REVISIT_LADDER as scheduler_ladder

    assert DEFAULT_REVISIT_LADDER == (14, 42, 180)
    assert scheduler_ladder is DEFAULT_REVISIT_LADDER


def test_next_pending_revisit_returns_earliest_due_rung() -> None:
    from app.calibration.scheduler import next_pending_revisit

    decision = _decision(decided_on=date(2026, 1, 1))
    assert next_pending_revisit(decision, today=date(2026, 1, 14)) is None

    due = next_pending_revisit(decision, today=date(2026, 1, 15))
    assert due is not None
    assert due.rung_index == 0
    assert due.rung_days == 14
    assert due.due_since == date(2026, 1, 15)

    assert (
        next_pending_revisit(
            decision,
            today=date(2026, 7, 1),
            outcome_records=[
                {
                    "decision_object_id": decision["decision_object_id"],
                    "decision_uuid": decision["decision_uuid"],
                    "rung_index": 0,
                    "outcome": "held",
                    "created_at": "2026-01-15T00:00:00+00:00",
                }
            ],
        ).rung_index
        == 1
    )

    every_rung_answered = [
        {
            "decision_object_id": decision["decision_object_id"],
            "decision_uuid": decision["decision_uuid"],
            "rung_index": rung_index,
            "outcome": "held",
            "created_at": "2026-01-15T00:00:00+00:00",
        }
        for rung_index in range(3)
    ]
    assert (
        next_pending_revisit(
            decision, today=date(2027, 1, 1), outcome_records=every_rung_answered
        )
        is None
    )


def test_at_most_one_pending_revisit_per_decision() -> None:
    from app.calibration.scheduler import next_pending_revisit

    decision = _decision(decided_on=date(2026, 1, 1))
    due = next_pending_revisit(decision, today=date(2027, 1, 1))
    assert due is not None
    assert due.rung_index == 0


def test_dismissal_is_durable_and_writes_no_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.calibration.scheduler import next_pending_revisit
    from app.receipts import outcome_receipt_log
    from app.receipts.revisit_dismissal_log import append_revisit_dismissal

    decision = _decision(decided_on=date(2026, 1, 1))
    monkeypatch.setattr(
        "app.receipts.revisit_dismissal_log.DEFAULT_WRITE_GUARD.assert_writes_allowed", lambda _: None
    )
    append_revisit_dismissal(
        decision_object_id=str(decision["decision_object_id"]),
        decision_uuid=str(decision["decision_uuid"]),
        rung_index=0,
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        vault_root=tmp_path / "vault",
    )

    assert outcome_receipt_log.iter_outcome_receipts(tmp_path / "vault") == []
    assert (
        next_pending_revisit(
            decision, today=date(2026, 2, 1), vault_root=tmp_path / "vault"
        ) is None
    )


def test_dismiss_blocked_by_write_guard_raises_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.receipts import revisit_dismissal_log
    from app.write_guard import WritesBlockedError

    monkeypatch.setattr(
        revisit_dismissal_log.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: (_ for _ in ()).throw(WritesBlockedError("safe_mode", None, action)),
    )
    with pytest.raises(WritesBlockedError):
        revisit_dismissal_log.append_revisit_dismissal(
            decision_object_id=str(uuid4()),
            decision_uuid=str(uuid4()),
            rung_index=0,
            vault_root=tmp_path / "vault",
        )
    assert not (tmp_path / "vault").exists()


def test_answered_rung_advances_schedule_like_dismissal() -> None:
    from app.calibration.scheduler import next_pending_revisit

    decision = _decision(decided_on=date(2026, 1, 1))
    outcomes = [
        {
            "decision_object_id": decision["decision_object_id"],
            "decision_uuid": decision["decision_uuid"],
            "rung_index": 0,
            "outcome": "held",
            "created_at": "2026-01-15T00:00:00+00:00",
        }
    ]
    due = next_pending_revisit(decision, today=date(2026, 2, 12), outcome_records=outcomes)
    assert due is not None
    assert due.rung_index == 1
