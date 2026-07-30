from __future__ import annotations

import json

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import VerificationConsumer
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
        base_reads=["b" * 40, "b" * 40, "b" * 40],
        manifest_blobs=["blob-1", "blob-1", "blob-1"],
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

    receipt = runtime.recover_dry_cycle(run.run_id)
    deferred = ledger.get(run.run_id)
    assert deferred is not None
    assert receipt["terminal_outcome"] == "retry_after_readback"
    assert deferred.status == "backoff"

    replay = runtime.recover_dry_cycle(run.run_id)

    assert replay == receipt
    assert ledger.get(run.run_id).status == "backoff"  # type: ignore[union-attr]
