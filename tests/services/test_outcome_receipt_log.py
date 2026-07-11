"""CAL-01 contract tests for append-only decision outcome receipts."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.receipts.outcome_receipt_log as outcome_log
from app.write_guard import WritesBlockedError


def _ids() -> tuple[str, str]:
    return str(uuid4()), str(uuid4())


def _records(vault: Path) -> list[dict[str, object]]:
    return outcome_log.iter_outcome_receipts(vault)


def test_outcome_schema_validates_vocabulary() -> None:
    object_id, decision_uuid = _ids()
    receipt = outcome_log.build_receipt(
        decision_object_id=object_id,
        decision_uuid=decision_uuid,
        rung_index=0,
        outcome="held",
        note="still true",
    )
    assert receipt["outcome"] == "held"
    assert receipt["decision_object_id"] == object_id
    assert receipt["decision_uuid"] == decision_uuid
    with pytest.raises(ValidationError):
        outcome_log.build_receipt(
            decision_object_id=object_id,
            decision_uuid=decision_uuid,
            rung_index=0,
            outcome="wrong",  # type: ignore[arg-type]
        )


def test_append_blocked_by_write_guard_raises_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id, decision_uuid = _ids()
    monkeypatch.setattr(
        outcome_log.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: (_ for _ in ()).throw(WritesBlockedError("safe_mode", None, action)),
    )
    with pytest.raises(WritesBlockedError):
        outcome_log.append_outcome_receipt(
            decision_object_id=object_id,
            decision_uuid=decision_uuid,
            rung_index=0,
            outcome="held",
            vault_root=tmp_path / "vault",
        )
    assert not (tmp_path / "vault").exists()


def test_append_durable_even_if_projection_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id, decision_uuid = _ids()
    monkeypatch.setattr(outcome_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)
    monkeypatch.setattr(
        outcome_log, "_insert_projection", lambda _: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    with pytest.raises(RuntimeError, match="db down"):
        outcome_log.append_outcome_receipt(
            decision_object_id=object_id,
            decision_uuid=decision_uuid,
            rung_index=0,
            outcome="partly_held",
            vault_root=tmp_path / "vault",
        )
    assert len(_records(tmp_path / "vault")) == 1


def test_append_idempotent_per_decision_and_rung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id, decision_uuid = _ids()
    monkeypatch.setattr(outcome_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)
    projections: list[dict[str, object]] = []
    monkeypatch.setattr(outcome_log, "_insert_projection", projections.append)
    kwargs = dict(
        decision_object_id=object_id,
        decision_uuid=decision_uuid,
        rung_index=2,
        outcome="unknown_yet",
        vault_root=tmp_path / "vault",
    )
    first = outcome_log.append_outcome_receipt(**kwargs)
    second = outcome_log.append_outcome_receipt(**kwargs)
    assert first == second
    assert len(_records(tmp_path / "vault")) == 1
    assert len(projections) == 2  # retry repairs a prior failed/missing projection


def test_existing_receipts_never_rewritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    object_id, decision_uuid = _ids()
    monkeypatch.setattr(outcome_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)
    monkeypatch.setattr(outcome_log, "_insert_projection", lambda _: None)
    created = datetime(2026, 7, 1, tzinfo=timezone.utc)
    outcome_log.append_outcome_receipt(
        decision_object_id=object_id,
        decision_uuid=decision_uuid,
        rung_index=0,
        outcome="held",
        created_at=created,
        vault_root=tmp_path / "vault",
    )
    shard = next(outcome_log.outcome_receipts_dir(tmp_path / "vault").glob("*.jsonl"))
    before = shard.read_bytes()
    outcome_log.append_outcome_receipt(
        decision_object_id=object_id,
        decision_uuid=decision_uuid,
        rung_index=1,
        outcome="did_not_hold",
        created_at=created,
        vault_root=tmp_path / "vault",
    )
    assert shard.read_bytes().startswith(before)


def test_append_call_site_asserts_write_guard_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_id, decision_uuid = _ids()
    seen: list[str] = []
    monkeypatch.setattr(
        outcome_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", seen.append
    )
    monkeypatch.setattr(outcome_log, "_insert_projection", lambda _: None)
    outcome_log.append_outcome_receipt(
        decision_object_id=object_id,
        decision_uuid=decision_uuid,
        rung_index=0,
        outcome="held",
        vault_root=tmp_path / "vault",
    )
    assert seen == [outcome_log.OUTCOME_RECEIPT_WRITE_ACTION]
