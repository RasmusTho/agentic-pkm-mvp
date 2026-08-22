from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_agent_loop import VerificationAgentLoop
from app.dispatcher.verification_github import (
    GitHubProtectedRepositoryAuthority,
    _latest_github_result,
    _workflow_runs_by_suite,
)
from app.dispatcher.verification_merge import (
    MergeAuthorityError,
    ProtectedDeliveryManifest,
    VerificationMergeExecutor,
)
from app.dispatcher.verified_merge import (
    FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
    VERIFIED_MERGE_READINESS_CONTRACT,
    build_verified_merge_phase,
    fixed_verified_merge_commit_title,
    prepare_verified_merge,
)
from tests.dispatcher.builderops_verification_fakes import FakeBuilderOpsClient
from tests.dispatcher.verification_helpers import HEAD, REPO, request

BASE = "b" * 40
NEXT_BASE = "c" * 40


class RepositoryAuthority:
    def __init__(
        self,
        *,
        base_reads: list[str] | None = None,
        manifest_blobs: list[str] | None = None,
        head: str = HEAD,
        gates: dict[str, bool] | None = None,
        timeout: bool = False,
        transport_error: bool = False,
        merged: bool = True,
        prepared_gates: list[dict[str, object]] | None = None,
        merge_commit_title: str | None = None,
        merge_commit_message: str | None = None,
    ) -> None:
        self.base_reads = iter(base_reads or [BASE, BASE])
        self.manifest_blobs = iter(manifest_blobs or ["blob-1", "blob-1"])
        self.head = head
        self.gates = gates or {
            "ci": True,
            "review": True,
            "protection": True,
            "scope": True,
            "current_head": True,
        }
        self.prepared_gates = iter(
            prepared_gates
            or [
                {
                    "contract": "verified_merge_prepared_gate.v1",
                    "repository": REPO.lower(),
                    "pr_number": 3603,
                    "run_id": "test-run",
                    "head_sha": HEAD,
                    "governing_issue": 3603,
                    "closing_issues": [3603],
                    "neutralized_body_sha256": "a" * 64,
                    "authority_sha256": "b" * 64,
                    "phase_sha256": "c" * 64,
                    "closing_reference_count": 0,
                    "fixed_commit_title": fixed_verified_merge_commit_title(
                        3603
                    ),
                    "fixed_commit_message": (
                        FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
                    ),
                }
            ]
            * 20
        )
        self.timeout = timeout
        self.transport_error = transport_error
        self.merged = merged
        self.merge_commit_title = (
            fixed_verified_merge_commit_title(3603)
            if merge_commit_title is None
            else merge_commit_title
        )
        self.merge_commit_message = (
            FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
            if merge_commit_message is None
            else merge_commit_message
        )
        self.calls: list[str] = []
        self.last_merge = None

    def protected_base_sha(self, repository: str) -> str:
        return next(self.base_reads)

    def delivery_manifest(
        self, repository: str, base_sha: str
    ) -> ProtectedDeliveryManifest:
        blob = next(self.manifest_blobs)
        return ProtectedDeliveryManifest.from_document(
            {
                "repository": REPO,
                "allowed_effects": [
                    "github.merge",
                    "github.merge.dry_run",
                ],
                "github_credential": {
                    "credential_id": "github-repo-merge",
                    "rotation_generation": 7,
                },
            },
            repository=repository,
            base_sha=base_sha,
            blob_sha=blob,
        )

    def current_pr_head(self, repository: str, pr_number: int) -> str:
        return self.head

    def required_gates(
        self, repository: str, pr_number: int, head_sha: str
    ) -> dict[str, bool]:
        return self.gates

    def verified_merge_prepared(
        self,
        repository: str,
        pr_number: int,
        *,
        run_id: str,
        head_sha: str,
        expected_repair_budget: Mapping[str, object],
    ) -> Mapping[str, object]:
        gate = dict(next(self.prepared_gates))
        gate.update(
            repository=repository,
            pr_number=pr_number,
            run_id=run_id,
            head_sha=head_sha,
        )
        gate.setdefault(
            "fixed_commit_title",
            fixed_verified_merge_commit_title(pr_number),
        )
        gate.setdefault(
            "fixed_commit_message",
            FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
        )
        return gate

    def conditional_merge(self, *args, **kwargs):
        self.calls.append("merge")
        self.last_merge = kwargs
        if self.timeout:
            raise TimeoutError("simulated GitHub timeout")
        if self.transport_error:
            raise httpx.ReadTimeout("simulated response loss")
        return {"accepted": True}

    def merge_readback(self, repository: str, pr_number: int):
        self.calls.append("readback")
        return {
            "merged": self.merged,
            "head_sha": HEAD,
            "merge_commit_sha": "d" * 40 if self.merged else None,
            "merge_commit_title": (
                self.merge_commit_title if self.merged else None
            ),
            "merge_commit_message": (
                self.merge_commit_message if self.merged else None
            ),
        }


class Credentials:
    def __init__(self) -> None:
        self.calls = []

    def resolve(self, **values):
        self.calls.append(values)
        return object()


class CrashCredentials(Credentials):
    def resolve(self, **values):
        super().resolve(**values)
        raise SystemExit("simulated host crash after outbox claim")


class CrashOnceReadbackRepository(RepositoryAuthority):
    def __init__(self) -> None:
        super().__init__(
            base_reads=[BASE, BASE, BASE],
            manifest_blobs=["blob-1", "blob-1", "blob-1"],
            merged=True,
        )
        self.crashed = False

    def merge_readback(self, repository: str, pr_number: int):
        if not self.crashed:
            self.crashed = True
            raise SystemExit("simulated crash before merge readback")
        return super().merge_readback(repository, pr_number)


class Outbox:
    def __init__(
        self,
        run_id: str,
        effect_type: str = "github.merge",
        payload_loader=None,
    ) -> None:
        self.run_id = run_id
        self.effect_type = effect_type
        self.calls = []
        self.state = "missing"
        self.evidence = None
        self.payload_loader = payload_loader
        self.intent_payload_override = None

    def _payload(self):
        if self.intent_payload_override is not None:
            return dict(self.intent_payload_override)
        return dict(self.payload_loader()) if self.payload_loader else {}

    def claim(self, operation_key: str):
        self.calls.append("claim")
        self.state = "claimed"
        return {
            "repository": REPO.lower(),
            "operation_key": operation_key,
            "worker_id": "demerzel-verifier",
            "fencing_token": 1,
            "intent_lsn": "0/10",
            "claim_lsn": "0/20",
            "receipt_sequence": 2,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ).isoformat(),
            "effect_eligible": True,
            "task_id": self.run_id,
            "effect_type": self.effect_type,
            "payload": self._payload(),
        }

    def recover(self, operation_key: str):
        self.calls.append("recover")
        return self.claim(operation_key)

    def status(self, operation_key: str):
        self.calls.append("status")
        return {
            "repository": REPO.lower(),
            "operation_key": operation_key,
            "task_id": self.run_id,
            "effect_type": self.effect_type,
            "payload": self._payload(),
            "status": self.state,
            "reconciliation_evidence": self.evidence,
            "reconciliation_receipt_sequence": (
                3 if self.evidence is not None else None
            ),
        }

    def mark_unknown(self, claim, *, detail: str):
        self.calls.append("unknown")
        self.state = "unknown"

    def reconcile(
        self,
        claim,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence,
    ):
        self.calls.append("reconcile")
        self.state = (
            "dead_letter"
            if terminal_unknown
            else ("succeeded" if observed_applied else "pending")
        )
        self.evidence = dict(evidence)
        return {"status": self.state}


class CrashAfterReconcileOutbox(Outbox):
    def reconcile(
        self,
        claim,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence,
    ):
        super().reconcile(
            claim,
            observed_applied=observed_applied,
            terminal_unknown=terminal_unknown,
            evidence=evidence,
        )
        raise SystemExit("simulated crash after durable reconciliation")


class BlockingReviewWinsIntentRaceClient(FakeBuilderOpsClient):
    def __init__(self) -> None:
        super().__init__()
        self.before_merge_intent = None

    def transition_task(self, **values):
        callback = self.before_merge_intent
        if (
            callback is not None
            and isinstance(values.get("outbox"), Mapping)
            and values["outbox"].get("effect_type")
            in {"github.merge", "github.merge.dry_run"}
        ):
            self.before_merge_intent = None
            callback()
            task = self.tasks[values["task_id"]]
            if int(task["version"]) != values.get("expected_version"):
                raise ValueError(
                    "simulated task-version CAS rejected stale merge intent"
                )
        return super().transition_task(**values)


def claimed_run(
    effect_type: str = "github.merge",
    *,
    api: FakeBuilderOpsClient | None = None,
):
    api = api or FakeBuilderOpsClient()
    ledger = BuilderOpsVerificationLedger(api, repository=REPO)
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    ledger.record_attempt(
        run.run_id,
        "verification",
        "verification-session",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "passed",
        {"head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="pre-merge-verification",
    )
    anchor = ledger.attempts(run.run_id)[-1]["attempt_id"]
    ledger.record_attempt(
        run.run_id,
        "review",
        "independent-review-session",
        "gpt-5.6-sol",
        "xhigh",
        {"head_sha": HEAD},
        "clean",
        {"head_sha": HEAD, "reviewed_attempt_id": anchor},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="pre-merge-review",
    )
    assert ledger.closure_ready(run.run_id)
    ready = ledger.mark_merge_ready(
        run.run_id,
        {
            "verdict": "verified",
            "head_sha": HEAD,
            "summary": "host-fenced merge ready",
            "receipt_ids": ["verified-review"],
            "retry_after": None,
            "review_events": [],
            "human_exception": None,
        },
        holder="verification-host",
        lease_id=claimed.lease_id,
    )
    def _pending_payload():
        snapshot = ledger._snapshot(ready.run_id)["payload"]
        pending = snapshot.get("pending_privileged_effect")
        return pending["payload"] if isinstance(pending, Mapping) else {}

    outbox = Outbox(
        ready.run_id,
        effect_type,
        payload_loader=_pending_payload,
    )
    ledger.effect_outbox = outbox
    return ledger, ready, outbox


def test_merge_ready_containment_matches_durable_verification_attempt() -> None:
    api = FakeBuilderOpsClient()
    ledger = BuilderOpsVerificationLedger(api, repository=REPO)
    run = ledger.ingest(request())
    claimed = ledger.claim(run.run_id, "verification-host")
    assert claimed.lease_id is not None
    containment = {
        "contract": "builderops_linux_containment.v1",
        "profile_name": "linux-systemd-cgroup-v2-scope-v1",
        "scope_identity": f"yggdrasil-verification-{'a' * 24}.scope",
        "evidence_digests": {
            "attach": "b" * 64,
            "cleanup": "c" * 64,
        },
        "outcome": "clean",
    }
    ledger.record_attempt(
        run.run_id,
        "verification",
        "verification-session",
        "gpt-5.6-sol",
        "high",
        {"head_sha": HEAD},
        "passed",
        {"head_sha": HEAD},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="contained-verification",
        containment_receipt=containment,
    )
    anchor = ledger.attempts(run.run_id)[-1]["attempt_id"]
    ledger.record_attempt(
        run.run_id,
        "review",
        "independent-review-session",
        "gpt-5.6-sol",
        "xhigh",
        {"head_sha": HEAD},
        "clean",
        {"head_sha": HEAD, "reviewed_attempt_id": anchor},
        holder="verification-host",
        lease_id=claimed.lease_id,
        idempotency_key="contained-review",
    )
    coordinator_receipt = {
        "verdict": "verified",
        "head_sha": HEAD,
        "summary": "host-fenced merge ready",
        "receipt_ids": ["verified-review"],
        "retry_after": None,
        "review_events": [],
        "human_exception": None,
    }
    substituted = {
        **containment,
        "scope_identity": f"yggdrasil-verification-{'d' * 24}.scope",
    }

    with pytest.raises(
        ValueError,
        match="containment does not match durable verification",
    ):
        ledger.mark_merge_ready(
            run.run_id,
            coordinator_receipt,
            holder="verification-host",
            lease_id=claimed.lease_id,
            containment_receipt=substituted,
        )

    assert ledger.merge_ready_receipt(run.run_id) is None
    ledger.mark_merge_ready(
        run.run_id,
        coordinator_receipt,
        holder="verification-host",
        lease_id=claimed.lease_id,
        containment_receipt=containment,
    )
    marker = ledger.merge_ready_receipt(run.run_id)
    assert marker is not None
    assert marker["containment"] == containment
    with pytest.raises(
        ValueError,
        match="containment does not match durable verification",
    ):
        ledger.mark_merge_ready(
            run.run_id,
            coordinator_receipt,
            holder="verification-host",
            lease_id=claimed.lease_id,
            containment_receipt=substituted,
        )
    assert ledger.merge_ready_receipt(run.run_id) == marker
    api.tasks[run.run_id]["payload"]["merge_ready_receipt"][
        "containment"
    ] = substituted
    with pytest.raises(ValueError, match="containment is stale or substituted"):
        ledger.merge_ready_receipt(run.run_id)


def test_blocking_review_wins_atomic_merge_intent_race() -> None:
    api = BlockingReviewWinsIntentRaceClient()
    ledger, run, outbox = claimed_run(api=api)
    loop = VerificationAgentLoop(
        ledger,
        run.run_id,
        holder="verification-host",
        lease_id=run.lease_id or "",
    )
    api.before_merge_intent = lambda: loop.review(
        finding_id="F-race",
        failure_domain="review_code_correctness",
        mechanism_id="merge-authority",
        session_id="late-blocking-review",
        capability="gpt-5.6-sol",
        reasoning_effort="xhigh",
        context={"head_sha": HEAD},
        outcome="blocking",
    )
    repository = RepositoryAuthority()

    with pytest.raises(
        MergeAuthorityError,
        match="outbox claim is not an eligible current fenced merge intent",
    ):
        VerificationMergeExecutor(
            ledger,
            outbox,
            repository,
            Credentials(),
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert ledger.closure_ready(run.run_id) is False
    assert repository.calls == []
    assert outbox.state == "missing"


def test_merge_revalidates_protected_manifest_and_repo_credential_binding() -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority(
        base_reads=[BASE, BASE, BASE],
        manifest_blobs=["blob-1", "blob-1", "blob-1"],
    )
    credentials = Credentials()
    executor = VerificationMergeExecutor(
        ledger, outbox, repository, credentials
    )

    with pytest.raises(MergeAuthorityError, match="credential selection"):
        executor.execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
            requested_credential_id="credential-for-another-repo",
        )
    assert repository.calls == []
    assert credentials.calls == []

    repository = RepositoryAuthority(
        manifest_blobs=["blob-1", "blob-1", "blob-1"],
    )
    executor = VerificationMergeExecutor(
        ledger, outbox, repository, credentials
    )
    receipt = executor.execute(
        run,
        holder="verification-host",
        lease_id=run.lease_id or "",
        requested_credential_id="github-repo-merge",
    )
    assert receipt.outcome == "merged"
    assert repository.calls == ["merge", "readback"]
    assert repository.last_merge["expected_head_sha"] == HEAD
    assert repository.last_merge["expected_base_sha"] == BASE
    assert repository.last_merge["expected_manifest_blob_sha"] == "blob-1"
    assert repository.last_merge[
        "commit_title"
    ] == fixed_verified_merge_commit_title(3603)
    assert (
        repository.last_merge["commit_message"]
        == FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
    )
    assert credentials.calls == [
        {
            "repository": REPO.lower(),
            "credential_id": "github-repo-merge",
            "rotation_generation": 7,
        }
    ]
    stale_ledger, stale_run, stale_outbox = claimed_run()
    stale = replace(stale_run, current_head_sha="e" * 40)
    with pytest.raises(MergeAuthorityError, match="merge-ready receipt"):
        VerificationMergeExecutor(
            stale_ledger,
            stale_outbox,
            RepositoryAuthority(),
            Credentials(),
        ).execute(
            stale,
            holder="verification-host",
            lease_id=stale_run.lease_id or "",
        )

    missing_ledger, missing_run, missing_outbox = claimed_run()
    missing_ci = RepositoryAuthority(
        gates={
            "ci": False,
            "review": True,
            "protection": True,
            "scope": True,
            "current_head": True,
        }
    )
    with pytest.raises(MergeAuthorityError, match="required CI"):
        VerificationMergeExecutor(
            missing_ledger,
            missing_outbox,
            missing_ci,
            Credentials(),
        ).execute(
            missing_run,
            holder="verification-host",
            lease_id=missing_run.lease_id or "",
        )
    assert missing_ci.calls == []


def test_merge_rejects_divergent_outbox_intent_before_credential_or_effect() -> None:
    ledger, run, outbox = claimed_run()
    outbox.intent_payload_override = {
        "repository": "someone/unrelated",
        "head_sha": HEAD,
    }
    repository = RepositoryAuthority()
    credentials = Credentials()

    with pytest.raises(
        MergeAuthorityError,
        match="outbox claim is not an eligible current fenced merge intent",
    ):
        VerificationMergeExecutor(
            ledger, outbox, repository, credentials
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert credentials.calls == []
    assert repository.calls == []


@pytest.mark.parametrize(
    ("merge_commit_title", "merge_commit_message"),
    (
        ("Fixes #3603", FIXED_VERIFIED_MERGE_COMMIT_MESSAGE),
        (
            fixed_verified_merge_commit_title(3603),
            "Exact-head delivery. Closes #3603.",
        ),
    ),
)
def test_merge_requires_fixed_non_closing_text_in_transport_and_readback(
    merge_commit_title: str,
    merge_commit_message: str,
) -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority(
        merge_commit_title=merge_commit_title,
        merge_commit_message=merge_commit_message,
    )

    with pytest.raises(
        MergeAuthorityError,
        match="not confirmed by exact-head GitHub readback",
    ):
        VerificationMergeExecutor(
            ledger, outbox, repository, Credentials()
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert repository.last_merge["commit_title"] == (
        fixed_verified_merge_commit_title(3603)
    )
    assert (
        repository.last_merge["commit_message"]
        == FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
    )
    assert outbox.state == "pending"
    pending = ledger.pending_effect_binding(run.run_id)
    assert pending is not None
    payload = pending["payload"]
    assert isinstance(payload, Mapping)
    assert payload["fixed_commit_title"] == (
        fixed_verified_merge_commit_title(3603)
    )
    assert (
        payload["fixed_commit_message"]
        == FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
    )
    marker = ledger.merge_ready_receipt(run.run_id)
    assert isinstance(marker, Mapping)
    expected_review_digest = hashlib.sha256(
        json.dumps(
            dict(marker),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    assert payload["review_authority_sha256"] == expected_review_digest
    task_payload = ledger._snapshot(run.run_id)["payload"]
    assert isinstance(task_payload, Mapping)
    assert task_payload["attempt_write_seal"] == {
        "contract": "builderops_attempt_write_seal.v1",
        "operation_key": pending["operation_key"],
        "effect_type": "github.merge",
        "review_authority_sha256": expected_review_digest,
    }


def test_merge_rejects_base_or_manifest_change_after_final_validation() -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority(base_reads=[BASE, NEXT_BASE])
    credentials = Credentials()

    with pytest.raises(MergeAuthorityError, match="changed after final validation"):
        VerificationMergeExecutor(
            ledger, outbox, repository, credentials
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert repository.calls == []
    assert outbox.calls == ["status", "claim", "unknown", "reconcile"]
    assert outbox.state == "succeeded"
    assert credentials.calls == []
    api = ledger.client
    assert any(
        values.get("outbox", {}).get("effect_type") == "github.merge"
        for name, values in api.calls
        if name == "transition_task"
    )


def test_real_merge_requires_stable_prepared_authority_before_any_effect() -> None:
    ledger, run, outbox = claimed_run()
    missing = RepositoryAuthority(prepared_gates=[{}])
    credentials = Credentials()

    with pytest.raises(
        MergeAuthorityError, match="prepared authority does not match"
    ):
        VerificationMergeExecutor(
            ledger, outbox, missing, credentials
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert missing.calls == []
    assert outbox.calls == []
    assert credentials.calls == []

    text_ledger, text_run, text_outbox = claimed_run()
    text_mismatch = RepositoryAuthority(
        prepared_gates=[
            {
                "contract": "verified_merge_prepared_gate.v1",
                "governing_issue": 3603,
                "closing_issues": [3603],
                "neutralized_body_sha256": "a" * 64,
                "authority_sha256": "b" * 64,
                "phase_sha256": "c" * 64,
                "closing_reference_count": 0,
                "fixed_commit_title": "Fixes #3603",
                "fixed_commit_message": (
                    FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
                ),
            }
        ]
    )
    with pytest.raises(
        MergeAuthorityError, match="prepared authority does not match"
    ):
        VerificationMergeExecutor(
            text_ledger, text_outbox, text_mismatch, Credentials()
        ).execute(
            text_run,
            holder="verification-host",
            lease_id=text_run.lease_id or "",
        )
    assert text_mismatch.calls == []
    assert text_outbox.calls == []

    drift_ledger, drift_run, drift_outbox = claimed_run()
    prepared = {
        "contract": "verified_merge_prepared_gate.v1",
        "governing_issue": 3603,
        "closing_issues": [3603],
        "neutralized_body_sha256": "a" * 64,
        "authority_sha256": "b" * 64,
        "phase_sha256": "c" * 64,
        "closing_reference_count": 0,
    }
    drift = RepositoryAuthority(
        prepared_gates=[
            prepared,
            {**prepared, "phase_sha256": "d" * 64},
        ]
    )
    drift_credentials = Credentials()

    with pytest.raises(
        MergeAuthorityError, match="changed after final validation"
    ):
        VerificationMergeExecutor(
            drift_ledger,
            drift_outbox,
            drift,
            drift_credentials,
        ).execute(
            drift_run,
            holder="verification-host",
            lease_id=drift_run.lease_id or "",
        )

    assert drift.calls == []
    assert drift_outbox.state == "succeeded"
    assert drift_credentials.calls == []


def test_timed_out_merge_reconciles_before_retry() -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority(timeout=True, merged=False)

    receipt = VerificationMergeExecutor(
        ledger, outbox, repository, Credentials()
    ).execute(
        run,
        holder="verification-host",
        lease_id=run.lease_id or "",
    )

    assert receipt.outcome == "retry_after_readback"
    assert repository.calls == ["merge", "readback"]


def test_response_loss_reconciles_before_retry() -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority(transport_error=True, merged=False)

    receipt = VerificationMergeExecutor(
        ledger, outbox, repository, Credentials()
    ).execute(
        run,
        holder="verification-host",
        lease_id=run.lease_id or "",
    )

    assert receipt.outcome == "retry_after_readback"
    assert repository.calls == ["merge", "readback"]
    assert outbox.state == "pending"


@pytest.mark.parametrize(
    ("merge_commit_title", "merge_commit_message"),
    (
        ("Fixes #3603", FIXED_VERIFIED_MERGE_COMMIT_MESSAGE),
        ("", FIXED_VERIFIED_MERGE_COMMIT_MESSAGE),
        (
            fixed_verified_merge_commit_title(3603),
            "Closes #3603",
        ),
        (fixed_verified_merge_commit_title(3603), ""),
    ),
)
def test_crash_recovery_rejects_wrong_merge_text_before_base_drift(
    merge_commit_title: str,
    merge_commit_message: str,
) -> None:
    ledger, run, outbox = claimed_run()
    repository = CrashOnceReadbackRepository()
    repository.base_reads = iter([BASE, BASE, NEXT_BASE])
    repository.merge_commit_title = merge_commit_title
    repository.merge_commit_message = merge_commit_message
    executor = VerificationMergeExecutor(
        ledger, outbox, repository, Credentials()
    )

    with pytest.raises(SystemExit, match="before merge readback"):
        executor.execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert outbox.state == "claimed"
    assert outbox.evidence is None
    with pytest.raises(
        MergeAuthorityError,
        match="merged GitHub readback lacks exact governed commit text",
    ):
        executor.recover(run)

    assert outbox.state == "claimed"
    assert outbox.evidence is None
    assert "reconcile" not in outbox.calls


@pytest.mark.parametrize("outbox_status", ("pending", "succeeded"))
def test_recovery_rejects_durable_wrong_text_merged_evidence(
    outbox_status: str,
) -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority(
        manifest_blobs=["blob-1", "blob-1", "blob-1"],
    )
    with pytest.raises(SystemExit, match="simulated host crash"):
        VerificationMergeExecutor(
            ledger, outbox, repository, CrashCredentials()
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )
    outbox.state = outbox_status
    outbox.evidence = {
        "merged": True,
        "head_sha": HEAD,
        "merge_commit_sha": "d" * 40,
        "merge_commit_title": "Fixes #3603",
        "merge_commit_message": FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
    }

    with pytest.raises(
        MergeAuthorityError,
        match="durable merge reconciliation lacks exact governed commit text",
    ):
        VerificationMergeExecutor(
            BuilderOpsVerificationLedger(
                ledger.client,
                repository=REPO,
                effect_outbox=outbox,
            ),
            outbox,
            repository,
            Credentials(),
        ).recover(run)

    assert outbox.state == outbox_status
    assert outbox.evidence["merge_commit_title"] == "Fixes #3603"


def test_pending_reconciliation_cannot_be_upgraded_to_merged_receipt() -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority(
        base_reads=[BASE, BASE, BASE],
        manifest_blobs=["blob-1", "blob-1", "blob-1"],
        transport_error=True,
        merged=False,
    )
    first = VerificationMergeExecutor(
        ledger, outbox, repository, Credentials()
    ).execute(
        run,
        holder="verification-host",
        lease_id=run.lease_id or "",
    )
    assert first.outcome == "retry_after_readback"
    assert outbox.state == "pending"
    outbox.evidence = {
        "merged": True,
        "head_sha": HEAD,
        "merge_commit_sha": "d" * 40,
    }

    restarted = BuilderOpsVerificationLedger(
        ledger.client,
        repository=REPO,
        effect_outbox=outbox,
    )
    with pytest.raises(
        MergeAuthorityError,
        match="durable merge reconciliation lacks exact governed commit text",
    ):
        VerificationMergeExecutor(
            restarted, outbox, repository, Credentials()
        ).recover(run)

    assert outbox.state == "pending"


def test_expired_outbox_claim_performs_no_credential_or_merge_effect() -> None:
    ledger, run, outbox = claimed_run()
    repository = RepositoryAuthority()
    credentials = Credentials()
    original_claim = outbox.claim

    def expired_claim(operation_key: str):
        claim = original_claim(operation_key)
        claim["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        return claim

    outbox.claim = expired_claim  # type: ignore[method-assign]
    with pytest.raises(MergeAuthorityError, match="eligible current fenced"):
        VerificationMergeExecutor(
            ledger, outbox, repository, credentials
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert credentials.calls == []
    assert repository.calls == []


def test_dry_run_commits_and_reconciles_no_merge() -> None:
    ledger, run, outbox = claimed_run("github.merge.dry_run")
    repository = RepositoryAuthority()

    receipt = VerificationMergeExecutor(
        ledger, outbox, repository, Credentials()
    ).execute(
        run,
        holder="verification-host",
        lease_id=run.lease_id or "",
        dry_run=True,
    )

    assert receipt.outcome == "dry_run_no_merge"
    assert repository.calls == []
    assert outbox.calls == ["status", "claim", "unknown", "reconcile"]
    assert outbox.state == "succeeded"


def test_dry_run_recovers_after_crash_with_task_bound_operation() -> None:
    ledger, run, outbox = claimed_run("github.merge.dry_run")
    repository = RepositoryAuthority(
        base_reads=[BASE, BASE, BASE],
        manifest_blobs=["blob-1", "blob-1", "blob-1"],
    )
    with pytest.raises(SystemExit, match="after outbox claim"):
        VerificationMergeExecutor(
            ledger, outbox, repository, CrashCredentials()
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
            dry_run=True,
        )

    restarted = BuilderOpsVerificationLedger(
        ledger.client,
        repository=REPO,
        effect_outbox=outbox,
    )
    receipt = VerificationMergeExecutor(
        restarted, outbox, repository, Credentials()
    ).recover(run, dry_run=True)

    assert receipt.outcome == "dry_run_no_merge"
    assert outbox.state == "succeeded"
    assert outbox.calls[-1] == "reconcile"
    assert "recover" in outbox.calls


def test_merge_recovers_exact_readback_after_transport_return_crash() -> None:
    ledger, run, outbox = claimed_run()
    repository = CrashOnceReadbackRepository()
    with pytest.raises(SystemExit, match="before merge readback"):
        VerificationMergeExecutor(
            ledger, outbox, repository, Credentials()
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    restarted = BuilderOpsVerificationLedger(
        ledger.client,
        repository=REPO,
        effect_outbox=outbox,
    )
    receipt = VerificationMergeExecutor(
        restarted, outbox, repository, Credentials()
    ).recover(run)

    assert receipt.outcome == "merged"
    assert receipt.readback["merge_commit_sha"] == "d" * 40
    assert outbox.state == "succeeded"


def test_merge_reconstructs_receipt_after_durable_reconciliation_crash() -> None:
    ledger, run, original_outbox = claimed_run()
    def _pending_payload():
        snapshot = ledger._snapshot(run.run_id)["payload"]
        pending = snapshot.get("pending_privileged_effect")
        return pending["payload"] if isinstance(pending, Mapping) else {}

    outbox = CrashAfterReconcileOutbox(
        run.run_id,
        payload_loader=_pending_payload,
    )
    ledger.effect_outbox = outbox
    repository = RepositoryAuthority(
        base_reads=[BASE, BASE, BASE],
        manifest_blobs=["blob-1", "blob-1", "blob-1"],
    )

    with pytest.raises(SystemExit, match="durable reconciliation"):
        VerificationMergeExecutor(
            ledger, outbox, repository, Credentials()
        ).execute(
            run,
            holder="verification-host",
            lease_id=run.lease_id or "",
        )

    assert outbox.state == "succeeded"
    restarted = BuilderOpsVerificationLedger(
        ledger.client,
        repository=REPO,
        effect_outbox=outbox,
    )
    calls_before = list(outbox.calls)
    receipt = VerificationMergeExecutor(
        restarted, outbox, repository, Credentials()
    ).recover(run)

    assert receipt.outcome == "merged"
    assert receipt.readback["merge_commit_sha"] == "d" * 40
    assert "recover" not in outbox.calls[len(calls_before) :]
    assert original_outbox.state == "missing"


@pytest.mark.parametrize(
    ("additional_check_conclusion", "expected_ci"),
    [("success", True), ("failure", False)],
)
def test_live_adapter_loads_manifest_from_exact_protected_base(
    additional_check_conclusion: str,
    expected_ci: bool,
) -> None:
    manifest = {
        "repository": REPO,
        "allowed_effects": ["github.merge", "github.merge.dry_run"],
        "github_credential": {
            "credential_id": "github:agentic-pkm-mvp:merge",
            "rotation_generation": 1,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": BASE}})
        if "/contents/.builderops/delivery-manifest.json" in path:
            assert request.url.params["ref"] == BASE
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "encoding": "base64",
                    "sha": "manifest-blob-1",
                    "content": base64.b64encode(
                        json.dumps(manifest).encode()
                    ).decode(),
                },
            )
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                    "merged": False,
                    "merge_commit_sha": None,
                    "merged_at": None,
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 3,
                    "check_runs": [
                        {
                            "id": 1,
                            "name": "verification",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"id": 7},
                        },
                        {
                            "id": 2,
                            "name": "Unit tests (not pg)",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {
                                "id": 7,
                                "slug": "github-actions",
                            },
                            "check_suite": {"id": 70},
                        },
                        {
                            "id": 3,
                            "name": "relevant non-required check",
                            "status": "completed",
                            "conclusion": additional_check_conclusion,
                            "app": {
                                "id": 7,
                                "slug": "github-actions",
                            },
                            "check_suite": {"id": 70},
                        },
                    ],
                },
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200,
                json={"total_count": 0, "statuses": []},
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "workflow_runs": [
                        {
                            "id": 80,
                            "workflow_id": 198962230,
                            "run_attempt": 1,
                            "check_suite_id": 70,
                            "path": ".github/workflows/ci-smoke.yaml",
                            "event": "pull_request",
                            "head_sha": HEAD,
                        }
                    ],
                },
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": [],
                        "checks": [{"context": "verification", "app_id": 7}],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    base = authority.protected_base_sha(REPO)
    protected = authority.delivery_manifest(REPO, base)
    gates = authority.required_gates(REPO, 3603, HEAD)

    assert protected.base_sha == BASE
    assert protected.blob_sha == "manifest-blob-1"
    assert gates["ci"] is expected_ci
    assert all(
        value for name, value in gates.items() if name != "ci"
    )


@pytest.mark.parametrize(
    ("closing_nodes", "accepted"),
    [
        ([], True),
        (
            [
                {
                    "number": 3603,
                    "repository": {"nameWithOwner": REPO},
                }
            ],
            False,
        ),
    ],
)
def test_live_adapter_authenticates_exact_prepared_merge_window(
    closing_nodes: list[dict[str, object]],
    accepted: bool,
) -> None:
    repository = REPO.lower()
    repair_budget = {"policy": "mechanism-keyed-v1", "rounds": 2}
    original_pr: dict[str, object] = {
        "number": 3603,
        "state": "open",
        "merged": False,
        "merged_at": None,
        "merge_commit_sha": None,
        "draft": False,
        "title": "BCP-05 verifier delivery",
        "body": (
            "Governing-Issue: #3603\n\n"
            "Fixes #3603\n\n"
            "Final-Review-Rounds: 2\n"
        ),
        "head": {"sha": HEAD},
    }
    plan = prepare_verified_merge(
        context={
            "contract": "verification_closer_dispatch_context.v2",
            "repository": repository,
            "pr_number": 3603,
            "governing_issue": 3603,
            "closing_issues": [3603],
            "supporting_issues": [],
            "head_sha": HEAD,
            "run_id": "test-run",
            "repair_budget": repair_budget,
        },
        pr=original_pr,
        live_closing_issues=[3603],
        merge_readiness={
            "contract": VERIFIED_MERGE_READINESS_CONTRACT,
            "head_sha": HEAD,
            "required_checks_green": True,
            "review_gate_resolved": True,
            "further_commits_anticipated": False,
        },
    )
    authority_receipt = plan["authority_receipt"]
    assert isinstance(authority_receipt, Mapping)
    prepared_pr = {
        **original_pr,
        "body": plan["neutralized_body"],
    }
    phase = build_verified_merge_phase(
        authority_receipt=authority_receipt,
        phase="prepared",
        pr=prepared_pr,
    )
    comments = [
        {
            "author_association": "COLLABORATOR",
            "body": plan["authority_receipt_comment"],
        },
        {
            "author_association": "COLLABORATOR",
            "body": phase["phase_receipt_comment"],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls/3603"):
            return httpx.Response(200, json=prepared_pr)
        if request.url.path.endswith("/issues/3603/comments"):
            return httpx.Response(200, json=comments)
        if request.url.path == "/graphql":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "closingIssuesReferences": {
                                    "nodes": closing_nodes,
                                    "pageInfo": {"hasNextPage": False},
                                }
                            }
                        }
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    adapter = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    if not accepted:
        with pytest.raises(
            MergeAuthorityError, match="empty closers"
        ):
            adapter.verified_merge_prepared(
                REPO,
                3603,
                run_id="test-run",
                head_sha=HEAD,
                expected_repair_budget=repair_budget,
            )
        return

    gate = adapter.verified_merge_prepared(
        REPO,
        3603,
        run_id="test-run",
        head_sha=HEAD,
        expected_repair_budget=repair_budget,
    )
    assert gate["repository"] == repository
    assert gate["governing_issue"] == 3603
    assert gate["closing_issues"] == [3603]
    assert gate["closing_reference_count"] == 0
    assert gate["fixed_commit_title"] == fixed_verified_merge_commit_title(3603)
    assert (
        gate["fixed_commit_message"]
        == FIXED_VERIFIED_MERGE_COMMIT_MESSAGE
    )


def test_live_adapter_rejects_failing_required_status_and_nondefault_base() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "feature",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            return httpx.Response(
                200, json={"total_count": 0, "check_runs": []}
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "statuses": [
                        {
                            "id": 1,
                            "context": "legacy-required",
                            "state": "failure",
                        }
                    ],
                },
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200, json={"total_count": 0, "workflow_runs": []}
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": ["legacy-required"],
                        "checks": [],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gates = authority.required_gates(REPO, 3603, HEAD)

    assert gates["ci"] is False
    assert gates["scope"] is False
    assert gates["protection"] is True


def test_live_adapter_paginates_required_check_runs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        page = int(request.url.params.get("page", "1"))
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            rows = (
                [
                    {
                        "id": index + 1,
                        "name": f"other-{index}",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    }
                    for index in range(100)
                ]
                if page == 1
                else [
                    {
                        "id": 101,
                        "name": "required-last",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    },
                    {
                        "id": 102,
                        "name": "Unit tests (not pg)",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7, "slug": "github-actions"},
                        "check_suite": {"id": 70},
                    },
                ]
            )
            return httpx.Response(
                200, json={"total_count": 102, "check_runs": rows}
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200, json={"total_count": 0, "statuses": []}
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "workflow_runs": [
                        {
                            "id": 80,
                            "workflow_id": 198962230,
                            "run_attempt": 1,
                            "check_suite_id": 70,
                            "path": ".github/workflows/ci-smoke.yaml",
                            "event": "pull_request",
                            "head_sha": HEAD,
                        }
                    ],
                },
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": [],
                        "checks": [
                            {"context": "required-last", "app_id": 7}
                        ],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gates = authority.required_gates(REPO, 3603, HEAD)

    assert all(gates.values())


@pytest.mark.parametrize(
    ("method_name", "path_suffix", "collection_key"),
    (
        ("_check_runs", f"/commits/{HEAD}/check-runs", "check_runs"),
        ("_workflow_runs", "/actions/runs", "workflow_runs"),
        ("_commit_statuses", f"/commits/{HEAD}/status", "statuses"),
    ),
)
@pytest.mark.parametrize("defect", ("duplicate_page", "changed_total"))
def test_live_adapter_rejects_false_complete_counted_authority(
    method_name: str,
    path_suffix: str,
    collection_key: str,
    defect: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(path_suffix)
        page = int(request.url.params["page"])
        start = 1 if page == 1 or defect == "duplicate_page" else 101
        total = 200 if page == 1 or defect == "duplicate_page" else 201
        return httpx.Response(
            200,
            json={
                "total_count": total,
                collection_key: [
                    {"id": index} for index in range(start, start + 100)
                ],
            },
        )

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    with pytest.raises(
        MergeAuthorityError,
        match="malformed|total changed",
    ):
        getattr(authority, method_name)(REPO, HEAD)


def test_live_adapter_rejects_ambiguous_workflow_suite_provenance() -> None:
    common = {
        "workflow_id": 198962230,
        "path": ".github/workflows/docs-guard.yml",
        "event": "pull_request",
        "head_sha": HEAD,
        "check_suite_id": 71,
        "run_attempt": 1,
        "created_at": "2026-07-30T10:00:00Z",
    }

    with pytest.raises(
        MergeAuthorityError,
        match="workflow-suite provenance is ambiguous",
    ):
        _workflow_runs_by_suite(
            [
                {"id": 81, **common},
                {"id": 82, **common},
            ],
            head_sha=HEAD,
        )


def test_live_adapter_rejects_malformed_multirow_check_history() -> None:
    with pytest.raises(
        MergeAuthorityError,
        match="rerun history is malformed",
    ):
        _latest_github_result(
            [
                {
                    "id": 90,
                    "completed_at": "2026-07-30T10:00:00Z",
                    "status": "completed",
                    "conclusion": "failure",
                },
                {
                    "id": 91,
                    "status": "completed",
                    "conclusion": "failure",
                },
            ]
        )


def test_live_adapter_rejects_malformed_timestamp_before_fallback() -> None:
    with pytest.raises(
        MergeAuthorityError,
        match="rerun history timestamp is malformed",
    ):
        _latest_github_result(
            [
                {
                    "id": 90,
                    "completed_at": "2026-07-30T10:00:00Z",
                    "status": "completed",
                    "conclusion": "failure",
                },
                {
                    "id": 91,
                    "completed_at": 123,
                    "updated_at": "2099-01-01T00:00:00Z",
                    "status": "completed",
                    "conclusion": "success",
                },
            ]
        )


@pytest.mark.parametrize(
    "defect",
    ("unnamed_check", "invalid_suite", "malformed_timestamp"),
)
def test_live_adapter_rejects_malformed_check_reduction(
    defect: str,
) -> None:
    checks: list[dict[str, object]] = [
        {
            "id": 10,
            "name": "Unit tests (not pg)",
            "status": "completed",
            "conclusion": "success",
            "completed_at": "2026-07-30T10:00:00Z",
            "app": {"id": 7, "slug": "github-actions"},
            "check_suite": {"id": 70},
        }
    ]
    if defect == "unnamed_check":
        checks.append(
            {
                "id": 11,
                "status": "completed",
                "conclusion": "failure",
                "completed_at": "2026-07-30T10:01:00Z",
                "app": {"id": 7, "slug": "github-actions"},
                "check_suite": {"id": 70},
            }
        )
    elif defect == "invalid_suite":
        checks.append(
            {
                "id": 11,
                "name": "Docs Guard",
                "status": "completed",
                "conclusion": "failure",
                "completed_at": "2026-07-30T10:01:00Z",
                "app": {"id": 7, "slug": "github-actions"},
                "check_suite": {"id": 0},
            }
        )
    else:
        checks.extend(
            [
                {
                    "id": 11,
                    "name": "Docs Guard",
                    "status": "completed",
                    "conclusion": "failure",
                    "completed_at": "2026-07-30T10:01:00Z",
                    "app": {"id": 7, "slug": "github-actions"},
                    "check_suite": {"id": 70},
                },
                {
                    "id": 12,
                    "name": "Docs Guard",
                    "status": "completed",
                    "conclusion": "success",
                    "completed_at": "not-a-time",
                    "app": {"id": 7, "slug": "github-actions"},
                    "check_suite": {"id": 70},
                },
            ]
        )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            return httpx.Response(
                200,
                json={"total_count": len(checks), "check_runs": checks},
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200, json={"total_count": 0, "statuses": []}
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "workflow_runs": [
                        {
                            "id": 80,
                            "workflow_id": 198962230,
                            "path": ".github/workflows/ci-smoke.yaml",
                            "event": "pull_request",
                            "head_sha": HEAD,
                            "check_suite_id": 70,
                            "run_attempt": 1,
                        }
                    ],
                },
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": [],
                        "checks": [
                            {
                                "context": "Unit tests (not pg)",
                                "app_id": 7,
                            }
                        ],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    with pytest.raises(
        MergeAuthorityError,
        match="check-run|check-suite|timestamp",
    ):
        authority.required_gates(REPO, 3603, HEAD)


def test_live_adapter_rejects_green_push_masking_failed_pr_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 6,
                    "check_runs": [
                        {
                            "id": 10,
                            "name": "verification",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"id": 7},
                        },
                        {
                            "id": 11,
                            "name": "Unit tests (not pg)",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {
                                "id": 7,
                                "slug": "github-actions",
                            },
                            "check_suite": {"id": 70},
                        },
                        {
                            "id": 12,
                            "name": "Docs Guard",
                            "status": "completed",
                            "conclusion": "failure",
                            "completed_at": "2026-07-30T10:00:00Z",
                            "app": {
                                "id": 7,
                                "slug": "github-actions",
                            },
                            "check_suite": {"id": 70},
                        },
                        {
                            "id": 13,
                            "name": "Docs Guard",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {
                                "id": 7,
                                "slug": "github-actions",
                            },
                            "check_suite": {"id": 71},
                        },
                        {
                            "id": 14,
                            "name": "Docs Guard",
                            "status": "completed",
                            "conclusion": "success",
                            "completed_at": "2026-07-30T10:01:00Z",
                            "app": {
                                "id": 7,
                                "slug": "other-app",
                            },
                        },
                        {
                            "id": 15,
                            "name": "Docs Guard",
                            "status": "completed",
                            "conclusion": "success",
                            "completed_at": "2026-07-30T10:02:00Z",
                            "app": {
                                "id": 7,
                                "slug": "github-actions",
                            },
                            "check_suite": {"id": 72},
                        },
                    ],
                },
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200, json={"total_count": 0, "statuses": []}
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 3,
                    "workflow_runs": [
                        {
                            "id": 80,
                            "workflow_id": 198962230,
                            "run_attempt": 1,
                            "check_suite_id": 70,
                            "path": ".github/workflows/ci-smoke.yaml",
                            "event": "pull_request",
                            "head_sha": HEAD,
                        },
                        {
                            "id": 81,
                            "workflow_id": 198962230,
                            "run_attempt": 1,
                            "check_suite_id": 71,
                            "path": ".github/workflows/docs-guard.yml",
                            "event": "push",
                            "head_sha": HEAD,
                        },
                        {
                            "id": 82,
                            "workflow_id": 222,
                            "run_attempt": 1,
                            "check_suite_id": 72,
                            "path": ".github/workflows/unrelated.yml",
                            "event": "pull_request",
                            "head_sha": HEAD,
                        },
                    ],
                },
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": [],
                        "checks": [
                            {"context": "verification", "app_id": 7}
                        ],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gates = authority.required_gates(REPO, 3603, HEAD)

    assert gates["ci"] is False
    assert all(
        value for name, value in gates.items() if name != "ci"
    )


def test_live_adapter_reads_exact_merge_commit_title_and_message() -> None:
    merge_sha = "d" * 40
    expected_title = fixed_verified_merge_commit_title(3603)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "merged": True,
                    "head": {"sha": HEAD},
                    "merge_commit_sha": merge_sha,
                    "merged_at": "2026-07-30T12:00:00Z",
                },
            )
        if path.endswith(f"/commits/{merge_sha}"):
            return httpx.Response(
                200,
                json={
                    "commit": {
                        "message": (
                            f"{expected_title}\n\n"
                            f"{FIXED_VERIFIED_MERGE_COMMIT_MESSAGE}"
                        )
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    readback = authority.merge_readback(REPO.lower(), 3603)

    assert readback == {
        "merged": True,
        "head_sha": HEAD,
        "merge_commit_sha": merge_sha,
        "merge_commit_title": expected_title,
        "merge_commit_message": FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
        "merged_at": "2026-07-30T12:00:00Z",
    }


def test_app_bound_required_check_rejects_same_name_legacy_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            return httpx.Response(
                200, json={"total_count": 0, "check_runs": []}
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "statuses": [
                        {
                            "id": 1,
                            "context": "app-bound",
                            "state": "success",
                        }
                    ],
                },
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200, json={"total_count": 0, "workflow_runs": []}
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": [],
                        "checks": [{"context": "app-bound", "app_id": 7}],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gates = authority.required_gates(REPO, 3603, HEAD)

    assert gates["ci"] is False


@pytest.mark.parametrize(
    "protected_context",
    ["Unit tests (not pg)", "another-required-check"],
)
def test_mandatory_behavioral_check_rejects_legacy_status_substitution(
    protected_context: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            return httpx.Response(
                200, json={"total_count": 0, "check_runs": []}
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200,
                json={
                    "total_count": 2,
                    "statuses": [
                        {
                            "id": 1,
                            "context": "Unit tests (not pg)",
                            "state": "success",
                        },
                        {
                            "id": 2,
                            "context": "another-required-check",
                            "state": "success",
                        },
                    ],
                },
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200, json={"total_count": 0, "workflow_runs": []}
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": [protected_context],
                        "checks": [],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gates = authority.required_gates(REPO, 3603, HEAD)

    assert gates["ci"] is False
    assert gates["protection"] is True


@pytest.mark.parametrize("required_kind", ["check", "status"])
def test_live_adapter_uses_only_latest_required_rerun(
    required_kind: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            rows = (
                [
                    {
                        "id": 10,
                        "name": "rerun-required",
                        "status": "completed",
                        "conclusion": "success",
                        "completed_at": "2026-07-30T08:00:00Z",
                        "app": {"id": 7},
                    },
                    {
                        "id": 11,
                        "name": "rerun-required",
                        "status": "completed",
                        "conclusion": "failure",
                        "completed_at": "2026-07-30T09:00:00Z",
                        "app": {"id": 7},
                    },
                ]
                if required_kind == "check"
                else []
            )
            return httpx.Response(
                200, json={"total_count": len(rows), "check_runs": rows}
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            statuses = (
                [
                    {
                        "id": 20,
                        "context": "rerun-required",
                        "state": "success",
                        "updated_at": "2026-07-30T08:00:00Z",
                    },
                    {
                        "id": 21,
                        "context": "rerun-required",
                        "state": "failure",
                        "updated_at": "2026-07-30T09:00:00Z",
                    },
                ]
                if required_kind == "status"
                else []
            )
            return httpx.Response(
                200,
                json={"total_count": len(statuses), "statuses": statuses},
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200, json={"total_count": 0, "workflow_runs": []}
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": (
                            ["rerun-required"]
                            if required_kind == "status"
                            else []
                        ),
                        "checks": (
                            [{"context": "rerun-required", "app_id": 7}]
                            if required_kind == "check"
                            else []
                        ),
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gates = authority.required_gates(REPO, 3603, HEAD)

    assert gates["ci"] is False


@pytest.mark.parametrize(
    ("conclusion", "workflow_path", "expected_ci"),
    [
        ("success", ".github/workflows/ci-smoke.yaml", True),
        ("skipped", ".github/workflows/ci-smoke.yaml", False),
        ("neutral", ".github/workflows/ci-smoke.yaml", False),
        ("success", ".github/workflows/foreign.yaml", False),
    ],
)
def test_required_behavioral_check_requires_authenticated_success(
    conclusion: str,
    workflow_path: str,
    expected_ci: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO.lower()}":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/pulls/3603"):
            return httpx.Response(
                200,
                json={
                    "head": {"sha": HEAD},
                    "base": {
                        "ref": "main",
                        "repo": {"full_name": REPO},
                    },
                },
            )
        if path.endswith(f"/commits/{HEAD}/check-runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "check_runs": [
                        {
                            "id": 30,
                            "name": "Unit tests (not pg)",
                            "status": "completed",
                            "conclusion": conclusion,
                            "completed_at": "2026-07-30T09:00:00Z",
                            "app": {"id": 7, "slug": "github-actions"},
                            "check_suite": {"id": 70},
                        }
                    ],
                },
            )
        if path.endswith(f"/commits/{HEAD}/status"):
            return httpx.Response(
                200, json={"total_count": 0, "statuses": []}
            )
        if path.endswith("/actions/runs"):
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "workflow_runs": [
                        {
                            "id": 80,
                            "workflow_id": 198962230,
                            "run_attempt": 1,
                            "check_suite_id": 70,
                            "path": workflow_path,
                            "event": "pull_request",
                            "head_sha": HEAD,
                        }
                    ],
                },
            )
        if path.endswith("/branches/main/protection"):
            return httpx.Response(
                200,
                json={
                    "required_status_checks": {
                        "contexts": [],
                        "checks": [
                            {
                                "context": "Unit tests (not pg)",
                                "app_id": 7,
                            }
                        ],
                    }
                },
            )
        raise AssertionError(f"unexpected GitHub request: {request.url}")

    authority = GitHubProtectedRepositoryAuthority(
        "host-read-token",
        http_client=httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ),
    )

    gates = authority.required_gates(REPO, 3603, HEAD)

    assert gates["ci"] is expected_ci
