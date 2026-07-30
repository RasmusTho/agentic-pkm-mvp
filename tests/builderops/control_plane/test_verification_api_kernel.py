from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneConflictError,
    ControlPlaneScopeError,
)
from app.builderops.control_plane.models import StateConflict
from app.builderops.control_plane.service import create_app
from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_merge import BuilderOpsOutboxExecutor
from tests.dispatcher.verification_helpers import REPO, request

pytestmark = pytest.mark.pg


def test_concurrent_attempts_share_one_task_version_cas(
    control_plane_store, envelope
) -> None:
    task_id = "vrun-attempt-cas"
    control_plane_store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key="attempt-cas-create",
        request={"status": "ready"},
    )
    _, lease = control_plane_store.claim_task(
        envelope=envelope,
        task_id=task_id,
        holder="executor:attempt-cas",
        idempotency_key="attempt-cas-claim",
        request={"status": "claimed"},
    )
    expected_version = int(
        control_plane_store.get_task(envelope.repository, task_id)["version"]
    )
    barrier = Barrier(2)

    def commit(index: int) -> str:
        barrier.wait()
        try:
            control_plane_store.commit_attempt(
                envelope=envelope,
                task_id=task_id,
                attempt_id=f"concurrent-attempt-{index}",
                state="verification",
                payload={"ordinal": index},
                idempotency_key=f"concurrent-attempt-{index}",
                lease=lease,
                expected_task_version=expected_version,
            )
        except StateConflict:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(commit, (1, 2)))

    assert sorted(outcomes) == ["committed", "conflict"]
    attempts = control_plane_store.list_attempts(
        envelope.repository, task_id
    )
    assert len(attempts) == 1
    assert (
        int(control_plane_store.get_task(envelope.repository, task_id)["version"])
        == expected_version + 1
    )


def test_stale_task_version_rejects_transition_attempt_release_and_complete(
    control_plane_store, envelope
) -> None:
    task_id = "vrun-version-cas"
    control_plane_store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key="version-create",
        request={"status": "ready"},
    )
    _, lease = control_plane_store.claim_task(
        envelope=envelope,
        task_id=task_id,
        holder="executor:version-cas",
        idempotency_key="version-claim",
        request={"status": "claimed"},
    )
    stale_version = int(
        control_plane_store.get_task(envelope.repository, task_id)["version"]
    )
    control_plane_store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="claimed",
        idempotency_key="version-advance",
        request={"status": "running"},
        lease=lease,
        expected_states=("claimed",),
        expected_version=stale_version,
    )

    with pytest.raises(StateConflict, match="expected task version"):
        control_plane_store.commit_transition(
            envelope=envelope,
            task_id=task_id,
            to_state="claimed",
            idempotency_key="version-stale-transition",
            request={"status": "stale"},
            lease=lease,
            expected_states=("claimed",),
            expected_version=stale_version,
        )
    with pytest.raises(StateConflict, match="expected task version"):
        control_plane_store.commit_attempt(
            envelope=envelope,
            task_id=task_id,
            attempt_id="stale-attempt",
            state="verification",
            payload={"outcome": "stale"},
            idempotency_key="version-stale-attempt",
            lease=lease,
            expected_task_version=stale_version,
        )
    with pytest.raises(StateConflict, match="expected task version"):
        control_plane_store.release_task(
            envelope=envelope,
            lease=lease,
            idempotency_key="version-stale-release",
            request={"status": "backoff"},
            expected_version=stale_version,
        )
    with pytest.raises(StateConflict, match="expected task version"):
        control_plane_store.complete_task(
            envelope=envelope,
            lease=lease,
            idempotency_key="version-stale-complete",
            request={"status": "completed"},
            expected_version=stale_version,
        )


def test_verification_task_attempt_and_outbox_share_postgres_authority(
    control_plane_store, envelope
) -> None:
    store = control_plane_store
    task_id = "vrun-api-kernel"
    payload = {
        "contract_version": "builderops_verification_run.v1",
        "run": {"run_id": task_id, "status": "queued"},
        "exceptions": [],
    }
    store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key="verification-create",
        request=payload,
    )
    snapshot = store.get_task(envelope.repository, task_id)
    assert snapshot["payload"] == payload
    assert snapshot["lease"] is None
    assert [row["task_id"] for row in store.list_tasks(
        envelope.repository, task_prefix="vrun-"
    )] == [task_id]

    _, lease = store.claim_task(
        envelope=envelope,
        task_id=task_id,
        holder="demerzel-verifier",
        idempotency_key="verification-claim",
        request={**payload, "run": {"run_id": task_id, "status": "claimed"}},
    )
    store.commit_attempt(
        envelope=envelope,
        task_id=task_id,
        attempt_id="vattempt-1",
        state="verification",
        payload={"ordinal": 1, "outcome": "passed"},
        idempotency_key="verification-attempt-1",
        lease=lease,
    )
    transition = store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="claimed",
        idempotency_key="verification-effect-1",
        request={**payload, "run": {"run_id": task_id, "status": "running"}},
        lease=lease,
        expected_states=("claimed",),
        outbox={
            "effect_type": "github.merge",
            "payload": {"repository": envelope.repository, "pr_number": 3603},
        },
    )

    assert [row["attempt_id"] for row in store.list_attempts(
        envelope.repository, task_id
    )] == ["vattempt-1"]
    assert transition.operation_key is not None
    intent = store.outbox_intent(envelope.repository, transition.operation_key)
    assert intent["task_id"] == task_id
    assert intent["effect_type"] == "github.merge"
    claim = store.claim_outbox(
        envelope=envelope,
        operation_key=transition.operation_key,
        worker_id="demerzel-verifier",
    )
    assert store.effect_eligible(claim) is True
    recovered = store.outbox_claim(envelope.repository, transition.operation_key)
    reconciliation = store.reconcile_outbox(
        recovered,
        observed_applied=False,
        evidence={"readback": "not_merged"},
    )
    assert reconciliation.status == "pending"


def test_verification_adapter_round_trips_only_through_authenticated_api(
    control_plane_store, tmp_path
) -> None:
    secret = tmp_path / "executor.secret"
    secret.write_text("verification-executor-token\n", encoding="utf-8")
    manifest = tmp_path / "credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "verification-executor",
                        "principal": "executor:demerzel-verifier",
                        "secret_ref": "host-secret:verification-executor",
                        "secret_file": str(secret),
                        "scopes": [
                            "status:read",
                            "receipts:read",
                            "tasks:write",
                            "attempts:write",
                            "outbox:write",
                        ],
                        "repositories": [REPO],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    transport = TestClient(
        create_app(
            store=control_plane_store,
            credentials=CredentialRegistry(manifest),
        )
    )
    client = BuilderOpsControlPlaneClient(
        ClientConfig(
            base_url="http://testserver",
            token="verification-executor-token",
        ),
        http_client=transport,  # type: ignore[arg-type]
    )
    outbox = BuilderOpsOutboxExecutor(
        client,
        repository=REPO,
        worker_id="demerzel-verifier",
    )
    ledger = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
    )

    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    assert claimed.lease_id is not None
    dry_run_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.merge.dry_run",
        payload={
            "repository": REPO.lower(),
            "pr_number": 3603,
            "head_sha": "a" * 40,
        },
        holder="executor:demerzel-verifier",
        lease_id=claimed.lease_id,
        idempotency_key="api-roundtrip-dry-run",
    )
    ledger.finish_effect(
        dry_run_key,
        observed_applied=True,
        evidence={"outcome": "dry_run_no_merge", "merged": False},
    )
    assert control_plane_store.outbox_status(REPO, dry_run_key) == "succeeded"

    indeterminate_key = ledger.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={
            "repository": REPO.lower(),
            "pr_number": 3603,
            "head_sha": "a" * 40,
        },
        holder="executor:demerzel-verifier",
        lease_id=claimed.lease_id,
        idempotency_key="api-roundtrip-indeterminate-model-effect",
    )
    restarted = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
    )
    restarted.recover_effect(
        indeterminate_key,
        run_id=run.run_id,
        effect_type="model.verification_coordinator",
    )
    restarted.finish_effect(
        indeterminate_key,
        observed_applied=False,
        terminal_unknown=True,
        evidence={
            "outcome": "indeterminate_pre_session_model_effect",
            "provider_session_id": None,
            "relaunch_performed": False,
        },
    )

    assert (
        control_plane_store.outbox_status(REPO, indeterminate_key)
        == "dead_letter"
    )

    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.merge",
        payload={
            "repository": REPO.lower(),
            "pr_number": 3603,
            "head_sha": "a" * 40,
        },
        holder="executor:demerzel-verifier",
        lease_id=claimed.lease_id,
        idempotency_key="api-roundtrip-effect",
    )

    restarted = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
    )
    restarted.recover_effect(
        operation_key,
        run_id=run.run_id,
        effect_type="github.merge",
    )
    restarted.finish_effect(
        operation_key,
        observed_applied=False,
        evidence={"readback": "not_merged"},
    )

    assert control_plane_store.outbox_status(REPO, operation_key) == "pending"


def test_api_binds_task_lease_to_principal_and_restricts_public_lifecycle(
    control_plane_store, tmp_path
) -> None:
    credentials = []
    for suffix in ("a", "b"):
        secret = tmp_path / f"executor-{suffix}.secret"
        secret.write_text(f"executor-{suffix}-token\n", encoding="utf-8")
        credentials.append(
            {
                "id": f"executor-{suffix}",
                "principal": f"executor:{suffix}",
                "secret_ref": f"host-secret:executor-{suffix}",
                "secret_file": str(secret),
                "scopes": [
                    "status:read",
                    "receipts:read",
                    "tasks:write",
                    "attempts:write",
                    "outbox:write",
                ],
                "repositories": [REPO],
                "rotation_generation": 1,
            }
        )
    manifest = tmp_path / "two-principals.json"
    manifest.write_text(
        json.dumps({"credentials": credentials}), encoding="utf-8"
    )
    transport = TestClient(
        create_app(
            store=control_plane_store,
            credentials=CredentialRegistry(manifest),
        )
    )
    client_a = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="http://testserver", token="executor-a-token"),
        http_client=transport,  # type: ignore[arg-type]
    )
    client_b = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="http://testserver", token="executor-b-token"),
        http_client=transport,  # type: ignore[arg-type]
    )
    envelope = {
        "repository": REPO,
        "scope": "verification",
        "stack": "builderops-control-plane",
        "source_refs": ["github-issue:3603"],
        "schema_version": 1,
    }
    client_a.transition_task(
        envelope=envelope,
        task_id="vrun-principal-binding",
        to_state="ready",
        idempotency_key="principal-create",
        request={"status": "ready"},
    )
    claim = client_a.claim_task(
        envelope=envelope,
        task_id="vrun-principal-binding",
        idempotency_key="principal-claim",
    )
    lease = claim["lease"]
    version = int(
        client_a.get_task(
            repository=REPO, task_id="vrun-principal-binding"
        )["version"]
    )

    forbidden_calls = (
        lambda: client_b.heartbeat_task(
            envelope=envelope,
            lease=lease,
            idempotency_key="principal-b-heartbeat",
        ),
        lambda: client_b.transition_task(
            envelope=envelope,
            task_id="vrun-principal-binding",
            to_state="claimed",
            idempotency_key="principal-b-transition",
            request={"status": "stolen"},
            lease=lease,
            expected_states=("claimed",),
            expected_version=version,
        ),
        lambda: client_b.commit_attempt(
            envelope=envelope,
            task_id="vrun-principal-binding",
            attempt_id="principal-b-attempt",
            state="verification",
            payload={"outcome": "stolen"},
            idempotency_key="principal-b-attempt",
            lease=lease,
            expected_task_version=version,
        ),
        lambda: client_b.release_task(
            envelope=envelope,
            lease=lease,
            idempotency_key="principal-b-release",
            expected_version=version,
        ),
        lambda: client_b.complete_task(
            envelope=envelope,
            lease=lease,
            idempotency_key="principal-b-complete",
            expected_version=version,
        ),
    )
    for call in forbidden_calls:
        with pytest.raises(ControlPlaneScopeError):
            call()

    ledger = BuilderOpsVerificationLedger(client_a, repository=REPO)
    verification_run = ledger.ingest(request())
    first_claim = ledger.claim(verification_run.run_id, "ignored-holder")
    assert first_claim.claimed_by == "executor:a"
    assert first_claim.lease_id is not None
    first_heartbeat = ledger.heartbeat(
        verification_run.run_id,
        first_claim.claimed_by,
        first_claim.lease_id,
    )
    assert first_heartbeat.lease_id is not None
    second_heartbeat = ledger.heartbeat(
        verification_run.run_id,
        first_heartbeat.claimed_by or "",
        first_heartbeat.lease_id,
    )
    assert second_heartbeat.lease_id is not None

    with pytest.raises(ControlPlaneConflictError):
        client_a.transition_task(
            envelope=envelope,
            task_id="arbitrary-terminal",
            to_state="completed",
            idempotency_key="invalid-create-completed",
            request={"status": "completed"},
        )
    with pytest.raises(ControlPlaneConflictError):
        client_a.transition_task(
            envelope=envelope,
            task_id="vrun-principal-binding",
            to_state="ready",
            idempotency_key="invalid-retained-ready",
            request={"status": "ready"},
            lease=lease,
            expected_states=("claimed",),
            expected_version=version,
        )

    cross_repo = transport.post(
        "/v1/executor/outbox/unknown",
        headers={
            "Authorization": "Bearer executor-a-token",
            "X-BuilderOps-Authority-Epoch": "1",
        },
        json={
            "envelope": envelope,
            "claim": {
                "repository": "other/repository",
                "operation_key": "cross-repo-operation",
                "worker_id": "executor:a",
                "fencing_token": 1,
                "intent_lsn": "0/1",
                "claim_lsn": "0/2",
                "receipt_sequence": 1,
                "expires_at": "2099-01-01T00:00:00Z",
            },
            "detail": "must be rejected before store lookup",
        },
    )
    assert cross_repo.status_code == 403

    outbox_a = BuilderOpsOutboxExecutor(
        client_a,
        repository=REPO,
        worker_id="executor:a",
    )
    ledger.effect_outbox = outbox_a
    operation_key = ledger.begin_effect(
        verification_run.run_id,
        effect_type="model.verification_coordinator",
        payload={
            "repository": REPO,
            "head_sha": verification_run.current_head_sha,
        },
        holder=first_heartbeat.claimed_by or "",
        lease_id=second_heartbeat.lease_id,
        idempotency_key="principal-bound-effect",
    )
    claim_identity = ledger.effect_claim(operation_key)

    with pytest.raises(ControlPlaneScopeError):
        client_b.recover_outbox(
            envelope=envelope,
            operation_key=operation_key,
        )
    with pytest.raises(ControlPlaneScopeError):
        client_b.mark_outbox_unknown(
            envelope=envelope,
            claim=claim_identity,
            detail="cross-principal mutation must fail",
        )
    with pytest.raises(ControlPlaneScopeError):
        client_b.reconcile_outbox(
            envelope=envelope,
            claim=claim_identity,
            observed_applied=False,
            evidence={"outcome": "cross-principal mutation must fail"},
        )
