from __future__ import annotations

import json

import pytest

from app.builderops.execution_routing import (
    ExecutionRouteRequest,
    ResolvedExecutionTarget,
    admit_phase2_canary,
    build_execution_routing_canary_receipt,
    create_execution_attempt,
)
from app.builderops.execution_routing_receipts import (
    CanaryReceiptEvidenceError,
    append_attempt_intent,
    append_attempt_outcome,
    bind_canary_receipt_to_verification_request,
)
from app.builderops.store import SqliteBuilderOpsStore
from app.builderops.control_plane import LeaseUnavailable
from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_consumer import VerificationConsumer
from app.dispatcher.verification_dispatch import (
    VerificationSubscriptionBusy,
)
from app.dispatcher.verification_merge import (
    MergeAuthorityError,
    VerificationMergeExecutor,
)
from app.dispatcher.verification_runtime import (
    HostFencedVerificationCycle,
    validated_containment_receipt_shape,
)
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

    terminal = api.tasks[str(receipt["run_id"])]["payload"]["run"][
        "terminal_receipt"
    ]
    terminal["merge_authority"]["credential_generation"] = 999
    with pytest.raises(ValueError, match="receipt is malformed"):
        runtime.recover_dry_cycle(str(receipt["run_id"]))
    terminal["merge_authority"]["credential_generation"] = 7

    pending = api.tasks[str(receipt["run_id"])]["payload"][
        "pending_privileged_effect"
    ]
    pending["head_sha"] = "e" * 40
    with pytest.raises(ValueError, match="receipt is malformed"):
        runtime.recover_dry_cycle(str(receipt["run_id"]))
    pending["head_sha"] = "a" * 40

    payload = pending["payload"]
    payload["repository"] = "someone/unrelated"
    with pytest.raises(ValueError, match="receipt is malformed"):
        runtime.recover_dry_cycle(str(receipt["run_id"]))
    payload["repository"] = REPO.lower()

    original_status = outbox.status

    def _boolean_sequence(operation_key: str):
        status = original_status(operation_key)
        return {**status, "reconciliation_receipt_sequence": True}

    outbox.status = _boolean_sequence  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="receipt is malformed"):
        runtime.recover_dry_cycle(str(receipt["run_id"]))
    outbox.status = original_status  # type: ignore[method-assign]

    operation_key = str(receipt["operation_key"])
    outbox.states[operation_key] = "pending"
    with pytest.raises(ValueError, match="receipt is malformed"):
        runtime.recover_dry_cycle(str(receipt["run_id"]))
    outbox.states[operation_key] = "succeeded"


def test_host_cycle_projects_linux_containment_into_durable_receipt() -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    containment_receipt: dict[str, object] = {
        "contract": "builderops_linux_containment.v1",
        "profile_name": "linux-systemd-cgroup-v2-scope-v1",
        "scope_identity": f"yggdrasil-verification-{'a' * 24}.scope",
        "evidence_digests": {
            "attach": "b" * 64,
            "cleanup": "c" * 64,
        },
        "outcome": "clean",
    }

    class LinuxVerifiedLauncher(VerifiedLauncher):
        containment_receipt_required = True

        def containment_receipt(self):
            return containment_receipt

    consumer = VerificationConsumer(
        ledger,
        Truth(eligible_pr(), GREEN),
        Auth(),
        LinuxVerifiedLauncher(),
        holder="verification-host",
    )
    repository = RepositoryAuthority()
    credentials = Credentials()
    runtime = HostFencedVerificationCycle(
        ledger,
        consumer,
        VerificationMergeExecutor(
            ledger, outbox, repository, credentials
        ),
        holder="verification-host",
        containment_receipt_required=True,
    )

    receipt = runtime.run_dry_cycle(request())

    assert receipt["containment"] == containment_receipt
    merge_ready = ledger.merge_ready_receipt(str(receipt["run_id"]))
    assert merge_ready is not None
    assert merge_ready["containment"] == containment_receipt
    terminal = api.tasks[str(receipt["run_id"])]["payload"]["run"][
        "terminal_receipt"
    ]
    assert terminal["containment"] == containment_receipt
    assert runtime.recover_dry_cycle(str(receipt["run_id"])) == receipt

    terminal.pop("containment")
    with pytest.raises(ValueError, match="receipt is malformed"):
        runtime.recover_dry_cycle(str(receipt["run_id"]))
    terminal["containment"] = {
        **containment_receipt,
        "scope_identity": f"yggdrasil-verification-{'d' * 24}.scope",
    }
    with pytest.raises(ValueError, match="receipt is malformed"):
        runtime.recover_dry_cycle(str(receipt["run_id"]))


def test_linux_cycle_requires_containment_in_merge_ready_evidence() -> None:
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
    credentials = Credentials()
    runtime = HostFencedVerificationCycle(
        ledger,
        consumer,
        VerificationMergeExecutor(
            ledger, outbox, repository, credentials
        ),
        holder="verification-host",
        containment_receipt_required=True,
    )

    with pytest.raises(
        ValueError, match="Linux containment evidence is unavailable"
    ):
        runtime.run_dry_cycle(request())

    run_id = next(iter(api.tasks))
    marker = ledger.merge_ready_receipt(run_id)
    assert marker is not None
    assert "containment" not in marker
    recovered = ledger.get(run_id)
    assert recovered is not None
    assert recovered.status == "running"
    assert repository.calls == []
    assert credentials.calls == []


def test_containment_receipt_validator_rejects_non_allowlisted_evidence() -> None:
    unsafe = {
        "contract": "builderops_linux_containment.v1",
        "profile_name": "linux-systemd-cgroup-v2-scope-v1",
        "scope_identity": f"yggdrasil-verification-{'a' * 24}.scope",
        "evidence_digests": {
            "attach": "b" * 64,
            "cleanup": "c" * 64,
        },
        "outcome": "clean",
        "cgroup_path": "/user.slice/private.scope",
    }

    with pytest.raises(ValueError, match="containment receipt is malformed"):
        validated_containment_receipt_shape(unsafe)


def test_pending_dry_recovery_rejects_contradictory_merge_evidence() -> None:
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
    credentials = Credentials()
    executor = VerificationMergeExecutor(
        ledger, outbox, repository, credentials
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
    credentials.calls.clear()

    with pytest.raises(
        MergeAuthorityError, match="reconciliation is contradictory"
    ):
        runtime.recover_dry_cycle(run.run_id)
    assert credentials.calls == []


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
    recovery_credentials = Credentials()
    runtime = HostFencedVerificationCycle(
        ledger,
        consumer,
        VerificationMergeExecutor(
            ledger, outbox, repository, recovery_credentials
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
    assert recovery_credentials.calls == [
        {
            "repository": REPO.lower(),
            "credential_id": "github-repo-merge",
            "rotation_generation": 7,
        }
    ]
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
    recovery_credentials = Credentials()
    runtime = HostFencedVerificationCycle(
        ledger,
        consumer,
        VerificationMergeExecutor(
            ledger, outbox, repository, recovery_credentials
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

    original_outbox_payload = dict(outbox.claims[operation_key]["payload"])
    outbox.claims[operation_key]["payload"] = {
        **original_outbox_payload,
        "repository": "someone/unrelated",
    }
    with pytest.raises(
        MergeAuthorityError, match="manifest binding is inconsistent"
    ):
        runtime.recover_dry_cycle(run.run_id)
    assert recovery_credentials.calls == []
    outbox.claims[operation_key]["payload"] = original_outbox_payload
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"

    class _UnavailableCredentials(Credentials):
        def resolve(self, **values):
            raise MergeAuthorityError(
                "exact recovery credential generation is unavailable"
            )

    runtime.merge_executor.credentials = _UnavailableCredentials()
    with pytest.raises(
        MergeAuthorityError, match="credential generation is unavailable"
    ):
        runtime.recover_dry_cycle(run.run_id)
    assert ledger.get(run.run_id).status != "completed"  # type: ignore[union-attr]

    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    outbox.claims[operation_key][
        "expires_at"
    ] = "2000-01-01T00:00:00+00:00"
    runtime.merge_executor.credentials = recovery_credentials

    receipt = runtime.recover_dry_cycle(run.run_id)

    assert receipt["terminal_outcome"] == "dry_run_no_merge"
    assert recovery_credentials.calls == [
        {
            "repository": REPO.lower(),
            "credential_id": "github-repo-merge",
            "rotation_generation": 7,
        }
    ]
    assert ledger.get(run.run_id).status == "completed"  # type: ignore[union-attr]
    assert outbox.states[operation_key] == "succeeded"


def test_host_cycle_consumes_canary_acceptance_on_verified_current_head(
    tmp_path,
) -> None:
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    canary_store = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    canary_store.initialize()
    route_request = ExecutionRouteRequest(
        request_id="execution-route-request-runtime-canary",
        repository=REPO,
        issue_number=3603,
        work_class="bounded_fast",
        risk="low",
        ambiguity="low",
        protected_surface=False,
        decision_at="2026-08-29T15:00:00Z",
        context_pack_hash="a" * 64,
        authority_hash="b" * 64,
        verification_profile_hash="c" * 64,
        shadow_against_capability="luna",
    )
    route_decision = admit_phase2_canary(
        route_request, opt_in=True, sample_index=1, sample_limit=1
    )
    attempt = create_execution_attempt(
        request=route_request,
        decision=route_decision,
        target=ResolvedExecutionTarget(
            capability="luna",
            provider="openai",
            model="gpt-5.6-luna",
            reasoning_effort="low",
            configuration_ref="builderops-test",
        ),
        attempt_number=1,
        mode="canary",
        outcome="started",
        observed_at="2026-08-29T15:00:01Z",
    )
    chain = append_attempt_intent(
        canary_store, route_request, route_decision, attempt
    )
    append_attempt_outcome(
        canary_store, chain, route_request, route_decision, attempt
    )
    canary_receipt = build_execution_routing_canary_receipt(
        request=route_request,
        decision=route_decision,
        attempts=(attempt,),
        accepted_delivery_verification="not_run",
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
        VerificationMergeExecutor(ledger, outbox, repository, Credentials()),
        holder="verification-host",
        canary_receipt_store=canary_store,
    )

    verification_request = bind_canary_receipt_to_verification_request(
        request(), canary_receipt
    )
    cycle_receipt = runtime.run_dry_cycle(
        verification_request, canary_receipt=canary_receipt
    )

    acceptance_records = [
        record
        for record in canary_store.list_records("BuilderOpsReceipt")
        if record["action"] == "canary_acceptance_observation"
    ]
    assert len(acceptance_records) == 1
    acceptance = json.loads(acceptance_records[0]["receipt_body"])
    assert acceptance["acceptance"]["status"] == "passed"
    assert cycle_receipt["terminal_outcome"] == "dry_run_no_merge"

    assert runtime.recover_dry_cycle(
        str(cycle_receipt["run_id"]), canary_receipt=canary_receipt
    ) == cycle_receipt
    assert len(
        [
            record
            for record in canary_store.list_records("BuilderOpsReceipt")
            if record["action"] == "canary_acceptance_observation"
        ]
    ) == 1


def _canary_runtime_fixture(tmp_path):
    api = FakeBuilderOpsClient()
    outbox = FakeVerificationOutbox(api)
    ledger = BuilderOpsVerificationLedger(
        api, repository=REPO, effect_outbox=outbox
    )
    canary_store = SqliteBuilderOpsStore(tmp_path / "builderops-lineage.sqlite3")
    canary_store.initialize()
    route_request = ExecutionRouteRequest(
        request_id="execution-route-request-runtime-lineage",
        repository=REPO,
        issue_number=3603,
        work_class="bounded_fast",
        risk="low",
        ambiguity="low",
        protected_surface=False,
        decision_at="2026-08-29T15:00:00Z",
        context_pack_hash="a" * 64,
        authority_hash="b" * 64,
        verification_profile_hash="c" * 64,
        shadow_against_capability="luna",
    )
    route_decision = admit_phase2_canary(
        route_request, opt_in=True, sample_index=1, sample_limit=1
    )
    attempt = create_execution_attempt(
        request=route_request,
        decision=route_decision,
        target=ResolvedExecutionTarget(
            capability="luna",
            provider="openai",
            model="gpt-5.6-luna",
            reasoning_effort="low",
            configuration_ref="builderops-test",
        ),
        attempt_number=1,
        mode="canary",
        outcome="started",
        observed_at="2026-08-29T15:00:01Z",
    )
    chain = append_attempt_intent(
        canary_store, route_request, route_decision, attempt
    )
    append_attempt_outcome(
        canary_store, chain, route_request, route_decision, attempt
    )
    canary_receipt = build_execution_routing_canary_receipt(
        request=route_request,
        decision=route_decision,
        attempts=(attempt,),
        accepted_delivery_verification="not_run",
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
        VerificationMergeExecutor(ledger, outbox, repository, Credentials()),
        holder="verification-host",
        canary_receipt_store=canary_store,
    )
    verification_request = bind_canary_receipt_to_verification_request(
        request(), canary_receipt
    )
    return runtime, canary_store, canary_receipt, verification_request


def test_canary_acceptance_requires_request_bound_lineage(tmp_path) -> None:
    runtime, canary_store, canary_receipt, verification_request = (
        _canary_runtime_fixture(tmp_path)
    )
    unbound_request = dict(verification_request)
    unbound_request.pop("canary_identity")

    with pytest.raises(CanaryReceiptEvidenceError, match="request lineage"):
        runtime.run_dry_cycle(unbound_request, canary_receipt=canary_receipt)

    assert [
        record
        for record in canary_store.list_records("BuilderOpsReceipt")
        if record["action"] == "canary_acceptance_observation"
    ] == []


def test_terminalization_failure_does_not_record_canary_acceptance(
    tmp_path, monkeypatch
) -> None:
    runtime, canary_store, canary_receipt, verification_request = (
        _canary_runtime_fixture(tmp_path)
    )

    def fail_terminalization(_run_id, _receipt):
        raise RuntimeError("terminalization failed")

    monkeypatch.setattr(runtime, "_complete", fail_terminalization)
    with pytest.raises(RuntimeError, match="terminalization failed"):
        runtime.run_dry_cycle(
            verification_request, canary_receipt=canary_receipt
        )

    assert [
        record
        for record in canary_store.list_records("BuilderOpsReceipt")
        if record["action"] == "canary_acceptance_observation"
    ] == []


def test_retry_after_readback_does_not_record_canary_acceptance(
    tmp_path, monkeypatch
) -> None:
    runtime, canary_store, canary_receipt, verification_request = (
        _canary_runtime_fixture(tmp_path)
    )
    retry_receipt = {"terminal_outcome": "retry_after_readback"}
    monkeypatch.setattr(
        runtime,
        "_finish_ready_dry_cycle",
        lambda _run_id: retry_receipt,
    )

    assert (
        runtime.run_dry_cycle(
            verification_request, canary_receipt=canary_receipt
        )
        == retry_receipt
    )
    assert [
        record
        for record in canary_store.list_records("BuilderOpsReceipt")
        if record["action"] == "canary_acceptance_observation"
    ] == []


def test_recovery_retry_after_readback_does_not_record_canary_acceptance(
    tmp_path, monkeypatch
) -> None:
    runtime, canary_store, canary_receipt, verification_request = (
        _canary_runtime_fixture(tmp_path)
    )
    run = runtime.consumer.consume(verification_request)
    task = runtime.ledger.client.tasks[run.run_id]
    assert task["lease"] is not None
    task["lease"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    retry_receipt = {"terminal_outcome": "retry_after_readback"}
    monkeypatch.setattr(
        runtime,
        "_finish_ready_dry_cycle",
        lambda _run_id: retry_receipt,
    )

    assert (
        runtime.recover_dry_cycle(
            run.run_id, canary_receipt=canary_receipt
        )
        == retry_receipt
    )
    assert [
        record
        for record in canary_store.list_records("BuilderOpsReceipt")
        if record["action"] == "canary_acceptance_observation"
    ] == []
