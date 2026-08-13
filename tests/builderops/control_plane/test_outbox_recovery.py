from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from app.builderops.control_plane import (
    IdempotencyConflict,
    LeaseUnavailable,
    StateConflict,
    StaleFencingToken,
    UnknownEffectNeedsReconciliation,
)

pytestmark = pytest.mark.pg


def _expire_outbox_claim(store, repository: str, operation_key: str) -> None:
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET claim_expires_at = clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND operation_key = %s",
            (repository, operation_key),
        )


def _commit_outbox_task(
    store,
    envelope,
    *,
    task_id: str,
    key: str,
    effect_type: str,
    payload: dict,
    task_payload: dict | None = None,
):
    store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key=f"{key}-create",
        request={"command": "create"},
    )
    _, lease = store.claim_task(
        envelope=envelope,
        task_id=task_id,
        holder="executor",
        idempotency_key=f"{key}-claim",
        request={"command": "claim"},
    )
    return store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="effect_pending",
        idempotency_key=key,
        request=task_payload or {"command": "schedule-effect"},
        outbox={"effect_type": effect_type, "payload": payload},
        lease=lease,
    )


def test_post_effect_phase_is_exact_idempotent_and_recoverable(
    control_plane_store, envelope
) -> None:
    head = "a" * 40
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="post-effect-phase",
        key="post-effect-phase",
        effect_type="github.merge",
        payload={"repository": envelope.repository, "pr_number": 4892, "head_sha": head},
    )
    assert result.operation_key is not None
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="verification-host",
        claim_ttl_seconds=1,
    )
    identity = {
        "operation_key": result.operation_key,
        "fencing_token": claim.fencing_token,
        "repository": envelope.repository,
        "task_id": "post-effect-phase",
        "pr_number": 4892,
        "head_sha": head,
    }
    readback = {
        "merged": True,
        "head_sha": head,
        "merge_commit_sha": "b" * 40,
    }

    pending = control_plane_store.begin_post_effect_reconciliation(
        claim, identity=identity
    )
    assert pending["phase"] == "pending"
    assert control_plane_store.begin_post_effect_reconciliation(
        claim, identity=identity
    ) == pending
    with pytest.raises((StateConflict, StaleFencingToken)):
        control_plane_store.begin_post_effect_reconciliation(
            replace(claim, fencing_token=claim.fencing_token + 1),
            identity={**identity, "fencing_token": claim.fencing_token + 1},
        )

    _expire_outbox_claim(
        control_plane_store, envelope.repository, result.operation_key
    )
    with pytest.raises(StaleFencingToken):
        control_plane_store.begin_post_effect_reconciliation(
            claim, identity=identity
        )
    recovered = control_plane_store.outbox_claim(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="recovery-verifier",
    )
    reconciled = control_plane_store.reconcile_post_effect(
        recovered,
        identity=identity,
        readback=readback,
    )
    assert reconciled["phase"] == "reconciled"
    assert reconciled["identity"] == identity
    assert reconciled["readback"] == readback
    assert reconciled["reconciled_receipt_sequence"] > pending[
        "pending_receipt_sequence"
    ]
    assert control_plane_store.reconcile_post_effect(
        recovered,
        identity=identity,
        readback=readback,
    ) == reconciled
    with pytest.raises(StateConflict, match="evidence is conflicting"):
        control_plane_store.reconcile_post_effect(
            recovered,
            identity=identity,
            readback={**readback, "merged": False},
        )
    with pytest.raises(StateConflict, match="reordered"):
        control_plane_store.begin_post_effect_reconciliation(
            recovered, identity=identity
        )

    intent = control_plane_store.outbox_intent(
        envelope.repository, result.operation_key
    )
    assert intent["post_effect_reconciliation"] == reconciled
    assert control_plane_store.receipt(
        envelope.repository, pending["pending_receipt_sequence"]
    )["event_type"] == "outbox.post_effect.pending"
    assert control_plane_store.receipt(
        envelope.repository, reconciled["reconciled_receipt_sequence"]
    )["event_type"] == "outbox.post_effect.reconciled"

    missing = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="post-effect-missing-pending",
        key="post-effect-missing-pending",
        effect_type="github.merge",
        payload={"repository": envelope.repository, "pr_number": 4893, "head_sha": head},
    )
    assert missing.operation_key is not None
    missing_claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=missing.operation_key,
        worker_id="verification-host",
    )
    with pytest.raises(StateConflict, match="requires pending"):
        control_plane_store.reconcile_post_effect(
            missing_claim,
            identity={
                **identity,
                "operation_key": missing.operation_key,
                "fencing_token": missing_claim.fencing_token,
                "task_id": "post-effect-missing-pending",
                "pr_number": 4893,
            },
            readback=readback,
        )


def test_unknown_external_effect_requires_readback_before_retry(
    control_plane_store, envelope
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="task-3792",
        key="unknown-effect",
        effect_type="github.merge",
        payload={"pr": 4000},
    )
    first_claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-1",
        claim_ttl_seconds=1,
    )
    restarted_store = type(control_plane_store)(control_plane_store.dsn)
    with pytest.raises(LeaseUnavailable, match="active claim"):
        restarted_store.outbox_claim(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="recovery-executor",
        )
    _expire_outbox_claim(
        restarted_store, envelope.repository, result.operation_key
    )
    orphaned_claim = restarted_store.outbox_claim(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="recovery-executor",
    )
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert orphaned_claim.operation_key == first_claim.operation_key
    assert orphaned_claim.worker_id == "recovery-executor"
    assert orphaned_claim.fencing_token > first_claim.fencing_token
    assert orphaned_claim.receipt_sequence > first_claim.receipt_sequence
    assert orphaned_claim.claim_lsn != first_claim.claim_lsn
    assert restarted_store.effect_eligible(first_claim) is False
    with pytest.raises(StaleFencingToken):
        restarted_store.reconcile_outbox(
            first_claim,
            observed_applied=True,
            evidence={"readback": "stale-worker-forged"},
        )
    with pytest.raises(StaleFencingToken):
        restarted_store.reconcile_outbox(
            replace(orphaned_claim, worker_id="wrong-holder"),
            observed_applied=False,
            evidence={"readback": "forged"},
        )
    with pytest.raises(RuntimeError, match="after_reconciliation_commit"):
        restarted_store.reconcile_outbox(
            orphaned_claim,
            observed_applied=False,
            evidence={"readback": "not-found"},
            fault_at="after_reconciliation_commit",
        )
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "pending"
    retryable = restarted_store.reconcile_outbox(
        orphaned_claim, observed_applied=False, evidence={"readback": "not-found"}
    )
    assert retryable.replayed is True
    retry_receipt = restarted_store.receipt(envelope.repository, retryable.receipt_sequence)
    assert retry_receipt["event_type"] == "outbox.reconciled.pending"
    assert retry_receipt["lease_holder"] == orphaned_claim.worker_id
    assert retry_receipt["lease_fencing_token"] == orphaned_claim.fencing_token
    assert retry_receipt["recovery_lsn"] == retryable.recovery_lsn
    with pytest.raises(IdempotencyConflict):
        restarted_store.reconcile_outbox(
            orphaned_claim,
            observed_applied=False,
            evidence={"readback": "different"},
        )
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "pending"
    claim = restarted_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor-2",
    )
    assert claim.fencing_token > first_claim.fencing_token
    assert restarted_store.effect_eligible(first_claim) is False
    with pytest.raises(StaleFencingToken):
        control_plane_store.mark_effect_unknown(first_claim, detail="late stale worker")
    restarted_store.mark_effect_unknown(claim, detail="network timeout after request")

    with pytest.raises(UnknownEffectNeedsReconciliation):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-2",
        )

    terminal = restarted_store.reconcile_outbox(
        claim, observed_applied=True, evidence={"merge_sha": "a" * 40}
    )
    terminal_receipt = restarted_store.receipt(envelope.repository, terminal.receipt_sequence)
    assert terminal_receipt["event_type"] == "outbox.reconciled.succeeded"
    assert terminal_receipt["lease_holder"] == claim.worker_id
    assert terminal_receipt["lease_fencing_token"] == claim.fencing_token
    assert terminal_receipt["recovery_lsn"] == terminal.recovery_lsn
    with pytest.raises(LeaseUnavailable, match="terminal"):
        restarted_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="executor-3",
        )
    assert restarted_store.outbox_status(envelope.repository, result.operation_key) == "succeeded"


def test_live_unknown_claim_cannot_be_stolen_during_readback(
    control_plane_store, envelope
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="live-unknown-readback",
        key="live-unknown-readback",
        effect_type="github.merge",
        payload={"pr": 4000},
    )
    original = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="readback-owner",
    )
    control_plane_store.mark_effect_unknown(
        original, detail="transport outcome requires readback"
    )

    with pytest.raises(LeaseUnavailable, match="active claim"):
        control_plane_store.outbox_claim(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="concurrent-recovery",
        )

    reconciliation = control_plane_store.reconcile_outbox(
        original,
        observed_applied=False,
        evidence={"readback": "not-found"},
    )
    assert reconciliation.status == "pending"
    assert reconciliation.fencing_token == original.fencing_token


def test_indeterminate_effect_dead_letters_without_retry(
    control_plane_store, envelope
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="task-indeterminate-model-effect",
        key="indeterminate-model-effect",
        effect_type="model.verification_coordinator",
        payload={"head_sha": "a" * 40},
        task_payload={
            "contract_version": "builderops_verification_run.v1",
            "run": {
                "coordinator_session_id": None,
                "context_pack": None,
            },
        },
    )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="verification-host",
    )
    control_plane_store.mark_effect_unknown(
        claim, detail="provider session identity was not durably observed"
    )
    evidence = {
        "head_sha": "a" * 40,
        "outcome": "indeterminate_pre_session_model_effect",
        "provider_session_id": None,
        "relaunch_performed": False,
    }

    terminal = control_plane_store.reconcile_outbox(
        claim,
        observed_applied=False,
        terminal_unknown=True,
        evidence=evidence,
    )
    replay = control_plane_store.reconcile_outbox(
        claim,
        observed_applied=False,
        terminal_unknown=True,
        evidence=evidence,
    )

    assert terminal.status == "dead_letter"
    assert replay.status == "dead_letter"
    assert replay.replayed is True
    receipt = control_plane_store.receipt(
        envelope.repository, terminal.receipt_sequence
    )
    assert receipt["event_type"] == "outbox.reconciled.dead_letter"
    assert receipt["recovery_lsn"] == terminal.recovery_lsn
    with control_plane_store._connect() as conn:
        dead_letter = conn.execute(
            "SELECT outcome FROM builderops_dead_letters "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
    assert dead_letter is not None
    assert dead_letter["outcome"] == evidence
    with pytest.raises(LeaseUnavailable, match="dead_letter"):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="replacement-verifier",
        )
    with pytest.raises(ValueError, match="cannot claim an applied effect"):
        control_plane_store.reconcile_outbox(
            claim,
            observed_applied=True,
            terminal_unknown=True,
            evidence=evidence,
        )


def test_terminal_unknown_rejects_github_effect_without_mutation(
    control_plane_store, envelope
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="task-github-effect-cannot-dead-letter",
        key="github-effect-cannot-dead-letter",
        effect_type="github.merge",
        payload={"head_sha": "a" * 40, "pr": 3852},
    )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="merge-executor",
    )
    control_plane_store.mark_effect_unknown(
        claim, detail="merge response was not durably observed"
    )

    with pytest.raises(StateConflict, match="restricted"):
        control_plane_store.reconcile_outbox(
            claim,
            observed_applied=False,
            terminal_unknown=True,
            evidence={
                "head_sha": "a" * 40,
                "outcome": "indeterminate_pre_session_model_effect",
                "provider_session_id": None,
                "relaunch_performed": False,
            },
        )

    assert (
        control_plane_store.outbox_status(envelope.repository, result.operation_key)
        == "unknown"
    )
    with control_plane_store._connect() as conn:
        dead_letters = conn.execute(
            "SELECT count(*) AS count FROM builderops_dead_letters "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
        reconciliations = conn.execute(
            "SELECT count(*) AS count FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
    assert dead_letters is not None and dead_letters["count"] == 0
    assert reconciliations is not None and reconciliations["count"] == 0


def test_terminal_unknown_requires_exact_model_evidence_without_mutation(
    control_plane_store, envelope
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="task-model-effect-exact-evidence",
        key="model-effect-exact-evidence",
        effect_type="model.verification_coordinator",
        payload={"head_sha": "a" * 40},
        task_payload={
            "contract_version": "builderops_verification_run.v1",
            "run": {
                "coordinator_session_id": None,
                "context_pack": None,
            },
        },
    )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="verification-host",
    )
    control_plane_store.mark_effect_unknown(
        claim, detail="provider session identity was not durably observed"
    )
    exact = {
        "head_sha": "a" * 40,
        "outcome": "indeterminate_pre_session_model_effect",
        "provider_session_id": None,
        "relaunch_performed": False,
    }
    invalid_evidence = (
        {key: value for key, value in exact.items() if key != "head_sha"},
        {**exact, "unexpected": True},
        {**exact, "head_sha": "b" * 40},
        {**exact, "provider_session_id": "thread-123"},
        {**exact, "relaunch_performed": True},
    )

    for evidence in invalid_evidence:
        with pytest.raises(StateConflict, match="exact"):
            control_plane_store.reconcile_outbox(
                claim,
                observed_applied=False,
                terminal_unknown=True,
                evidence=evidence,
            )

    assert (
        control_plane_store.outbox_status(envelope.repository, result.operation_key)
        == "unknown"
    )
    with control_plane_store._connect() as conn:
        dead_letters = conn.execute(
            "SELECT count(*) AS count FROM builderops_dead_letters "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
        reconciliations = conn.execute(
            "SELECT count(*) AS count FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
    assert dead_letters is not None and dead_letters["count"] == 0
    assert reconciliations is not None and reconciliations["count"] == 0


@pytest.mark.parametrize(
    ("case", "run_state"),
    (
        (
            "sessionful",
            {
                "coordinator_session_id": "01900000-0000-7000-8000-000000000099",
                "context_pack": {"head_sha": "a" * 40},
            },
        ),
        (
            "session_without_context",
            {
                "coordinator_session_id": "01900000-0000-7000-8000-000000000099",
                "context_pack": None,
            },
        ),
        (
            "context_without_session",
            {
                "coordinator_session_id": None,
                "context_pack": {"head_sha": "a" * 40},
            },
        ),
    ),
)
def test_terminal_unknown_rejects_session_bound_task_without_mutation(
    control_plane_store, envelope, case: str, run_state: dict
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id=f"task-model-effect-{case}",
        key=f"model-effect-{case}",
        effect_type="model.verification_coordinator",
        payload={"head_sha": "a" * 40},
        task_payload={
            "contract_version": "builderops_verification_run.v1",
            "run": run_state,
        },
    )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="verification-host",
    )
    control_plane_store.mark_effect_unknown(
        claim, detail="provider session state requires fail-closed recovery"
    )

    with pytest.raises(StateConflict, match="restricted"):
        control_plane_store.reconcile_outbox(
            claim,
            observed_applied=False,
            terminal_unknown=True,
            evidence={
                "head_sha": "a" * 40,
                "outcome": "indeterminate_pre_session_model_effect",
                "provider_session_id": None,
                "relaunch_performed": False,
            },
        )

    assert (
        control_plane_store.outbox_status(envelope.repository, result.operation_key)
        == "unknown"
    )
    with control_plane_store._connect() as conn:
        dead_letters = conn.execute(
            "SELECT count(*) AS count FROM builderops_dead_letters "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
        reconciliations = conn.execute(
            "SELECT count(*) AS count FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
    assert dead_letters is not None and dead_letters["count"] == 0
    assert reconciliations is not None and reconciliations["count"] == 0


@pytest.mark.parametrize(
    "fault_at",
    [
        "after_reconciliation_receipt",
        "after_reconciliation_state",
        "after_reconciliation_record",
    ],
)
def test_reconciliation_receipt_state_and_evidence_commit_atomically(
    control_plane_store, envelope, fault_at: str
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id=f"reconciliation-atomic-{fault_at}",
        key=f"reconciliation-atomic-{fault_at}",
        effect_type="github.merge",
        payload={"pr": 3852},
    )
    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="executor",
    )
    control_plane_store.mark_effect_unknown(claim, detail="response lost")
    receipt_count = control_plane_store.authority_counts(envelope.repository)["receipts"]

    with pytest.raises(RuntimeError, match=fault_at):
        control_plane_store.reconcile_outbox(
            claim,
            observed_applied=True,
            evidence={"readback": "found"},
            fault_at=fault_at,
        )

    assert control_plane_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert control_plane_store.authority_counts(envelope.repository)["receipts"] == receipt_count
    with control_plane_store._connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS count FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, result.operation_key),
        ).fetchone()
    assert row is not None
    assert row["count"] == 0


def test_claim_crash_before_lsn_binding_is_recoverable(control_plane_store, envelope) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="claim-binding-crash",
        key="claim-binding-crash",
        effect_type="github.merge",
        payload={"pr": 3852},
    )
    with pytest.raises(RuntimeError, match="after_claim_commit"):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="crashed-executor",
            fault_at="after_claim_commit",
        )

    recovered = type(control_plane_store)(control_plane_store.dsn)
    _expire_outbox_claim(
        recovered, envelope.repository, result.operation_key
    )
    orphaned_claim = recovered.outbox_claim(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="recovery-executor",
    )
    assert orphaned_claim.claim_lsn != "0/0"
    claim_receipt = recovered.receipt(envelope.repository, orphaned_claim.receipt_sequence)
    assert claim_receipt["recovery_lsn"] == orphaned_claim.claim_lsn
    assert recovered.outbox_status(envelope.repository, result.operation_key) == "unknown"
    assert recovered.effect_eligible(orphaned_claim) is False
    reconciliation = recovered.reconcile_outbox(
        orphaned_claim,
        observed_applied=False,
        evidence={"readback": "not-found"},
    )
    with recovered._connect() as conn:
        persisted = conn.execute(
            "SELECT claim_lsn::text AS claim_lsn FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s AND claim_fencing_token = %s",
            (envelope.repository, result.operation_key, orphaned_claim.fencing_token),
        ).fetchone()
    assert persisted is not None
    assert persisted["claim_lsn"] == orphaned_claim.claim_lsn
    assert reconciliation.claim_receipt_sequence == orphaned_claim.receipt_sequence
    retried = recovered.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="replacement-executor",
    )
    assert retried.fencing_token > orphaned_claim.fencing_token


def test_claim_binding_recovery_locks_identity_before_lsn_sampling(
    control_plane_store, envelope, monkeypatch
) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="claim-binding-race",
        key="claim-binding-race",
        effect_type="github.merge",
        payload={"pr": 3852},
    )
    with pytest.raises(RuntimeError, match="after_claim_commit"):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="crashed-executor",
            fault_at="after_claim_commit",
        )

    recovering = type(control_plane_store)(control_plane_store.dsn)
    contender = type(control_plane_store)(control_plane_store.dsn)
    _expire_outbox_claim(
        recovering, envelope.repository, result.operation_key
    )
    sampling_started = Event()
    release_sampling = Event()
    contender_started = Event()
    original_flushed_lsn = recovering._flushed_lsn

    def delayed_flushed_lsn() -> str:
        sampling_started.set()
        assert release_sampling.wait(timeout=10)
        return original_flushed_lsn()

    monkeypatch.setattr(recovering, "_flushed_lsn", delayed_flushed_lsn)

    def recover_first():
        return recovering.outbox_claim(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="recovery-executor",
        )

    def recover_concurrently():
        contender_started.set()
        return contender.outbox_claim(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="recovery-executor",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(recover_first)
        assert sampling_started.wait(timeout=10)
        contender_future = pool.submit(recover_concurrently)
        assert contender_started.wait(timeout=10)
        assert contender_future.done() is False
        release_sampling.set()
        first_claim = first_future.result(timeout=10)
        with pytest.raises(LeaseUnavailable, match="active claim"):
            contender_future.result(timeout=10)

    assert first_claim.claim_lsn != "0/0"
    reconciliation = recovering.reconcile_outbox(
        first_claim,
        observed_applied=False,
        evidence={"readback": "not-found"},
    )
    replacement = contender.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="replacement-executor",
    )
    assert replacement.fencing_token > first_claim.fencing_token
    with recovering._connect() as conn:
        historical = conn.execute(
            "SELECT claim_lsn::text AS claim_lsn FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s AND claim_fencing_token = %s",
            (envelope.repository, result.operation_key, first_claim.fencing_token),
        ).fetchone()
    assert historical is not None
    assert historical["claim_lsn"] == first_claim.claim_lsn
    assert reconciliation.claim_receipt_sequence == first_claim.receipt_sequence


def test_expired_claim_cannot_be_directly_reassigned(control_plane_store, envelope) -> None:
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="expired-claim",
        key="expired-claim",
        effect_type="github.merge",
        payload={"pr": 3852},
    )
    first = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="expired-executor",
        claim_ttl_seconds=1,
    )
    _expire_outbox_claim(control_plane_store, envelope.repository, result.operation_key)

    with pytest.raises(UnknownEffectNeedsReconciliation):
        control_plane_store.claim_outbox(
            envelope=envelope,
            operation_key=result.operation_key,
            worker_id="replacement-executor",
        )
    recovered = control_plane_store.outbox_claim(
        envelope=envelope,
        operation_key=result.operation_key,
        worker_id="recovery-executor",
    )
    assert recovered.operation_key == first.operation_key
    assert recovered.worker_id == "recovery-executor"
    assert recovered.fencing_token > first.fencing_token
    assert recovered.receipt_sequence > first.receipt_sequence
    assert control_plane_store.outbox_status(envelope.repository, result.operation_key) == "unknown"
