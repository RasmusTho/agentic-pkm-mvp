from __future__ import annotations

import hashlib
import json
from threading import Event, Thread, current_thread

import pytest

import app.dispatcher.verification_dispatch as verification_dispatch
from app.dispatcher.verification_dispatch import VerificationDispatchLedger
from tests.dispatcher.verification_helpers import HEAD, ledger, request


NEW_HEAD = "b" * 40


def _claimed_run(
    tmp_path,
) -> tuple[VerificationDispatchLedger, str, str]:
    state = ledger(tmp_path)
    run = state.ingest(request())
    claimed = state.claim(run.run_id, "host")
    assert claimed.lease_id is not None
    return state, run.run_id, claimed.lease_id


def _rebind(
    state: VerificationDispatchLedger,
    run_id: str,
    lease_id: str,
) -> None:
    state.rebind_head(
        run_id,
        NEW_HEAD,
        expected_head_sha=HEAD,
        observed_repository="RasmusTho/agentic-pkm-mvp",
        observed_pr_number=3603,
        observed_head_sha=NEW_HEAD,
        holder="host",
        lease_id=lease_id,
    )


def _pause_worker_before_write_lock(
    monkeypatch: pytest.MonkeyPatch,
    worker_name: str,
) -> tuple[Event, Event]:
    boundary_reached = Event()
    resume = Event()
    begin_immediate_now = verification_dispatch._begin_immediate_now

    def paused_begin_immediate_now(conn):
        if current_thread().name == worker_name:
            boundary_reached.set()
            if not resume.wait(timeout=5):
                raise AssertionError("worker was not resumed at the pre-lock boundary")
        return begin_immediate_now(conn)

    monkeypatch.setattr(
        verification_dispatch,
        "_begin_immediate_now",
        paused_begin_immediate_now,
    )
    return boundary_reached, resume


def _record_closure_evidence(
    state: VerificationDispatchLedger,
    run_id: str,
    lease_id: str,
) -> None:
    state.record_attempt(
        run_id,
        "verification",
        "coordinator",
        "gpt-5.6-sol",
        "xhigh",
        {"head_sha": HEAD},
        "verified",
        {"head_sha": HEAD},
        holder="host",
        lease_id=lease_id,
    )
    final_anchor = state.attempts(run_id)[-1]["attempt_id"]
    for ordinal in (1, 2):
        state.record_attempt(
            run_id,
            "review",
            f"review-{ordinal}",
            "gpt-5.6-sol",
            "xhigh",
            {"head_sha": HEAD},
            "clean",
            {
                "head_sha": HEAD,
                "reviewed_attempt_id": final_anchor,
                "verdict": "clean",
            },
            holder="host",
            lease_id=lease_id,
        )
    assert state.closure_ready(run_id)


def test_completed_rechecks_closure_evidence_after_same_token_head_rebind(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, run_id, lease_id = _claimed_run(tmp_path)
    _record_closure_evidence(state, run_id, lease_id)
    worker_name = "terminal-pre-lock-race"
    boundary_reached, resume = _pause_worker_before_write_lock(
        monkeypatch,
        worker_name,
    )
    outcome: dict[str, object] = {}

    def complete() -> None:
        try:
            outcome["result"] = state.terminal(
                run_id,
                "completed",
                {"head_sha": HEAD, "outcome": "delivered"},
                holder="host",
                lease_id=lease_id,
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=complete, name=worker_name, daemon=True)
    worker.start()
    try:
        assert boundary_reached.wait(timeout=2), "terminal never reached its pre-lock boundary"
        assert worker.is_alive()
        _rebind(state, run_id, lease_id)
    finally:
        resume.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    error = outcome.get("error")
    assert isinstance(error, ValueError), outcome
    assert "two fresh clean reviews" in str(error)
    assert "result" not in outcome
    run = state.get(run_id)
    assert run is not None
    assert run.status == "claimed"
    assert run.current_head_sha == NEW_HEAD
    assert run.verified_head_sha is None
    assert run.terminal_receipt is None


def test_exception_uses_locked_current_head_after_same_token_rebind(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, run_id, lease_id = _claimed_run(tmp_path)
    worker_name = "exception-pre-lock-race"
    boundary_reached, resume = _pause_worker_before_write_lock(
        monkeypatch,
        worker_name,
    )
    packet = {"failure_class": "authority-critical", "evidence": ["review-blocked"]}
    outcome: dict[str, object] = {}

    def create_exception() -> None:
        try:
            outcome["exception_id"] = state.exception(
                run_id,
                "authority-critical",
                packet,
                holder="host",
                lease_id=lease_id,
            )
        except BaseException as exc:  # noqa: BLE001 - asserted thread outcome
            outcome["error"] = exc

    worker = Thread(target=create_exception, name=worker_name, daemon=True)
    worker.start()
    try:
        assert boundary_reached.wait(timeout=2), "exception never reached its pre-lock boundary"
        assert worker.is_alive()
        _rebind(state, run_id, lease_id)
    finally:
        resume.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert "error" not in outcome, outcome
    expected_id = "vexception-" + hashlib.sha256(
        f"{run_id}:authority-critical:{NEW_HEAD}".encode()
    ).hexdigest()[:16]
    assert outcome["exception_id"] == expected_id
    with state.store._connect() as conn:
        rows = conn.execute(
            "SELECT exception_id, head_sha, packet_json "
            "FROM verification_exceptions WHERE run_id=?",
            (run_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["exception_id"] == expected_id
    assert rows[0]["head_sha"] == NEW_HEAD
    assert json.loads(rows[0]["packet_json"]) == packet
    assert rows[0]["head_sha"] != HEAD
