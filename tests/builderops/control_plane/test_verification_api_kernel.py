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
    ControlPlaneProtocolError,
    ControlPlaneScopeError,
    StaleLeaseError,
)
from app.builderops.control_plane.models import LeaseUnavailable, StateConflict
from app.builderops.control_plane.service import create_app
from app.builderops.control_plane.store import _operation_key
from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_merge import BuilderOpsOutboxExecutor
from tests.dispatcher.verification_helpers import REPO, request

pytestmark = pytest.mark.pg


def _expire_outbox_claim(
    store, repository: str, operation_key: str
) -> None:
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET claim_expires_at = "
            "clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND operation_key = %s",
            (repository.lower(), operation_key),
        )


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


def test_active_merge_intent_atomically_seals_attempt_writes(
    control_plane_store, envelope
) -> None:
    task_id = "vrun-merge-attempt-seal"
    transition_key = "verification-effect:merge-attempt-seal"
    operation_key = _operation_key(
        envelope.repository,
        transition_key,
        "github.merge",
    )
    control_plane_store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="ready",
        idempotency_key="merge-attempt-seal-create",
        request={"status": "ready"},
    )
    _, lease = control_plane_store.claim_task(
        envelope=envelope,
        task_id=task_id,
        holder="executor:merge-attempt-seal",
        idempotency_key="merge-attempt-seal-claim",
        request={"status": "claimed"},
    )
    expected_version = int(
        control_plane_store.get_task(
            envelope.repository,
            task_id,
        )["version"]
    )
    result = control_plane_store.commit_transition(
        envelope=envelope,
        task_id=task_id,
        to_state="claimed",
        idempotency_key=transition_key,
        request={
            "status": "claimed",
            "attempt_write_seal": {
                "contract": "builderops_attempt_write_seal.v1",
                "operation_key": operation_key,
                "effect_type": "github.merge",
                "review_authority_sha256": "a" * 64,
            },
        },
        outbox={
            "effect_type": "github.merge",
            "payload": {"head_sha": "b" * 40},
        },
        lease=lease,
        expected_states=("claimed",),
        expected_version=expected_version,
    )
    assert result.operation_key == operation_key
    sealed_version = int(
        control_plane_store.get_task(
            envelope.repository,
            task_id,
        )["version"]
    )

    with pytest.raises(
        StateConflict,
        match="attempt writes are sealed",
    ):
        control_plane_store.commit_attempt(
            envelope=envelope,
            task_id=task_id,
            attempt_id="late-blocking-review",
            state="review",
            payload={"outcome": "blocking"},
            idempotency_key="late-blocking-review",
            lease=lease,
            expected_task_version=sealed_version,
        )

    claim = control_plane_store.claim_outbox(
        envelope=envelope,
        operation_key=operation_key,
        worker_id="demerzel-verifier",
    )
    control_plane_store.mark_effect_unknown(
        claim,
        detail="merge effect reached terminal no-effect readback",
    )
    control_plane_store.reconcile_outbox(
        claim,
        observed_applied=True,
        evidence={"outcome": "terminal_no_effect"},
    )
    with pytest.raises(
        StateConflict,
        match="attempt writes are sealed",
    ):
        control_plane_store.commit_attempt(
            envelope=envelope,
            task_id=task_id,
            attempt_id="post-settlement-review",
            state="review",
            payload={"outcome": "blocking"},
            idempotency_key="post-settlement-review",
            lease=lease,
            expected_task_version=sealed_version,
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
    with pytest.raises(LeaseUnavailable, match="active claim"):
        store.outbox_claim(
            envelope=envelope,
            operation_key=transition.operation_key,
            worker_id="demerzel-recovery",
        )
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET claim_expires_at = "
            "clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND operation_key = %s",
            (envelope.repository, transition.operation_key),
        )
    recovered = store.outbox_claim(
        envelope=envelope,
        operation_key=transition.operation_key,
        worker_id="demerzel-recovery",
    )
    reconciliation = store.reconcile_outbox(
        recovered,
        observed_applied=False,
        evidence={"readback": "not_merged"},
    )
    assert reconciliation.status == "pending"


def _authenticated_api_ledger(
    control_plane_store, tmp_path
) -> tuple[
    BuilderOpsVerificationLedger,
    BuilderOpsControlPlaneClient,
    BuilderOpsOutboxExecutor,
]:
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
    return ledger, client, outbox


def test_verification_adapter_round_trips_only_through_authenticated_api(
    control_plane_store, tmp_path
) -> None:
    ledger, client, outbox = _authenticated_api_ledger(
        control_plane_store, tmp_path
    )

    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    assert claimed.lease_id is not None
    completed_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.comment",
        payload={
            "repository": REPO.lower(),
            "pr_number": 3603,
            "head_sha": "a" * 40,
        },
        holder="executor:demerzel-verifier",
        lease_id=claimed.lease_id,
        idempotency_key="api-roundtrip-completed-github-effect",
    )
    ledger.finish_effect(
        completed_key,
        observed_applied=True,
        evidence={"outcome": "comment_created"},
    )
    assert control_plane_store.outbox_status(REPO, completed_key) == "succeeded"

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
    _expire_outbox_claim(
        control_plane_store, REPO, indeterminate_key
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
            "head_sha": "a" * 40,
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
        effect_type="github.comment",
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
    _expire_outbox_claim(control_plane_store, REPO, operation_key)
    restarted.recover_effect(
        operation_key,
        run_id=run.run_id,
        effect_type="github.comment",
    )
    restarted.finish_effect(
        operation_key,
        observed_applied=False,
        evidence={"readback": "not_merged"},
    )

    assert control_plane_store.outbox_status(REPO, operation_key) == "pending"


def test_authenticated_recovery_claim_rejects_live_same_principal_task(
    control_plane_store, tmp_path
) -> None:
    ledger, client, _outbox = _authenticated_api_ledger(
        control_plane_store, tmp_path
    )
    run = ledger.ingest(request())
    ledger.claim(run.run_id, "ignored-client-holder")
    before = control_plane_store.get_task(REPO, run.run_id)

    with pytest.raises(StaleLeaseError, match="LeaseUnavailable"):
        client.claim_task(
            envelope=ledger.envelope,
            task_id=run.run_id,
            idempotency_key="api-live-same-principal-recovery",
            request={"must_not": "overwrite-live-owner"},
            require_new_fence=True,
        )

    after = control_plane_store.get_task(REPO, run.run_id)
    assert after["version"] == before["version"]
    assert after["payload"] == before["payload"]
    assert after["lease"] == before["lease"]


@pytest.mark.parametrize("secret_field", ("worker_id", "source_refs"))
def test_authenticated_outbox_recovery_rejects_durable_secret_fields(
    control_plane_store, tmp_path, secret_field: str
) -> None:
    ledger, client, _outbox = _authenticated_api_ledger(
        control_plane_store, tmp_path
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    assert claimed.lease_id is not None
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.comment",
        payload={
            "repository": REPO.lower(),
            "pr_number": 3603,
            "head_sha": "a" * 40,
        },
        holder="executor:demerzel-verifier",
        lease_id=claimed.lease_id,
        idempotency_key=f"secret-safe-recovery-{secret_field}",
    )
    _expire_outbox_claim(control_plane_store, REPO, operation_key)
    envelope = dict(ledger.envelope)
    worker_id = "demerzel-recovery"
    if secret_field == "worker_id":
        worker_id = "verification-executor-token"
    else:
        envelope["source_refs"] = ["verification-executor-token"]

    with pytest.raises(ControlPlaneProtocolError):
        client.recover_outbox(
            envelope=envelope,
            operation_key=operation_key,
            worker_id=worker_id,
        )

    with control_plane_store._connect() as conn:
        row = conn.execute(
            "SELECT worker_id, authority_envelope::text AS envelope "
            "FROM builderops_outbox WHERE repository = %s "
            "AND operation_key = %s",
            (REPO.lower(), operation_key),
        ).fetchone()
    assert row is not None
    assert "verification-executor-token" not in str(row)


def test_row_derived_post_effect_api_rejects_caller_attested_claim_evidence(
    control_plane_store, tmp_path
) -> None:
    ledger, client, _outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.comment",
        payload={"repository": REPO.lower(), "pr_number": 3603, "head_sha": "a" * 40},
        holder="executor:demerzel-verifier",
        lease_id=claimed.lease_id,
        idempotency_key="row-derived-api",
    )
    response = client._http.post(  # type: ignore[attr-defined]
        "/v1/executor/outbox/post-effect/pending",
        headers=client._headers(pin_epoch=True),  # type: ignore[attr-defined]
        json={
            "envelope": {**ledger.envelope, "claim_lsn": "0/0", "credential": "forbidden"},
            "operation_key": operation_key,
            "minimum_fencing_token": 1,
        },
    )
    assert response.status_code == 422
    response = client._http.post(  # type: ignore[attr-defined]
        "/v1/executor/outbox/post-effect/reconcile",
        headers=client._headers(pin_epoch=True),  # type: ignore[attr-defined]
        json={
            "envelope": ledger.envelope,
            "operation_key": operation_key,
            "minimum_fencing_token": 1,
            "observed_applied": False,
            "evidence": {"readback": "claim_lsn=0/DEADBEEF"},
        },
    )
    assert response.status_code == 422
    response = client._http.post(  # type: ignore[attr-defined]
        "/v1/executor/outbox/post-effect/reconcile",
        headers=client._headers(pin_epoch=True),  # type: ignore[attr-defined]
        json={
            "envelope": ledger.envelope,
            "operation_key": operation_key,
            "minimum_fencing_token": 1,
            "observed_applied": False,
            "evidence": {
                "nested": {
                    "claim": {
                        "lsn": "0/0",
                        "worker": {"id": "forged"},
                        "receipt": {"sequence": 99},
                        "fence": 7,
                    }
                }
            },
        },
    )
    assert response.status_code == 422
    assert control_plane_store.outbox_intent(REPO, operation_key).get("post_effect_phase") is None


def test_authenticated_api_rejects_github_terminal_unknown(
    control_plane_store, tmp_path
) -> None:
    ledger, client, outbox = _authenticated_api_ledger(
        control_plane_store, tmp_path
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    assert claimed.lease_id is not None
    rejected_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.comment",
        payload={
            "repository": REPO.lower(),
            "pr_number": 3603,
            "head_sha": "a" * 40,
        },
        holder="executor:demerzel-verifier",
        lease_id=claimed.lease_id,
        idempotency_key="api-roundtrip-rejected-github-dead-letter",
    )
    restarted = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
    )
    _expire_outbox_claim(control_plane_store, REPO, rejected_key)
    restarted.recover_effect(
        rejected_key,
        run_id=run.run_id,
        effect_type="github.comment",
    )
    with pytest.raises(ControlPlaneConflictError, match="StateConflict"):
        restarted.finish_effect(
            rejected_key,
            observed_applied=False,
            terminal_unknown=True,
            evidence={
                "head_sha": "a" * 40,
                "outcome": "indeterminate_pre_session_model_effect",
                "provider_session_id": None,
                "relaunch_performed": False,
            },
        )
    assert control_plane_store.outbox_status(REPO, rejected_key) == "unknown"


def test_authenticated_api_rejects_sessionful_model_terminal_unknown(
    control_plane_store, tmp_path
) -> None:
    ledger, client, outbox = _authenticated_api_ledger(
        control_plane_store, tmp_path
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    assert claimed.claimed_by is not None
    assert claimed.lease_id is not None
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="model.verification_coordinator",
        payload={
            "repository": REPO.lower(),
            "pr_number": 3603,
            "head_sha": "a" * 40,
        },
        holder=claimed.claimed_by,
        lease_id=claimed.lease_id,
        idempotency_key="api-roundtrip-sessionful-model-effect",
    )
    ledger.start(
        run.run_id,
        claimed.claimed_by,
        claimed.lease_id,
        "01900000-0000-7000-8000-000000000099",
        {"head_sha": "a" * 40},
    )
    restarted = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
    )
    _expire_outbox_claim(control_plane_store, REPO, operation_key)
    restarted.recover_effect(
        operation_key,
        run_id=run.run_id,
        effect_type="model.verification_coordinator",
    )

    with pytest.raises(ControlPlaneConflictError, match="StateConflict"):
        restarted.finish_effect(
            operation_key,
            observed_applied=False,
            terminal_unknown=True,
            evidence={
                "head_sha": "a" * 40,
                "outcome": "indeterminate_pre_session_model_effect",
                "provider_session_id": None,
                "relaunch_performed": False,
            },
        )

    assert control_plane_store.outbox_status(REPO, operation_key) == "unknown"
    with control_plane_store._connect() as conn:
        dead_letters = conn.execute(
            "SELECT count(*) AS count FROM builderops_dead_letters "
            "WHERE repository = %s AND operation_key = %s",
            (REPO.lower(), operation_key),
        ).fetchone()
        reconciliations = conn.execute(
            "SELECT count(*) AS count FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s",
            (REPO.lower(), operation_key),
        ).fetchone()
    assert dead_letters is not None and dead_letters["count"] == 0
    assert reconciliations is not None and reconciliations["count"] == 0


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
            worker_id="executor:b",
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
