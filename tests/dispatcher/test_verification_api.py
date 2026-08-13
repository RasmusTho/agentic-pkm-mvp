from __future__ import annotations

from copy import deepcopy

import pytest

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from tests.dispatcher.builderops_verification_fakes import (
    FakeBuilderOpsClient,
    FakeVerificationOutbox,
)
from tests.dispatcher.verification_helpers import HEAD, REPO, request


def _claimed_merge_effect():
    client = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(client)
    ledger = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    payload = {
        "repository": REPO.lower(),
        "pr_number": run.pr_number,
        "head_sha": HEAD,
    }
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.post_effect_reconciliation.test",
        payload=payload,
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="post-effect-phase-test",
    )
    claim = ledger.effect_claim(operation_key)
    identity = {
        "operation_key": operation_key,
        "fencing_token": claim["fencing_token"],
        "repository": REPO.lower(),
        "task_id": run.run_id,
        "pr_number": run.pr_number,
        "head_sha": HEAD,
    }
    return ledger, outbox, operation_key, identity


def test_post_effect_reconciliation_phase_requires_exact_fenced_identity() -> None:
    ledger, outbox, operation_key, identity = _claimed_merge_effect()

    pending = ledger.begin_post_effect_reconciliation(
        operation_key,
        identity=identity,
    )

    assert pending["phase"] == "pending"
    assert pending["identity"] == identity
    assert outbox.status(operation_key)["post_effect_reconciliation"] == pending

    for field, drift in (
        ("operation_key", "wrong-operation"),
        ("fencing_token", int(identity["fencing_token"]) + 1),
        ("repository", "someone/else"),
        ("pr_number", int(identity["pr_number"]) + 1),
        ("head_sha", "b" * 40),
    ):
        malformed = {**identity, field: drift}
        with pytest.raises(ValueError, match="exact fenced identity"):
            ledger.reconcile_post_effect(
                operation_key,
                identity=malformed,
                readback={
                    "merged": True,
                    "head_sha": HEAD,
                    "merge_commit_sha": "c" * 40,
                },
            )

    assert (
        outbox.status(operation_key)["post_effect_reconciliation"]["phase"]
        == "pending"
    )


def test_post_effect_reconciliation_phase_is_idempotent_and_rejects_conflicts() -> None:
    ledger, outbox, operation_key, identity = _claimed_merge_effect()
    readback = {
        "merged": True,
        "head_sha": HEAD,
        "merge_commit_sha": "c" * 40,
    }

    with pytest.raises(ValueError, match="pending"):
        ledger.reconcile_post_effect(
            operation_key,
            identity=identity,
            readback=readback,
        )

    pending = ledger.begin_post_effect_reconciliation(
        operation_key,
        identity=identity,
    )
    assert ledger.begin_post_effect_reconciliation(
        operation_key,
        identity=identity,
    ) == pending

    reconciled = ledger.reconcile_post_effect(
        operation_key,
        identity=identity,
        readback=readback,
    )
    assert reconciled["phase"] == "reconciled"
    assert ledger.reconcile_post_effect(
        operation_key,
        identity=identity,
        readback=deepcopy(readback),
    ) == reconciled

    with pytest.raises(ValueError, match="conflicting"):
        ledger.reconcile_post_effect(
            operation_key,
            identity=identity,
            readback={**readback, "merge_commit_sha": "d" * 40},
        )
    with pytest.raises(ValueError, match="reordered"):
        ledger.begin_post_effect_reconciliation(
            operation_key,
            identity=identity,
        )


def test_finish_effect_legacy_callers_remain_unchanged() -> None:
    ledger, outbox, operation_key, _identity = _claimed_merge_effect()
    evidence = {"outcome": "legacy-success"}

    assert ledger.finish_effect(
        operation_key,
        observed_applied=True,
        evidence=evidence,
    ) is None
    status = outbox.status(operation_key)
    assert status["status"] == "succeeded"
    assert status["reconciliation_evidence"] == evidence
    assert status.get("post_effect_reconciliation") is None
