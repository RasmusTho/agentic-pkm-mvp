from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.dispatcher.verification_api import BuilderOpsVerificationLedger
from app.dispatcher.verification_github import GitHubProtectedRepositoryAuthority
from app.dispatcher.verification_merge import (
    MergeAuthorityError,
    ProtectedDeliveryManifest,
    VerificationMergeExecutor,
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
        self.timeout = timeout
        self.transport_error = transport_error
        self.merged = merged
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
        self, run_id: str, effect_type: str = "github.merge"
    ) -> None:
        self.run_id = run_id
        self.effect_type = effect_type
        self.calls = []
        self.state = "missing"
        self.evidence = None

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
            "payload": {},
        }

    def recover(self, operation_key: str):
        self.calls.append("recover")
        return self.claim(operation_key)

    def status(self, operation_key: str):
        self.calls.append("status")
        return {
            "status": self.state,
            "reconciliation_evidence": self.evidence,
            "reconciliation_receipt_sequence": (
                3 if self.evidence is not None else None
            ),
        }

    def mark_unknown(self, claim, *, detail: str):
        self.calls.append("unknown")
        self.state = "unknown"

    def reconcile(self, claim, *, observed_applied: bool, evidence):
        self.calls.append("reconcile")
        self.state = "succeeded" if observed_applied else "pending"
        self.evidence = dict(evidence)
        return {"status": self.state}


class CrashAfterReconcileOutbox(Outbox):
    def reconcile(self, claim, *, observed_applied: bool, evidence):
        super().reconcile(
            claim,
            observed_applied=observed_applied,
            evidence=evidence,
        )
        raise SystemExit("simulated crash after durable reconciliation")


def claimed_run(
    effect_type: str = "github.merge",
):
    api = FakeBuilderOpsClient()
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
    outbox = Outbox(ready.run_id, effect_type)
    ledger.effect_outbox = outbox
    return ledger, ready, outbox


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

    repository = RepositoryAuthority()
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
    recovered = VerificationMergeExecutor(
        restarted, outbox, repository, Credentials()
    ).recover(run)

    assert recovered.outcome == "retry_after_readback"


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
    outbox = CrashAfterReconcileOutbox(run.run_id)
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


def test_live_adapter_loads_manifest_from_exact_protected_base() -> None:
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
                    "total_count": 2,
                    "check_runs": [
                        {
                            "name": "verification",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"id": 7},
                        },
                        {
                            "name": "Unit tests (not pg)",
                            "status": "completed",
                            "conclusion": "success",
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
    assert all(gates.values())


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
                        {"context": "legacy-required", "state": "failure"}
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
                        "name": "required-last",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 7},
                    },
                    {
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
                        {"context": "app-bound", "state": "success"}
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
                            "context": "Unit tests (not pg)",
                            "state": "success",
                        },
                        {
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
