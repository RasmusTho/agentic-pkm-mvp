from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
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
from app.dispatcher.verification_merge import (
    BuilderOpsOutboxExecutor,
    MergeIdentityConflict,
    ProtectedDeliveryManifest,
    VerificationMergeExecutor,
)
from tests.dispatcher.verification_helpers import (
    HEAD,
    REPO,
    admitted_verified_attempt_receipt,
    request,
)

pytestmark = pytest.mark.pg


def _expire_outbox_claim(store, repository: str, operation_key: str) -> None:
    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_outbox SET claim_expires_at = "
            "clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND operation_key = %s",
            (repository.lower(), operation_key),
        )


def test_concurrent_attempts_share_one_task_version_cas(control_plane_store, envelope) -> None:
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
    expected_version = int(control_plane_store.get_task(envelope.repository, task_id)["version"])
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
    attempts = control_plane_store.list_attempts(envelope.repository, task_id)
    assert len(attempts) == 1
    assert (
        int(control_plane_store.get_task(envelope.repository, task_id)["version"])
        == expected_version + 1
    )


def test_active_merge_intent_atomically_seals_attempt_writes(control_plane_store, envelope) -> None:
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
    stale_version = int(control_plane_store.get_task(envelope.repository, task_id)["version"])
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
    assert [
        row["task_id"] for row in store.list_tasks(envelope.repository, task_prefix="vrun-")
    ] == [task_id]

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

    assert [row["attempt_id"] for row in store.list_attempts(envelope.repository, task_id)] == [
        "vattempt-1"
    ]
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
    ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)

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
    _expire_outbox_claim(control_plane_store, REPO, indeterminate_key)
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

    assert control_plane_store.outbox_status(REPO, indeterminate_key) == "dead_letter"

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


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("worker_id", "stale-worker"),
        ("fencing_token", 999),
        ("intent_lsn", "0/BEEF"),
        ("claim_lsn", "0/DEAD"),
        ("receipt_sequence", 999),
        ("expires_at", "2000-01-01T00:00:00+00:00"),
    ),
)
def test_authenticated_effect_revalidation_denies_stale_fence_identity(
    control_plane_store,
    tmp_path,
    field: str,
    replacement: object,
) -> None:
    ledger, client, _outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
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
        idempotency_key=f"effect-revalidation-{field}",
    )
    exact_claim = ledger.effect_claim(operation_key)
    current = client.revalidate_outbox_effect(
        envelope=ledger.envelope,
        claim=exact_claim,
    )
    assert current["effect_eligible"] is True
    assert current["task_id"] == run.run_id
    assert current["effect_type"] == "github.comment"

    stale_claim = {**exact_claim, field: replacement}
    stale = client.revalidate_outbox_effect(
        envelope=ledger.envelope,
        claim=stale_claim,
    )
    assert stale["effect_eligible"] is False


def test_authenticated_recovery_claim_rejects_live_same_principal_task(
    control_plane_store, tmp_path
) -> None:
    ledger, client, _outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
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
    ledger, client, _outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
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
            "evidence": {"readback": "not-found", "provider_session_id": "claim_lsn"},
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


def test_authenticated_api_rejects_github_terminal_unknown(control_plane_store, tmp_path) -> None:
    ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
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
    ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
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
    manifest.write_text(json.dumps({"credentials": credentials}), encoding="utf-8")
    transport = TestClient(
        create_app(
            store=control_plane_store,
            credentials=CredentialRegistry(manifest),
        )
    )
    client_a = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="https://testserver", token="executor-a-token"),
        http_client=transport,  # type: ignore[arg-type]
    )
    client_b = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="https://testserver", token="executor-b-token"),
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
    version = int(client_a.get_task(repository=REPO, task_id="vrun-principal-binding")["version"])

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
            "X-BuilderOps-Authority-Epoch": str(control_plane_store.readiness()["authority_epoch"]),
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


def test_post_effect_api_readback_preserves_exact_merge_identity(
    control_plane_store, tmp_path, monkeypatch
):
    from tests.builderops.control_plane.test_outbox_recovery import _commit_outbox_task
    from app.builderops.control_plane import AuthorityEnvelope

    ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
    envelope = AuthorityEnvelope(
        repository=REPO,
        scope="verification-executor",
        stack="builderops-control-plane",
        actor="executor:demerzel-verifier",
        source_refs=("github-issue:4897",),
        schema_version=1,
    )
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id="post-effect-api",
        key="post-effect-api",
        effect_type="github.merge",
        payload={"repository": REPO.lower(), "pr_number": 4897, "head_sha": HEAD},
    )
    claim = outbox.claim(result.operation_key)
    ledger.begin_post_effect_pending(
        result.operation_key, minimum_fencing_token=claim["fencing_token"]
    )
    pending = client.get_outbox_status(repository=REPO, operation_key=result.operation_key)
    assert pending["post_effect_phase"] == "pending"
    assert pending["post_effect_claim_receipt_sequence"] == claim["receipt_sequence"]
    outbox.mark_unknown(claim, detail="exact merge readback")
    from app.dispatcher.verified_merge import (
        FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
        fixed_verified_merge_commit_title,
    )

    evidence = {
        "readback": "found",
        "merged": True,
        "head_sha": HEAD,
        "merge_commit_sha": "c" * 40,
        "merge_commit_title": fixed_verified_merge_commit_title(4897),
        "merge_commit_message": FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
    }
    # Simulate the process dying after the ordinary reconciliation commit but before its phase marker.
    outbox.reconcile(claim, observed_applied=True, evidence=evidence)
    interrupted = client.get_outbox_status(repository=REPO, operation_key=result.operation_key)
    assert interrupted["status"] == "succeeded"
    assert interrupted["post_effect_phase"] == "pending"
    ledger.post_effect_deployment = None
    # The API substrate repair is callable independently of consumer activation.
    ledger.reconcile_post_effect(
        result.operation_key,
        minimum_fencing_token=interrupted["readback_fencing_token"],
        observed_applied=True,
        evidence=evidence,
    )
    first = client.get_outbox_status(repository=REPO, operation_key=result.operation_key)
    restarted = BuilderOpsVerificationLedger(client, repository=REPO, effect_outbox=outbox)
    restarted.reconcile_post_effect(
        result.operation_key,
        minimum_fencing_token=claim["fencing_token"],
        observed_applied=True,
        evidence=evidence,
    )
    assert first == client.get_outbox_status(repository=REPO, operation_key=result.operation_key)
    assert first["post_effect_evidence"] == evidence
    assert first["post_effect_receipt_sequence"] > first["post_effect_claim_receipt_sequence"]

    from tests.dispatcher.test_verification_merge import deployed_post_effect

    deployment = deployed_post_effect()
    deployment["deployment_receipt"].update(control_plane_store.readiness())
    monkeypatch.setenv("BUILDEROPS_SOURCE_SHA", deployment["deployment_receipt"]["source_sha"])
    monkeypatch.setenv("BUILDEROPS_IMAGE_DIGEST", deployment["deployment_receipt"]["image_digest"])
    restarted = BuilderOpsVerificationLedger(
        client, repository=REPO, post_effect_deployment=deployment
    )
    projection = restarted.post_effect_authority(result.operation_key, run_id="post-effect-api")
    assert projection["operation_key"] == result.operation_key
    assert projection["merge_commit_sha"] == evidence["merge_commit_sha"]
    assert projection["pending_receipt_sequence"] == claim["receipt_sequence"]
    assert projection["reconciled_receipt_sequence"] == first["post_effect_receipt_sequence"]
    # Drive the real CLI producer through the authenticated production client/API seam.
    from app.builderops.control_plane import client as client_module
    from app.dispatcher.verified_merge import prepare_verified_merge
    from scripts import build_verified_issue_set_merge_phase as phase_cli
    from tests.dispatcher.verified_merge_projection_helpers import (
        projection_phase_kwargs,
        projection_convergence_comment,
    )

    body = "Governing-Issue: #4897\n\nFixes #4897\n"
    pr = {
        "number": 4897,
        "body": body,
        "head": {"sha": HEAD},
        "state": "open",
        "merged_at": None,
        "draft": False,
        "title": "Exact post-effect phase projection",
    }
    context = {
        "contract": "verification_closer_dispatch_context.v2",
        "repository": REPO,
        "run_id": "post-effect-api",
        "pr_number": 4897,
        "governing_issue": 4897,
        "closing_issues": [4897],
        "supporting_issues": [],
        "head_sha": HEAD,
        "repair_budget": {"policy_version": "v2", "mechanisms": []},
    }
    plan = prepare_verified_merge(
        context=context,
        pr=pr,
        live_closing_issues=[4897],
        merge_readiness={
            "contract": "verified_issue_set_merge_readiness.v1",
            "head_sha": HEAD,
            "further_commits_anticipated": False,
            "required_checks_green": True,
            "review_gate_resolved": True,
        },
    )
    authority = plan["authority_receipt"]
    neutral = {**pr, "body": plan["neutralized_body"]}
    convergence = projection_phase_kwargs(authority, neutral)
    merged_pr = {
        **neutral,
        "state": "closed",
        "merged": True,
        "merged_at": "2026-10-09T10:00:00Z",
        "merge_commit_sha": "c" * 40,
    }
    restored_pr = {**merged_pr, "body": plan["original_body"]}
    comments = [
        {"author_association": "OWNER", "body": plan["authority_receipt_comment"]},
        projection_convergence_comment(convergence),
    ]
    paths = {}
    for name, payload in {
        "authority": authority,
        "comments": comments,
        "convergence": convergence["projection_convergence_receipt"],
        "final": convergence["final_projection_observation"],
        "deployment": deployment,
        "pr": restored_pr,
        "closed": [4897],
    }.items():
        paths[name] = tmp_path / (name + ".json")
        paths[name].write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(client_module.ClientConfig, "from_env", lambda: None)
    monkeypatch.setattr(client_module, "BuilderOpsControlPlaneClient", lambda _config: client)
    output = tmp_path / "phase.json"
    phase_inputs = {
        "prepared": neutral,
        "merged": merged_pr,
        "reconciled": merged_pr,
        "restored": restored_pr,
    }
    projected_phase = None
    for phase, phase_pr in phase_inputs.items():
        paths["comments"].write_text(json.dumps(comments), encoding="utf-8")
        paths["pr"].write_text(json.dumps(phase_pr), encoding="utf-8")
        argv = [
            "--phase",
            phase,
            "--authority-json",
            str(paths["authority"]),
            "--comments-json",
            str(paths["comments"]),
            "--projection-convergence-json",
            str(paths["convergence"]),
            "--post-effect-deployment-json",
            str(paths["deployment"]),
            "--pr-json",
            str(paths["pr"]),
            "--output-json",
            str(output),
        ]
        if phase == "prepared":
            argv.extend(("--final-projection-observation-json", str(paths["final"])))
        if phase in {"reconciled", "restored"}:
            argv.extend(("--post-effect-operation-key", result.operation_key))
            argv.extend(("--closed-issues-json", str(paths["closed"])))
        assert phase_cli.main(argv) == 0
        phase_output = json.loads(output.read_text())
        projected_phase = phase_output["phase_receipt"]
        assert projected_phase["contract"] == "verified_issue_set_merge_phase.v2"
        comments.append(
            {
                "author_association": "OWNER",
                "body": phase_output["phase_receipt_comment"],
            }
        )
    assert projected_phase is not None
    assert projected_phase["contract"] == "verified_issue_set_merge_phase.v2"
    assert projected_phase["post_effect_authority"] == projection


@pytest.mark.parametrize("takeover", [False, True], ids=["expired", "takeover"])
def test_native_effect_refusal_reacquires_current_fence_before_terminalizing(
    control_plane_store, tmp_path, takeover
) -> None:
    from app.builderops.control_plane import AuthorityEnvelope
    from tests.builderops.control_plane.test_outbox_recovery import (
        _commit_outbox_task,
    )

    ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
    envelope = AuthorityEnvelope(
        repository=REPO,
        scope="verification-executor",
        stack="builderops-control-plane",
        actor="executor:demerzel-verifier",
        source_refs=("github-issue:4893",),
        schema_version=1,
    )
    task_id = f"native-effect-refusal-{'takeover' if takeover else 'expired'}"
    payload = {
        "repository": REPO.lower(),
        "pr_number": 4893,
        "head_sha": HEAD,
    }
    result = _commit_outbox_task(
        control_plane_store,
        envelope,
        task_id=task_id,
        key=task_id,
        effect_type="github.merge",
        payload=payload,
    )
    original = outbox.claim(result.operation_key)
    refreshed = outbox.revalidate_effect(original)
    assert refreshed["effect_eligible"] is True
    assert "payload" not in refreshed

    _expire_outbox_claim(control_plane_store, REPO, result.operation_key)
    assert outbox.revalidate_effect(original)["effect_eligible"] is False
    latest_token = original["fencing_token"]
    if takeover:
        contender = BuilderOpsOutboxExecutor(
            client,
            repository=REPO,
            worker_id="native-refusal-takeover",
        )
        replacement = contender.recover(result.operation_key)
        latest_token = replacement["fencing_token"]
        with pytest.raises(StaleLeaseError, match="LeaseUnavailable"):
            ledger.recover_effect(
                result.operation_key,
                run_id=task_id,
                effect_type="github.merge",
                expected_payload=payload,
                force_current_fence=True,
            )
        _expire_outbox_claim(
            control_plane_store,
            REPO,
            result.operation_key,
        )

    recovered = ledger.recover_effect(
        result.operation_key,
        run_id=task_id,
        effect_type="github.merge",
        expected_payload=payload,
        force_current_fence=True,
    )
    assert recovered["fencing_token"] > latest_token
    evidence = {
        "outcome": "terminal_no_effect",
        "reason": "native_effect_fence_refused",
    }
    ledger.finish_effect(
        result.operation_key,
        observed_applied=True,
        evidence=evidence,
    )
    persisted = client.get_outbox_status(
        repository=REPO,
        operation_key=result.operation_key,
    )
    assert persisted["status"] == "succeeded"
    assert persisted["reconciliation_evidence"] == evidence


@pytest.mark.parametrize(
    "ordering",
    ["concurrent", "response-first", "conflict-first"],
)
def test_native_merge_observation_conflict_converges_and_blocks_terminal_cas(
    control_plane_store, tmp_path, ordering
) -> None:
    ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    holder = claimed.claimed_by or ""
    assert claimed.lease_id is not None
    ledger.record_attempt(
        run.run_id,
        "verification",
        "native-pg-verification",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "launched",
        admitted_verified_attempt_receipt(
            ledger,
            run.run_id,
            "native-pg-verification",
            holder=holder,
            lease_id=claimed.lease_id,
        ),
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-pg-verification",
    )
    anchor = ledger.attempts(run.run_id)[-1]["attempt_id"]
    ledger.record_attempt(
        run.run_id,
        "review",
        "native-pg-review",
        "gpt-5.6-sol",
        "xhigh",
        {"head_sha": HEAD},
        "clean",
        {"head_sha": HEAD, "reviewed_attempt_id": anchor},
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-pg-review",
    )
    ready = ledger.mark_merge_ready(
        run.run_id,
        {
            "verdict": "verified",
            "head_sha": HEAD,
            "summary": "native PostgreSQL CAS proof",
            "receipt_ids": ["native-pg-review"],
            "retry_after": None,
            "review_events": [],
            "human_exception": None,
        },
        holder=holder,
        lease_id=claimed.lease_id,
    )
    marker = ledger.merge_ready_receipt(run.run_id)
    assert marker is not None
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.merge",
        payload={
            "repository": REPO.lower(),
            "pr_number": run.pr_number,
            "head_sha": HEAD,
            "verified_merge_prepared": {
                "contract": "native_single_closer_gate.v1",
                "run_id": run.run_id,
                "head_sha": HEAD,
                "closing_issues": list(run.closing_authority),
            },
        },
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-pg-effect",
        merge_ready_receipt=marker,
    )
    prearmed = ledger.pending_effect_binding(run.run_id)
    assert prearmed is not None
    assert prearmed["native_merge_response_sha"] is None
    assert prearmed["native_merge_identity_conflict"] is False
    assert prearmed["native_merge_effect_refusal"] is None

    response_writer = BuilderOpsVerificationLedger(client, repository=REPO, effect_outbox=outbox)
    conflict_writer = BuilderOpsVerificationLedger(client, repository=REPO, effect_outbox=outbox)
    barrier = Barrier(2)

    def record_response() -> None:
        response_writer.record_native_merge_response(
            run.run_id,
            operation_key,
            response_sha="c" * 40,
            holder=holder,
            lease_id=claimed.lease_id or "",
        )

    def write_response() -> str:
        barrier.wait()
        try:
            record_response()
        except ValueError:
            return "response-refused"
        return "response-recorded"

    def record_conflict() -> None:
        conflict_writer.record_native_merge_conflict(
            run.run_id,
            operation_key,
            holder=holder,
            lease_id=claimed.lease_id or "",
        )

    def write_conflict() -> str:
        barrier.wait()
        record_conflict()
        return "conflict-recorded"

    if ordering == "concurrent":
        with ThreadPoolExecutor(max_workers=2) as executor:
            response_future = executor.submit(write_response)
            conflict_future = executor.submit(write_conflict)
            outcomes = {response_future.result(), conflict_future.result()}
    elif ordering == "response-first":
        record_response()
        record_conflict()
        outcomes = {"response-recorded", "conflict-recorded"}
    else:
        record_conflict()
        outcomes = {"conflict-recorded"}
        with pytest.raises(
            ValueError,
            match="native response cannot replace captured identity or refusal",
        ):
            record_response()
        outcomes.add("response-refused")
    assert "conflict-recorded" in outcomes
    restarted = BuilderOpsVerificationLedger(client, repository=REPO, effect_outbox=outbox)
    persisted = restarted.pending_effect_binding(run.run_id)
    assert persisted is not None
    assert persisted["native_merge_identity_conflict"] is True
    assert persisted["native_merge_response_sha"] in {None, "c" * 40}
    assert persisted["native_merge_effect_refusal"] is None
    with pytest.raises(ValueError, match="exact captured merge authority"):
        restarted.terminal(
            ready.run_id,
            "completed",
            {"operation_key": operation_key, "merge_commit_sha": "c" * 40},
            holder=holder,
            lease_id=claimed.lease_id,
        )


def test_native_compensation_authority_uses_database_clock_and_current_task_fence(
    control_plane_store,
    tmp_path,
    monkeypatch,
) -> None:
    ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    holder = claimed.claimed_by or ""
    assert claimed.lease_id is not None
    ledger.record_attempt(
        run.run_id,
        "verification",
        "native-compensation-verification",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "launched",
        admitted_verified_attempt_receipt(
            ledger,
            run.run_id,
            "native-compensation-verification",
            holder=holder,
            lease_id=claimed.lease_id,
        ),
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-compensation-verification",
    )
    anchor = ledger.attempts(run.run_id)[-1]["attempt_id"]
    ledger.record_attempt(
        run.run_id,
        "review",
        "native-compensation-review",
        "gpt-5.6-sol",
        "xhigh",
        {"head_sha": HEAD},
        "clean",
        {"head_sha": HEAD, "reviewed_attempt_id": anchor},
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-compensation-review",
    )
    ledger.mark_merge_ready(
        run.run_id,
        {
            "verdict": "verified",
            "head_sha": HEAD,
            "summary": "native compensation database-clock proof",
            "receipt_ids": ["native-compensation-review"],
            "retry_after": None,
            "review_events": [],
            "human_exception": None,
        },
        holder=holder,
        lease_id=claimed.lease_id,
    )
    marker = ledger.merge_ready_receipt(run.run_id)
    assert marker is not None
    operation_key = ledger.begin_effect(
        run.run_id,
        effect_type="github.merge",
        payload={
            "repository": REPO.lower(),
            "pr_number": run.pr_number,
            "head_sha": HEAD,
            "verified_merge_prepared": {
                "contract": "native_single_closer_gate.v1",
                "run_id": run.run_id,
                "head_sha": HEAD,
                "closing_issues": list(run.closing_authority),
            },
        },
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-compensation-effect",
        merge_ready_receipt=marker,
    )
    ledger.record_native_merge_conflict(
        run.run_id,
        operation_key,
        holder=holder,
        lease_id=claimed.lease_id,
    )
    conflict = ledger.pending_effect_binding(run.run_id)
    assert conflict is not None
    assert conflict["native_merge_identity_conflict"] is True

    live_snapshot = deepcopy(client.get_task(repository=REPO, task_id=run.run_id))
    assert live_snapshot["lease"] is not None
    live_snapshot["lease"]["expires_at"] = "2099-01-01T00:00:00+00:00"
    with control_plane_store._connect() as conn:
        conn.execute(
            "UPDATE builderops_leases SET expires_at = "
            "clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND lease_kind = 'task' "
            "AND resource_id = %s",
            (REPO.lower(), run.run_id),
        )

    actual_get_task = client.get_task

    def apparently_live_task(*, repository, task_id):
        assert repository == REPO.lower()
        assert task_id == run.run_id
        return deepcopy(live_snapshot)

    monkeypatch.setattr(client, "get_task", apparently_live_task)
    patches: list[int] = []

    def compensate(actor) -> None:
        ledger.authorize_native_merge_compensation(
            actor.run_id,
            operation_key,
            holder=actor.claimed_by or "",
            lease_id=actor.lease_id or "",
        )
        patches.append(3604)

    with pytest.raises(StaleLeaseError, match="StaleFencingToken"):
        compensate(claimed)
    assert patches == []

    monkeypatch.setattr(client, "get_task", actual_get_task)
    current = ledger.claim(run.run_id, "ignored-current-holder")
    assert current.lease_id is not None
    assert current.lease_id != claimed.lease_id
    compensate(current)
    assert patches == [3604]
    persisted = ledger.pending_effect_binding(run.run_id)
    assert persisted is not None
    assert persisted["operation_key"] == operation_key
    assert persisted["native_merge_identity_conflict"] is True


def test_native_compensation_recovery_uses_database_clock_before_github_effects(
    control_plane_store,
    tmp_path,
    monkeypatch,
) -> None:
    from tests.dispatcher.test_verification_merge import (
        BASE,
        deployed_post_effect,
        native_authority,
    )

    _ledger, client, outbox = _authenticated_api_ledger(control_plane_store, tmp_path)
    deployment = deployed_post_effect()
    deployment["deployment_receipt"].update(control_plane_store.readiness())
    monkeypatch.setenv(
        "BUILDEROPS_SOURCE_SHA",
        str(deployment["deployment_receipt"]["source_sha"]),
    )
    monkeypatch.setenv(
        "BUILDEROPS_IMAGE_DIGEST",
        str(deployment["deployment_receipt"]["image_digest"]),
    )
    ledger = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
        post_effect_deployment=deployment,
    )
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "ignored-client-holder")
    holder = claimed.claimed_by or ""
    assert claimed.lease_id is not None
    ledger.record_attempt(
        run.run_id,
        "verification",
        "native-compensation-executor-verification",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "launched",
        admitted_verified_attempt_receipt(
            ledger,
            run.run_id,
            "native-compensation-executor-verification",
            holder=holder,
            lease_id=claimed.lease_id,
        ),
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-compensation-executor-verification",
    )
    anchor = ledger.attempts(run.run_id)[-1]["attempt_id"]
    ledger.record_attempt(
        run.run_id,
        "review",
        "native-compensation-executor-review",
        "gpt-5.6-sol",
        "xhigh",
        {"head_sha": HEAD},
        "clean",
        {"head_sha": HEAD, "reviewed_attempt_id": anchor},
        holder=holder,
        lease_id=claimed.lease_id,
        idempotency_key="native-compensation-executor-review",
    )
    ledger.mark_merge_ready(
        run.run_id,
        {
            "verdict": "verified",
            "head_sha": HEAD,
            "summary": "native compensation executor database-clock proof",
            "receipt_ids": ["native-compensation-executor-review"],
            "retry_after": None,
            "review_events": [],
            "human_exception": None,
        },
        holder=holder,
        lease_id=claimed.lease_id,
    )

    authority, github_calls = native_authority()
    manifest = ProtectedDeliveryManifest.from_document(
        {
            "repository": REPO,
            "allowed_effects": ["github.merge"],
            "github_credential": {
                "credential_id": "github-repo-merge",
                "rotation_generation": 7,
            },
        },
        repository=REPO.lower(),
        base_sha=BASE,
        blob_sha="native-compensation-manifest",
    )
    authority.protected_base_sha = lambda repository: BASE
    authority.delivery_manifest = lambda repository, base_sha: manifest
    authority.required_gates = lambda *args: {
        key: True
        for key in (
            "ci",
            "review",
            "protection",
            "scope",
            "current_head",
            "threads",
        )
    }

    class ClosureSource:
        def issue_set_closure_evidence(self, *args, **kwargs):
            return {
                "closure_scan_complete": True,
                "observed_closing_issues": [3603, 3604],
                "issue_evidence": [
                    {
                        "number": number,
                        "state": "closed",
                        "closed_by_delivery": True,
                        "closed_by_pull_requests": [3603],
                    }
                    for number in (3603, 3604)
                ],
            }

    authority.closure_source = ClosureSource()

    class CountingCredentials:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def resolve(self, **values):
            self.calls.append(dict(values))
            return "test-host-token"

    credentials = CountingCredentials()
    executor = VerificationMergeExecutor(ledger, outbox, authority, credentials)
    record_conflict = ledger.record_native_merge_conflict

    def crash_after_conflict(*args, **kwargs):
        record_conflict(*args, **kwargs)
        raise SystemExit("crash after durable native closure conflict")

    monkeypatch.setattr(ledger, "record_native_merge_conflict", crash_after_conflict)
    with pytest.raises(SystemExit, match="durable native closure conflict"):
        executor.execute(
            claimed,
            holder=holder,
            lease_id=claimed.lease_id,
        )
    monkeypatch.setattr(ledger, "record_native_merge_conflict", record_conflict)

    puts = [call for call in github_calls if call.method == "PUT"]
    assert len(puts) == 1
    assert not any(call.method == "PATCH" for call in github_calls)
    conflict = ledger.pending_effect_binding(run.run_id)
    assert conflict is not None
    assert conflict["outbox_status"] == "succeeded"
    assert conflict["native_merge_identity_conflict"] is True

    actual_get_task = client.get_task
    apparently_live = deepcopy(actual_get_task(repository=REPO, task_id=run.run_id))
    assert apparently_live["lease"] is not None
    old_version = int(apparently_live["version"])
    old_fencing_token = int(apparently_live["lease"]["fencing_token"])
    apparently_live["lease"]["expires_at"] = "2099-01-01T00:00:00+00:00"
    with control_plane_store._connect() as conn:
        conn.execute(
            "UPDATE builderops_leases SET expires_at = "
            "clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND lease_kind = 'task' "
            "AND resource_id = %s",
            (REPO.lower(), run.run_id),
        )

    def apparently_live_task(*, repository, task_id):
        assert repository == REPO.lower()
        assert task_id == run.run_id
        return deepcopy(apparently_live)

    monkeypatch.setattr(client, "get_task", apparently_live_task)
    credentials.calls.clear()
    restarted_ledger = BuilderOpsVerificationLedger(
        client,
        repository=REPO,
        effect_outbox=outbox,
        post_effect_deployment=deployment,
    )
    restarted = VerificationMergeExecutor(restarted_ledger, outbox, authority, credentials)
    with pytest.raises(
        MergeIdentityConflict,
        match="conflict compensation remains incomplete",
    ) as stale:
        restarted.recover(claimed)
    assert isinstance(stale.value.__cause__, StaleLeaseError)
    assert credentials.calls == []
    assert len([call for call in github_calls if call.method == "PUT"]) == 1
    assert not any(call.method == "PATCH" for call in github_calls)
    expired = control_plane_store.get_task(REPO, run.run_id)
    assert int(expired["version"]) == old_version
    assert expired["payload"]["run"]["terminal_receipt"] is None

    monkeypatch.setattr(client, "get_task", actual_get_task)
    current = restarted_ledger.claim(run.run_id, "ignored-current-holder")
    assert current.lease_id is not None
    assert current.lease_id != claimed.lease_id
    current_snapshot = actual_get_task(repository=REPO, task_id=run.run_id)
    assert current_snapshot["lease"] is not None
    assert int(current_snapshot["lease"]["fencing_token"]) > old_fencing_token
    restarted = VerificationMergeExecutor(restarted_ledger, outbox, authority, credentials)
    with pytest.raises(
        MergeIdentityConflict,
        match="merge or closure identity conflict requires governed repair",
    ):
        restarted.recover(current)

    assert len(credentials.calls) == 1
    assert len([call for call in github_calls if call.method == "PUT"]) == 1
    patched = [
        int(call.url.path.rsplit("/", 1)[1]) for call in github_calls if call.method == "PATCH"
    ]
    assert patched == [3604]
    persisted = restarted_ledger.pending_effect_binding(run.run_id)
    assert persisted is not None
    assert persisted["native_merge_identity_conflict"] is True
    latest = actual_get_task(repository=REPO, task_id=run.run_id)
    assert latest["payload"]["run"]["terminal_receipt"] is None


def test_authenticated_status_supplies_launcher_deployment_readback(
    control_plane_store, tmp_path, monkeypatch
):
    from tests.builderops.control_plane.test_deployment_readback import _files

    receipt, _, pin = _files(tmp_path, monkeypatch)
    ready = control_plane_store.readiness()
    receipt.update(schema_version=ready["schema_version"], authority_epoch=ready["authority_epoch"])
    (tmp_path / "latest.json").write_text(json.dumps(receipt))
    monkeypatch.setenv("BUILDEROPS_SOURCE_SHA", receipt["source_sha"])
    monkeypatch.setenv("BUILDEROPS_IMAGE_DIGEST", receipt["image_digest"])
    secret = tmp_path / "status-token"
    secret.write_text("status-read-token")
    manifest = tmp_path / "credentials.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "status-reader",
                        "principal": "test-status-reader",
                        "secret_file": str(secret),
                        "secret_ref": "host-secret:status-reader",
                        "rotation_generation": 1,
                        "scopes": ["status:read"],
                        "repositories": [REPO.lower()],
                    }
                ]
            }
        )
    )
    credentials = CredentialRegistry(manifest)
    app = create_app(store=control_plane_store, credentials=credentials)
    with TestClient(app) as http:
        assert http.get("/v1/status").status_code == 401
        client = BuilderOpsControlPlaneClient(
            ClientConfig(base_url="https://testserver", token="status-read-token"), http_client=http
        )
        ledger = BuilderOpsVerificationLedger(client, repository=REPO)
        ledger.require_post_effect_capability()
        assert ledger.post_effect_deployment["deployment_receipt"] == receipt
        pin.unlink()
        from app.dispatcher.verification_merge import MergeAuthorityError

        with pytest.raises(MergeAuthorityError, match="exact deployed substrate"):
            ledger.require_post_effect_capability()


def test_terminal_payload_status_correction_enforces_existing_admission(
    control_plane_store, envelope, tmp_path
):
    from dataclasses import asdict
    from tests.builderops.control_plane.correction_helpers import correction_setup, TASK

    args, before = correction_setup(control_plane_store, envelope)
    credentials = []
    for name, principal, scopes, repos in (
        (
            "writer",
            envelope.actor,
            ["tasks:write", "leases:write", "status:read", "receipts:read"],
            [envelope.repository],
        ),
        ("reader", "reader", ["status:read", "receipts:read"], [envelope.repository]),
        ("taskonly", envelope.actor, ["tasks:write"], [envelope.repository]),
        ("foreign", "foreign", ["tasks:write", "leases:write"], [envelope.repository]),
        ("otherrepo", envelope.actor, ["tasks:write", "leases:write"], ["foreign/repo"]),
    ):
        secret = tmp_path / f"{name}.secret"
        secret.write_text(f"{name}-value-6175")
        credentials.append(
            {
                "id": name,
                "principal": principal,
                "secret_ref": f"host-secret:{name}",
                "secret_file": str(secret),
                "scopes": scopes,
                "repositories": repos,
                "rotation_generation": 1,
            }
        )
    manifest = tmp_path / "correction-credentials.json"
    manifest.write_text(json.dumps({"credentials": credentials}))
    transport = TestClient(
        create_app(store=control_plane_store, credentials=CredentialRegistry(manifest))
    )
    body = {k: v for k, v in args.items() if k not in {"task_id", "envelope", "lease"}}
    body["expected_updated_at"] = args["expected_updated_at"].isoformat()
    body["envelope"] = envelope.as_json()
    body["envelope"].pop("actor")
    body["lease"] = asdict(args["lease"])
    body["lease"]["expires_at"] = args["lease"].expires_at.isoformat()
    epoch = control_plane_store.readiness()["authority_epoch"]
    url = f"/v1/tasks/{TASK}/correct-payload-status"

    def post(name="writer", document=None, pinned=epoch):
        return transport.post(
            url,
            json=body if document is None else document,
            headers={
                "Authorization": f"Bearer {name}-value-6175",
                "X-BuilderOps-Authority-Epoch": str(pinned),
            },
        )

    sdk = BuilderOpsControlPlaneClient(
        ClientConfig(base_url="https://testserver", token="writer-value-6175"), http_client=transport
    )
    # Prove the real generic-lease producer admits this exact resource name.
    claimed = sdk.claim_lease(
        envelope=body["envelope"], resource_id=f"payload-status-correction:{TASK}",
        idempotency_key="maintenance-http-claim",
    )
    body["lease"] = claimed["lease"]
    assert body["lease"]["lease_kind"] == "generic"
    for name in ("reader", "taskonly", "foreign", "otherrepo"):
        assert post(name).status_code == 403
    assert post(pinned=epoch + 1).status_code == 409
    assert post(document=dict(body, lease=dict(body["lease"], repository="foreign/repo"))).status_code == 403
    assert post(document=dict(body, lease=dict(body["lease"], repository="invalid"))).status_code == 400
    assert post(document=dict(body, lease=dict(body["lease"], unknown=True))).status_code == 422
    for extra in (
        {"payload": {}},
        {"to_state": "ready"},
        {"status": "completed"},
        {"expected_version": True},
    ):
        assert post(document=dict(body, **extra)).status_code == 422
    assert control_plane_store.get_task(envelope.repository, TASK) == before
    values = {k: v for k, v in body.items() if k not in {"envelope", "lease"}}
    result = sdk.correct_task_payload_status(
        envelope=body["envelope"], lease=body["lease"], task_id=TASK, **values
    )
    assert result["correction"]["after_version"] == 4
    assert result["result"]["recovery_lsn"] != "0/0"
    assert sdk.get_task(repository=envelope.repository, task_id=TASK)["payload"] == dict(
        before["payload"], status="completed"
    )
    assert post().json()["result"]["replayed"] is True
