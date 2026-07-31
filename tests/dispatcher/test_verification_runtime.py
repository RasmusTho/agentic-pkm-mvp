from __future__ import annotations

import json

import pytest

from app.builderops.control_plane import LeaseUnavailable
from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import VerificationConsumer
from app.dispatcher.verification_dispatch import (
    VerificationSubscriptionBusy,
)
from app.dispatcher.verification_merge import VerificationMergeExecutor
from app.dispatcher.verification_runtime import HostFencedVerificationCycle
from tests.dispatcher.builderops_verification_fakes import (
    FakeBuilderOpsClient,
    FakeVerificationOutbox,
)
from tests.dispatcher.test_verification_consumer import (
    Auth,
    GREEN,
    Truth,
    eligible_pr,
)
from tests.dispatcher.test_verification_merge import (
    CrashCredentials,
    Credentials,
    RepositoryAuthority,
)
from tests.dispatcher.test_verification_recovery import VerifiedLauncher
from tests.dispatcher.verification_helpers import REPO, request


def test_host_cycle_is_api_only_and_emits_terminal_dry_run_receipt() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        VerifiedLauncher(),
        holder="verification-host",
    )
    repository = RepositoryAuthority()
    executor = VerificationMergeExecutor(
        ledger, outbox, repository, Credentials()
    )
    runtime = HostFencedVerificationCycle(
        ledger, consumer, executor, holder="verification-host"
    )

    receipt = runtime.run_dry_cycle(request())

    assert receipt["contract"] == "bcp05_demerzel_cycle.v1"
    assert receipt["terminal_outcome"] == "dry_run_no_merge"
    assert receipt["raw_secret_count"] == 0
    assert receipt["repository"] == REPO.lower()
    run = ledger.get(str(receipt["run_id"]))
    assert run is not None
    assert run.status == "completed"
    assert repository.calls == []
    durable = json.dumps(api.calls, default=str)
    assert "sqlite" not in durable.lower()

    replay = runtime.recover_dry_cycle(str(receipt["run_id"]))

    assert replay == receipt
    assert repository.calls == []


def test_pending_dry_recovery_stays_deferred_and_replayable() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        VerifiedLauncher(),
        holder="verification-host",
    )
    repository = RepositoryAuthority(
        base_reads=["b" * 40] * 6,
        manifest_blobs=["blob-1"] * 6,
    )
    executor = VerificationMergeExecutor(
        ledger, outbox, repository, Credentials()
    )
    runtime = HostFencedVerificationCycle(
        ledger, consumer, executor, holder="verification-host"
    )
    run = consumer.consume(request())
    assert run.lease_id is not None
    merge_receipt = executor.execute(
        run,
        holder="verification-host",
        lease_id=run.lease_id,
        dry_run=True,
    )
    outbox.states[merge_receipt.operation_key] = "pending"
    outbox.evidence[merge_receipt.operation_key] = {
        "merged": True,
        "head_sha": run.current_head_sha,
        "merge_commit_sha": "d" * 40,
    }
    task = api.tasks[run.run_id]
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    receipt = runtime.recover_dry_cycle(run.run_id)
    deferred = ledger.get(run.run_id)
    assert deferred is not None
    assert receipt["terminal_outcome"] == "retry_after_readback"
    assert deferred.status == "backoff"

    replay = runtime.recover_dry_cycle(run.run_id)

    assert replay == receipt
    assert ledger.get(run.run_id).status == "backoff"  # type: ignore[union-attr]


def test_recovery_refuses_a_live_task_owner_before_outbox_access() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        VerifiedLauncher(),
        holder="verification-host",
    )
    executor = VerificationMergeExecutor(
        ledger, outbox, RepositoryAuthority(), Credentials()
    )
    runtime = HostFencedVerificationCycle(
        ledger, consumer, executor, holder="verification-host"
    )
    run = consumer.consume(request())

    with pytest.raises(
        VerificationSubscriptionBusy, match="live task owner"
    ):
        runtime.recover_dry_cycle(run.run_id)

    assert "recover" not in outbox.calls


def test_recovery_rebinds_expired_task_lease_after_merge_readiness() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        VerifiedLauncher(),
        holder="verification-host",
    )
    repository = RepositoryAuthority()
    runtime = HostFencedVerificationCycle(
        ledger,
        consumer,
        VerificationMergeExecutor(
            ledger, outbox, repository, Credentials()
        ),
        holder="verification-host",
    )
    run = consumer.consume(request())
    old_lease_id = run.lease_id
    task = api.tasks[run.run_id]
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    receipt = runtime.recover_dry_cycle(run.run_id)

    completed = ledger.get(run.run_id)
    assert completed is not None
    assert completed.status == "completed"
    assert receipt["terminal_outcome"] == "dry_run_no_merge"
    claim_calls = [
        values for name, values in api.calls if name == "claim_task"
    ]
    assert len(claim_calls) == 2
    completed_lease_ids = [
        values["lease"]["fencing_token"]
        for name, values in api.calls
        if name == "complete_task"
    ]
    assert completed_lease_ids == [2]
    assert old_lease_id != "2"


def test_recovery_rejects_same_task_fence_before_outbox_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        VerifiedLauncher(),
        holder="verification-host",
    )
    runtime = HostFencedVerificationCycle(
        ledger,
        consumer,
        VerificationMergeExecutor(
            ledger, outbox, RepositoryAuthority(), Credentials()
        ),
        holder="verification-host",
    )
    run = consumer.consume(request())
    monkeypatch.setattr(runtime, "_lease_is_live", lambda _run: False)
    monkeypatch.setattr(
        ledger,
        "claim",
        lambda _run_id, _holder: run,
    )

    with pytest.raises(
        VerificationSubscriptionBusy, match="fresh task fence"
    ):
        runtime.recover_dry_cycle(run.run_id)

    assert "recover" not in outbox.calls


def test_recovery_waits_for_live_outbox_owner_then_converges() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        VerifiedLauncher(),
        holder="verification-host",
    )
    repository = RepositoryAuthority(
        base_reads=["b" * 40] * 6,
        manifest_blobs=["blob-1"] * 6,
    )
    runtime = HostFencedVerificationCycle(
        ledger,
        consumer,
        VerificationMergeExecutor(
            ledger, outbox, repository, Credentials()
        ),
        holder="verification-host",
    )
    run = consumer.consume(request())
    assert run.lease_id is not None
    with pytest.raises(SystemExit, match="after outbox claim"):
        VerificationMergeExecutor(
            ledger, outbox, repository, CrashCredentials()
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id,
            dry_run=True,
        )
    pending = ledger.pending_effect_binding(run.run_id)
    assert pending is not None
    operation_key = str(pending["operation_key"])
    task = api.tasks[run.run_id]
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    with pytest.raises(LeaseUnavailable, match="active claim"):
        runtime.recover_dry_cycle(run.run_id)

    assert outbox.states[operation_key] == "claimed"
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    outbox.claims[operation_key][
        "expires_at"
    ] = "2000-01-01T00:00:00+00:00"

    receipt = runtime.recover_dry_cycle(run.run_id)

    assert receipt["terminal_outcome"] == "dry_run_no_merge"
    assert ledger.get(run.run_id).status == "completed"  # type: ignore[union-attr]
    assert outbox.states[operation_key] == "succeeded"
