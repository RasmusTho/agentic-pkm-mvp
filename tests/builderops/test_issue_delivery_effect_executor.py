"""Protected host execution contract for one approved Issue delivery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from psycopg import sql

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
)
from app.builderops.issue_delivery_effect_executor import (
    BuilderOpsIssueDeliveryEffectLedger,
    ContentOnlyIssueDeliverySessionLauncher,
    DestinationBinding,
    EffectAuthorityReadback,
    EffectReadback,
    FrozenIssueDeliveryDestination,
    GitIssueDeliveryDestination,
    IssueDeliveryEffectRequest,
    IssueDeliveryHostExecutor,
    PreparedIssueDeliveryWorker,
    WorkerIsolationBinding,
)
from app.builderops.control_plane.issue_delivery import (
    REQUIRED_WORKFLOW_ARTIFACTS,
    canonical_hash,
)
from app.builderops.control_plane.service import create_app
from app.builderops.control_plane.store import PostgresBuilderOpsStore
from app.builderops.issue_delivery_worker_isolation import (
    LinuxSystemdCodexIssueSessionLauncher,
)
from app.dispatcher.verification_merge import (
    BuilderOpsOutboxExecutor,
    ProtectedDeliveryManifest,
)

REPOSITORY = "rasmustho/agentic-pkm-mvp"
BASE_SHA = "a" * 40
REPO_ROOT = Path(__file__).resolve().parents[2]


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _isolation_receipt() -> dict[str, Any]:
    return {
        "contract": "builderops_issue_delivery_worker_isolation_receipt.v1",
        "profile_id": "issue-delivery-content-worker",
        "profile_version": 1,
        "profile_sha256": "1" * 64,
        "executor": {"uid": 1000, "gid": 1000, "supplementary_gids": [27]},
        "worker": {"uid": 2000, "gid": 2000, "supplementary_gids": []},
        "unit_identity": "yggdrasil-issue-worker-0123456789abcdef.service",
        "worktree_identity_sha256": "2" * 64,
        "executable_set_identity_sha256": "3" * 64,
        "model_auth_reference": "codex-login-1",
        "model_auth_identity_sha256": "4" * 64,
        "protected_credential_identity_sha256": "5" * 64,
        "probe_result": "denied",
        "worker_write_access_probe_result": "worktree-writable-git-denied",
        "git_metadata_write_denied": True,
        "command_sha256": "6" * 64,
        "isolation_properties_sha256": "7" * 64,
        "isolation_template_sha256": "7" * 64,
        "no_new_privileges": True,
        "child_environment_keys": ["CODEX_HOME", "HOME", "LANG", "LC_ALL", "PATH"],
        "entered_at": "2026-09-15T12:00:00Z",
    }


def _isolation() -> WorkerIsolationBinding:
    return WorkerIsolationBinding.from_receipt(_isolation_receipt())


def _destination(tmp_path: Path) -> FrozenIssueDeliveryDestination:
    checkout = tmp_path / "checkout"
    worktree = tmp_path / "worktree"
    git_dir = tmp_path / "worktree-git"
    common = tmp_path / "common-git"
    for path in (checkout, worktree, git_dir, common):
        path.mkdir(parents=True, exist_ok=True)
    binding = DestinationBinding(
        identity="destination:shared",
        run_id="run-5558",
        host_identity="host:test",
        system_identity="system:builderops",
        channel="dev",
        repository=REPOSITORY,
        checkout=checkout,
        worktree=worktree,
        branch="codex/5558-protected-host-executor-v2",
        base_ref="main",
        base_sha=BASE_SHA,
    )
    return FrozenIssueDeliveryDestination.capture(
        binding,
        git_directory=git_dir,
        common_git_directory=common,
        origin_url="https://github.com/RasmusTho/agentic-pkm-mvp.git",
    )


def _approval(
    destination: FrozenIssueDeliveryDestination,
    executor_artifact: Path,
    isolation_artifact: Path,
    *,
    parent: bool = False,
) -> dict[str, Any]:
    artifacts = [
        {
            "path": "app/builderops/issue_delivery_effect_executor.py",
            "sha256": _sha(executor_artifact.read_bytes()),
        },
        {
            "path": "app/builderops/issue_delivery_worker_isolation.py",
            "sha256": _sha(isolation_artifact.read_bytes()),
        },
    ]
    return {
        "contract_version": "fca-issue-delivery.v1",
        "operation_type": "deliver_ready_issue",
        "approval_id": "approval-5558",
        "operation_key": "operation-5558",
        "approval_manifest_hash": "8" * 64,
        "authority_epoch": 7,
        "repository": REPOSITORY,
        "issue": {
            "number": 5558,
            "node_id": "I_issue5558",
            "state": "open",
            "labels": ["agent:ready"],
            "body_hash": "9" * 64,
            "acceptance_criteria_hash": "a" * 64,
        },
        "source": {"revision": BASE_SHA},
        "workflow": {"content_hash": "b" * 64, "artifacts": artifacts},
        "profile": {
            "content_hash": "c" * 64,
            "verification_profile": {"content_hash": "d" * 64},
        },
        "destination": destination.binding.as_manifest(),
        "permitted_effects": [
            "repository_worktree",
            "issue_claim",
            "publication",
            "review_merge",
            "closure_reconciliation",
        ],
        "parent_evidence": (
            {
                "kind": "issue",
                "repository": REPOSITORY,
                "number": 5399,
                "node_id": "I_parent5399",
                "relationship": {
                    "kind": "parent",
                    "child_issue_number": 5558,
                    "authenticated": True,
                },
                "contract_version": "fca-parent.v1",
                "contract_hash": "e" * 64,
                "write_permission": {
                    "scope": "parent_evidence:write",
                    "effects": [
                        "pr_receipt_comments",
                        "child_generated_ledger_writeback",
                    ],
                },
            }
            if parent
            else {"kind": "none"}
        ),
    }


def _request(
    approval: Mapping[str, Any],
    destination: FrozenIssueDeliveryDestination,
    isolation: WorkerIsolationBinding,
    executor_artifact: Path,
    isolation_artifact: Path,
    *,
    effect_kind: str = "claim",
) -> IssueDeliveryEffectRequest:
    issue = approval["issue"]
    source = approval["source"]
    workflow = approval["workflow"]
    profile = approval["profile"]
    verification = profile["verification_profile"]
    issue_number = int(issue["number"])
    issue_node_id = str(issue["node_id"])
    targets: dict[str, dict[str, Any]] = {
        "claim": {
            "kind": "claim",
            "issue_number": issue_number,
            "issue_node_id": issue_node_id,
            "expected_state": "open",
            "expected_label": "agent:ready",
        },
        "publication": {
            "kind": "publication",
            "issue_number": issue_number,
            "branch": destination.binding.branch,
            "base_ref": "main",
            "base_sha": destination.binding.base_sha,
            "head_sha": "f" * 40,
            "title_sha256": "1" * 64,
            "body_sha256": "2" * 64,
            "expected_remote_ref_state": "absent",
        },
        "merge": {
            "kind": "merge",
            "issue_number": issue_number,
            "pr_number": 6000,
            "branch": destination.binding.branch,
            "base_ref": "main",
            "base_sha": destination.binding.base_sha,
            "head_sha": "f" * 40,
        },
        "closure": {
            "kind": "closure",
            "issue_number": issue_number,
            "pr_number": 6000,
            "merge_commit_sha": "3" * 40,
            "expected_issue_state": "open",
        },
        "parent_evidence": {
            "kind": "parent_evidence",
            "repository": REPOSITORY,
            "issue_number": 5399,
            "issue_node_id": "I_parent5399",
            "expected_state": "open",
            "child_issue_number": issue_number,
            "parent_contract_sha256": str(
                approval.get("parent_evidence", {}).get("contract_hash", "e" * 64)
            ),
            "relationship_sha256": canonical_hash(
                approval.get("parent_evidence", {}).get(
                    "relationship",
                    {
                        "kind": "parent",
                        "child_issue_number": issue_number,
                        "authenticated": True,
                    },
                )
            ),
            "evidence_kind": "pr_receipt_comment",
            "evidence_sha256": "4" * 64,
        },
    }
    return IssueDeliveryEffectRequest.model_validate(
        {
            "contract": "builderops.issue-delivery-effect.v1",
            "effect_kind": effect_kind,
            "approval": dict(approval),
            "approval_id": approval["approval_id"],
            "approved_operation_key": approval["operation_key"],
            "approval_manifest_hash": approval["approval_manifest_hash"],
            "repository": approval["repository"],
            "issue_number": issue_number,
            "issue_body_hash": issue["body_hash"],
            "acceptance_criteria_hash": issue["acceptance_criteria_hash"],
            "run_id": approval["destination"]["run_id"],
            "source_revision": source["revision"],
            "workflow_hash": workflow["content_hash"],
            "profile_hash": profile["content_hash"],
            "verification_profile_hash": verification["content_hash"],
            "authority_epoch": approval["authority_epoch"],
            "destination": {
                **destination.binding.model_dump(mode="json"),
                "frozen_identity_sha256": destination.identity_sha256,
            },
            "worker_isolation": isolation.model_dump(mode="json"),
            "executor_artifact_sha256": _sha(executor_artifact.read_bytes()),
            "worker_isolation_artifact_sha256": _sha(isolation_artifact.read_bytes()),
            "target": targets[effect_kind],
        }
    )


class _Authority:
    def __init__(self, approval: Mapping[str, Any]) -> None:
        self.approval = deepcopy(dict(approval))
        self.revoked = False
        self.readback_revoked = False
        self.epoch_drifted = False
        self.reads: list[str] = []

    def issue_delivery_authority(
        self, *, manifest: Mapping[str, Any], purpose: str
    ) -> Mapping[str, Any]:
        assert dict(manifest) == self.approval
        self.reads.append(purpose)
        if purpose == "execute" and self.revoked:
            raise ValueError("permission revoked")
        if purpose == "readback" and self.readback_revoked:
            raise ValueError("readback permission revoked")
        return {
            "approval": deepcopy(self.approval),
            "operation_key": self.approval["operation_key"],
            "authority_epoch": self.approval["authority_epoch"]
            + (1 if self.epoch_drifted else 0),
            "purpose": purpose,
        }


class _DestinationGuard:
    def __init__(self, frozen: FrozenIssueDeliveryDestination) -> None:
        self.frozen = frozen
        self.drifted = False
        self.checks = 0

    def assert_frozen(
        self, frozen: FrozenIssueDeliveryDestination, approval: Mapping[str, Any]
    ) -> None:
        del approval
        self.checks += 1
        if frozen != self.frozen or self.drifted:
            raise ValueError("destination changed")


class _RepositoryAuthority:
    def __init__(self) -> None:
        self.drifted = False

    def delivery_manifest(
        self, repository: str, base_sha: str
    ) -> ProtectedDeliveryManifest:
        return ProtectedDeliveryManifest(
            repository=repository,
            base_sha=base_sha,
            blob_sha=("5" if not self.drifted else "6") * 40,
            content_sha256=("7" if not self.drifted else "8") * 64,
            credential_id="github-writer",
            credential_generation=3,
            allowed_effects=(
                "github.issue-delivery.claim.v1",
                "github.issue-delivery.publication.v1",
                "github.issue-delivery.merge.v1",
                "github.issue-delivery.closure.v1",
                "github.issue-delivery.parent-evidence.v1",
            ),
        )


class _Credentials:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(
        self, *, repository: str, credential_id: str, rotation_generation: int
    ) -> object:
        assert (repository, credential_id, rotation_generation) == (
            REPOSITORY,
            "github-writer",
            3,
        )
        self.calls += 1
        return object()


class _BlockingCredentials(_Credentials):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def resolve(
        self, *, repository: str, credential_id: str, rotation_generation: int
    ) -> object:
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test credential fence was not released")
        return super().resolve(
            repository=repository,
            credential_id=credential_id,
            rotation_generation=rotation_generation,
        )


class _Transport:
    def __init__(self) -> None:
        self.apply_calls = 0
        self.raise_on_apply = False
        self.target_override: Mapping[str, Any] | None = None
        self.readback_target_override: str | None = None
        self.readbacks = ["applied"]
        self.on_apply: Callable[[], None] | None = None

    def validate_target(
        self, request: IssueDeliveryEffectRequest
    ) -> EffectAuthorityReadback:
        value = {
            "request_sha256": request.content_sha256,
            "repository": request.repository,
            "issue_number": request.issue_number,
            "issue_body_hash": request.issue_body_hash,
            "acceptance_criteria_hash": request.acceptance_criteria_hash,
            "source_revision": request.source_revision,
            "profile_hash": request.profile_hash,
            "verification_profile_hash": request.verification_profile_hash,
            "target": request.target.model_dump(mode="json"),
        }
        if self.target_override:
            value.update(self.target_override)
        return EffectAuthorityReadback.model_validate(value)

    def apply(self, request: IssueDeliveryEffectRequest, credential: object) -> None:
        del request, credential
        self.apply_calls += 1
        if self.on_apply is not None:
            self.on_apply()
        if self.raise_on_apply:
            raise TimeoutError("ambiguous GitHub response")

    def readback(self, request: IssueDeliveryEffectRequest) -> EffectReadback:
        return EffectReadback(
            request_sha256=request.content_sha256,
            outcome=self.readbacks.pop(0),
            evidence={
                "source": "github-authoritative-readback",
                "observed_target_sha256": self.readback_target_override
                or canonical_hash(request.target.model_dump(mode="json")),
            },
        )


class _Ledger:
    def __init__(self) -> None:
        self.state = "missing"
        self.intent: dict[str, Any] | None = None
        self.effect_claim: dict[str, Any] | None = None
        self.recovery_claims = 0
        self.reconciliations: list[tuple[bool, Mapping[str, Any]]] = []
        self.lose_next_unknown_write = False
        self.effect_revalidation_override: Mapping[str, Any] | None = None

    def operation_key(self, *, request_sha256: str, effect_type: str) -> str:
        assert request_sha256 and effect_type
        return "outbox-operation"

    def begin(
        self, *, request_sha256: str, effect_type: str, payload: Mapping[str, Any]
    ) -> str:
        self.intent = {
            "request_sha256": request_sha256,
            "effect_type": effect_type,
            "task_id": f"issue-delivery-effect:{request_sha256}",
            "payload": dict(payload),
        }
        self.state = "pending"
        return "outbox-operation"

    def status(self, operation_key: str) -> Mapping[str, Any]:
        return {
            "operation_key": operation_key,
            "status": self.state,
            **(self.intent or {}),
        }

    def claim_effect(
        self, operation_key: str, *, effect_type: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        assert self.intent is not None
        self.effect_claim = {
            "operation_key": operation_key,
            "effect_type": effect_type,
            "task_id": self.intent["task_id"],
            "payload": dict(payload),
            "effect_eligible": True,
            "fencing_token": 1,
            "receipt_sequence": 1,
            "claim_lsn": "0/1",
            "intent_lsn": "0/1",
            "worker_id": "host-executor",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "repository": REPOSITORY,
        }
        self.state = "claimed"
        return dict(self.effect_claim)

    def revalidate_effect_claim(
        self, claim: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        current = {
            key: value
            for key, value in claim.items()
            if key not in {"payload", "effect_eligible"}
        }
        current["effect_eligible"] = True
        if self.effect_revalidation_override:
            current.update(self.effect_revalidation_override)
        return current

    def claim_for_readback(self, operation_key: str) -> Mapping[str, Any]:
        assert self.effect_claim is not None
        self.recovery_claims += 1
        return {
            **self.effect_claim,
            "operation_key": operation_key,
            "effect_eligible": False,
            "readback_only": True,
            "recovery_kind": "recovered_attempt",
        }

    def mark_unknown(self, claim: Mapping[str, Any], *, detail: str) -> None:
        assert claim["effect_eligible"] is True and detail
        if self.lose_next_unknown_write:
            self.lose_next_unknown_write = False
            raise TimeoutError("unknown transition response lost")
        self.state = "unknown"

    def reconcile(
        self,
        claim: Mapping[str, Any],
        *,
        observed_applied: bool,
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        assert claim["readback_only"] is True
        assert claim["effect_eligible"] is False
        self.reconciliations.append((observed_applied, dict(evidence)))
        self.state = "succeeded" if observed_applied else "pending"
        return {"status": self.state}


def _executor(tmp_path: Path, *, effect_kind: str = "claim", parent: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    executor_artifact = tmp_path / "issue_delivery_effect_executor.py"
    isolation_artifact = tmp_path / "issue_delivery_worker_isolation.py"
    executor_artifact.write_text("host executor\n", encoding="utf-8")
    isolation_artifact.write_text("worker isolation\n", encoding="utf-8")
    destination = _destination(tmp_path)
    isolation = _isolation()
    approval = _approval(
        destination, executor_artifact, isolation_artifact, parent=parent
    )
    request = _request(
        approval,
        destination,
        isolation,
        executor_artifact,
        isolation_artifact,
        effect_kind=effect_kind,
    )
    authority = _Authority(approval)
    destination_guard = _DestinationGuard(destination)
    repository = _RepositoryAuthority()
    credentials = _Credentials()
    ledger = _Ledger()
    transport = _Transport()
    executor = IssueDeliveryHostExecutor(
        authority=authority,
        ledger=ledger,
        repository_authority=repository,
        credentials=credentials,
        destination=destination_guard,
        frozen_destination=destination,
        worker_isolation=isolation,
        transport=transport,
        trusted_executor_artifact=executor_artifact,
        trusted_worker_isolation_artifact=isolation_artifact,
    )
    return (
        executor,
        request,
        authority,
        destination_guard,
        repository,
        credentials,
        ledger,
        transport,
    )


def _schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


@pytest.fixture
def issue_delivery_pg_store() -> PostgresBuilderOpsStore:
    base = (
        os.getenv("BUILDEROPS_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )
    if not base:
        pytest.skip("no explicit non-production BuilderOps PostgreSQL DSN configured")
    schema = f"builderops_effect_executor_{uuid4().hex}"
    try:
        with psycopg.connect(base, connect_timeout=2, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL unavailable for host-executor test: {exc}")
    store = PostgresBuilderOpsStore(_schema_dsn(base, schema))
    store.initialize()
    try:
        yield store
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )


def _production_registry(tmp_path: Path) -> CredentialRegistry:
    entries: list[dict[str, Any]] = []
    for credential_id, principal, token, scopes, principal_kind in (
        (
            "owner",
            "owner:human",
            "owner-pg-token",
            ["issue_delivery:approve", "issue_delivery:read", "status:read"],
            "human",
        ),
        (
            "issue-delivery-host",
            "destination:shared",
            "executor-pg-token",
            [
                "issue_delivery:execute",
                "issue_delivery:read",
                "outbox:write",
                "receipts:read",
                "status:read",
                "tasks:write",
            ],
            "agent",
        ),
    ):
        secret = tmp_path / f"{credential_id}.secret"
        secret.write_text(token, encoding="utf-8")
        entries.append(
            {
                "id": credential_id,
                "principal": principal,
                "secret_ref": f"host-secret:{credential_id}",
                "secret_file": str(secret),
                "scopes": scopes,
                "repositories": [REPOSITORY],
                "rotation_generation": 1,
                "principal_kind": principal_kind,
            }
        )
    manifest_path = tmp_path / "builderops-credentials.json"
    manifest_path.write_text(json.dumps({"credentials": entries}), encoding="utf-8")
    return CredentialRegistry(manifest_path)


def _production_client(
    store: PostgresBuilderOpsStore,
    registry: CredentialRegistry,
    token: str,
) -> BuilderOpsControlPlaneClient:
    return BuilderOpsControlPlaneClient(
        ClientConfig(base_url="http://builderops", token=token),
        http_client=TestClient(create_app(store=store, credentials=registry)),
        max_retries=0,
    )


def _production_manifest(
    *,
    checkout: Path,
    worktree: Path,
    base_sha: str,
    operation_key: str,
) -> dict[str, Any]:
    # This is the established FCA-ID-A production manifest fixture, rebound to
    # the test's real checkout/worktree and the exact current trusted files.
    from tests.builderops.test_control_plane_issue_delivery import _manifest

    manifest = deepcopy(_manifest(operation_key=operation_key))
    manifest["approval_id"] = (
        f"approval-pg-{_sha(operation_key.encode('utf-8'))[:24]}"
    )
    branch = f"codex/pg-effect-{uuid4().hex[:12]}"
    destination = manifest["destination"]
    destination.update(
        {
            "checkout": str(checkout),
            "worktree": str(worktree),
            "branch": branch,
            "base_sha": base_sha,
        }
    )
    manifest["source"]["revision"] = base_sha
    manifest["source"]["refs"] = ["github:issue:5550", f"git:{base_sha}"]
    dispatch_plan = manifest["context"]["dispatch_plan"]
    context_pack = dispatch_plan["context_packs"][0]
    context_pack["branch_worktree_plan"].update(
        {"branch": branch, "worktree": str(worktree)}
    )
    manifest["context"]["content_hash"] = canonical_hash(context_pack)
    manifest["context"]["expected_plan_hash"] = canonical_hash(dispatch_plan)
    artifacts = [
        {
            "path": path,
            "sha256": _sha((REPO_ROOT / path).read_bytes()),
        }
        for path in sorted(REQUIRED_WORKFLOW_ARTIFACTS)
    ]
    manifest["workflow"]["artifacts"] = artifacts
    manifest["workflow"]["content_hash"] = canonical_hash(artifacts)
    return manifest


@dataclass(frozen=True)
class _ProductionHarness:
    store: PostgresBuilderOpsStore
    registry: CredentialRegistry
    owner: BuilderOpsControlPlaneClient
    client: BuilderOpsControlPlaneClient
    approval: Mapping[str, Any]
    destination: GitIssueDeliveryDestination
    frozen: FrozenIssueDeliveryDestination
    prepared_worker: PreparedIssueDeliveryWorker
    isolation: WorkerIsolationBinding
    request: IssueDeliveryEffectRequest
    ledger: BuilderOpsIssueDeliveryEffectLedger
    credentials: _Credentials
    transport: _Transport
    executor: IssueDeliveryHostExecutor
    checkout: Path
    worktree: Path
    preparation_observed: tuple[bool, ...]


@pytest.fixture
def issue_delivery_production_harness(
    issue_delivery_pg_store: PostgresBuilderOpsStore,
    tmp_path: Path,
) -> Callable[..., _ProductionHarness]:
    counter = 0

    def build(
        *, effect_kind: str = "claim", parent: bool = False
    ) -> _ProductionHarness:
        nonlocal counter
        counter += 1
        case = tmp_path / f"production-{counter}"
        checkout = case / "checkout"
        worktree = case / "worktrees" / "issue-delivery"
        checkout.mkdir(parents=True)
        subprocess.run(
            ["git", "init", "--initial-branch=main", str(checkout)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "config", "user.name", "Host Executor Test"],
            check=True,
        )
        (checkout / "tracked.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(checkout), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(checkout), "commit", "-m", "base"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "remote",
                "add",
                "origin",
                "https://github.com/RasmusTho/agentic-pkm-mvp.git",
            ],
            check=True,
        )
        base_sha = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        registry = _production_registry(case)
        owner = _production_client(
            issue_delivery_pg_store, registry, "owner-pg-token"
        )
        client = _production_client(
            issue_delivery_pg_store, registry, "executor-pg-token"
        )
        manifest = _production_manifest(
            checkout=checkout,
            worktree=worktree,
            base_sha=base_sha,
            operation_key=f"operation-pg-{uuid4().hex}",
        )
        if parent:
            raise ValueError("production parent fixture is not yet required")
        preview = owner.issue_delivery_preview(manifest=manifest)
        approval = owner.issue_delivery_start(
            decision="start", manifest=preview["manifest"]
        )["approval"]
        destination = GitIssueDeliveryDestination()
        preparation_observed: list[bool] = []
        launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)

        def launcher_factory(
            frozen: FrozenIssueDeliveryDestination,
        ) -> ContentOnlyIssueDeliverySessionLauncher:
            preparation_observed.append(
                frozen.binding.worktree.is_dir()
                and frozen.binding.worktree == worktree
            )
            return launcher

        prepared_worker = PreparedIssueDeliveryWorker.create(
            approval=approval,
            destination=destination,
            launcher_factory=launcher_factory,
        )
        frozen = prepared_worker.frozen_destination
        isolation = _isolation()
        request = _request(
            approval,
            frozen,
            isolation,
            REPO_ROOT / "app/builderops/issue_delivery_effect_executor.py",
            REPO_ROOT / "app/builderops/issue_delivery_worker_isolation.py",
            effect_kind=effect_kind,
        )
        ledger = BuilderOpsIssueDeliveryEffectLedger(
            client,
            repository=REPOSITORY,
            run_id=request.run_id,
            approval_id=request.approval_id,
            worker_id="issue-delivery-host",
        )
        credentials = _Credentials()
        transport = _Transport()
        executor = IssueDeliveryHostExecutor(
            authority=client,
            ledger=ledger,
            repository_authority=_RepositoryAuthority(),
            credentials=credentials,
            destination=destination,
            frozen_destination=frozen,
            worker_isolation=isolation,
            transport=transport,
        )
        return _ProductionHarness(
            store=issue_delivery_pg_store,
            registry=registry,
            owner=owner,
            client=client,
            approval=approval,
            destination=destination,
            frozen=frozen,
            prepared_worker=prepared_worker,
            isolation=isolation,
            request=request,
            ledger=ledger,
            credentials=credentials,
            transport=transport,
            executor=executor,
            checkout=checkout,
            worktree=worktree,
            preparation_observed=tuple(preparation_observed),
        )

    return build


@pytest.mark.pg
def test_worker_has_no_ambient_repository_mutation_identity(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    harness = issue_delivery_production_harness()
    assert isinstance(
        harness.prepared_worker.launcher,
        ContentOnlyIssueDeliverySessionLauncher,
    )
    assert issubclass(
        ContentOnlyIssueDeliverySessionLauncher,
        LinuxSystemdCodexIssueSessionLauncher,
    )
    assert harness.preparation_observed == (True,)
    assert harness.isolation.worker_uid != harness.isolation.executor_uid
    assert harness.isolation.worker_gid != harness.isolation.executor_gid
    assert harness.isolation.worker_supplementary_gids == ()
    assert harness.isolation.repository_credential_probe == "denied"
    assert harness.isolation.git_metadata_write_denied is True
    receipt = harness.executor.execute(harness.request)
    assert receipt.outcome == "applied"
    status = harness.ledger.status(receipt.operation_key)
    assert status["status"] == "succeeded"
    assert status["payload"]["worker_isolation_binding_sha256"] == canonical_hash(
        harness.isolation.model_dump(mode="json")
    )
    assert harness.transport.apply_calls == 1


@pytest.mark.pg
def test_production_harness_keeps_immutable_approvals_distinct(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    first = issue_delivery_production_harness()
    second = issue_delivery_production_harness()
    assert first.approval["approval_id"] != second.approval["approval_id"]
    assert first.approval["operation_key"] != second.approval["operation_key"]
    assert first.owner.issue_delivery_readback(
        repository=REPOSITORY,
        approval_id=str(first.approval["approval_id"]),
    )["approval"] == first.approval
    assert second.owner.issue_delivery_readback(
        repository=REPOSITORY,
        approval_id=str(second.approval["approval_id"]),
    )["approval"] == second.approval


@pytest.mark.pg
@pytest.mark.parametrize("effect_kind", ["claim", "publication", "merge", "closure"])
def test_host_executor_applies_only_exact_authorized_delivery_effect(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    effect_kind: str,
) -> None:
    harness = issue_delivery_production_harness(effect_kind=effect_kind)
    receipt = harness.executor.execute(harness.request)
    assert receipt.outcome == "applied"
    assert harness.ledger.status(receipt.operation_key)["status"] == "succeeded"
    assert harness.transport.apply_calls == 1
    assert harness.credentials.calls == 1
    serialized = receipt.as_dict()
    assert "worktree" not in serialized
    assert "credential" not in serialized
    broadened = harness.request.model_dump(mode="json")
    broadened["target"]["other_issue"] = 5559
    with pytest.raises(ValidationError):
        IssueDeliveryEffectRequest.model_validate(broadened)


@pytest.mark.pg
def test_revocation_and_target_drift_fail_closed(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    revoked = issue_delivery_production_harness()
    credential_manifest = json.loads(
        revoked.registry.manifest_path.read_text(encoding="utf-8")
    )
    credential_manifest["credentials"][1]["revoked"] = True
    revoked.registry.manifest_path.write_text(
        json.dumps(credential_manifest), encoding="utf-8"
    )
    with pytest.raises(Exception, match="revoked|credential"):
        revoked.executor.execute(revoked.request)
    assert revoked.transport.apply_calls == revoked.credentials.calls == 0

    drifted = issue_delivery_production_harness()
    drifted.transport.target_override = {"source_revision": "b" * 40}
    with pytest.raises(ValueError, match="target/source/profile"):
        drifted.executor.execute(drifted.request)
    assert drifted.transport.apply_calls == drifted.credentials.calls == 0
    assert drifted.ledger.status(
        drifted.ledger.operation_key(
            request_sha256=drifted.request.content_sha256,
            effect_type="github.issue-delivery.claim.v1",
        )
    )["status"] == "pending"


@pytest.mark.pg
def test_host_prepares_and_freezes_destination_before_entry(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
) -> None:
    harness = issue_delivery_production_harness()
    assert harness.preparation_observed == (True,)
    assert harness.worktree.is_dir()
    assert harness.frozen.binding.worktree == harness.worktree
    moved = harness.worktree.with_name("issue-delivery-moved")
    harness.worktree.rename(moved)
    try:
        with pytest.raises(ValueError, match="Git identity"):
            harness.executor.execute(harness.request)
    finally:
        moved.rename(harness.worktree)
    assert harness.transport.apply_calls == harness.credentials.calls == 0


def test_unit_worker_binding_rejects_ambient_repository_identity() -> None:
    assert issubclass(
        ContentOnlyIssueDeliverySessionLauncher, LinuxSystemdCodexIssueSessionLauncher
    )
    receipt = _isolation_receipt()
    binding = WorkerIsolationBinding.from_receipt(receipt)
    assert binding.worker_uid != binding.executor_uid
    assert binding.worker_gid != binding.executor_gid
    assert binding.worker_supplementary_gids == ()
    assert binding.git_metadata_write_denied is True
    assert binding.repository_credential_probe == "denied"

    same_user = deepcopy(receipt)
    same_user["worker"]["uid"] = same_user["executor"]["uid"]
    with pytest.raises(ValueError, match="distinct OS principal"):
        WorkerIsolationBinding.from_receipt(same_user)

    mutable_git = deepcopy(receipt)
    mutable_git["git_metadata_write_denied"] = False
    with pytest.raises(ValueError, match="Git metadata"):
        WorkerIsolationBinding.from_receipt(mutable_git)

    launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)
    launcher.developer_instructions = "Implement the bounded content change."
    prompt = launcher.prompt({"branch_worktree_plan": {"worktree": "/worktrees/5558"}})
    assert "propose only typed" in prompt
    assert "must not run Git or GitHub lifecycle effects" in prompt
    assert "Self-claim" not in prompt


@pytest.mark.parametrize("effect_kind", ["claim", "publication", "merge", "closure"])
def test_unit_host_executor_applies_only_exact_authorized_delivery_effect(
    tmp_path: Path, effect_kind: str
) -> None:
    (
        executor,
        request,
        _authority,
        destination,
        _repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path, effect_kind=effect_kind)
    receipt = executor.execute(request)
    assert receipt.outcome == "applied"
    assert (
        receipt.as_dict()["destination_identity_sha256"]
        == request.destination.frozen_identity_sha256
    )
    assert "worktree" not in receipt.as_dict()
    assert transport.apply_calls == 1
    assert credentials.calls == 1
    assert destination.checks == 2
    assert ledger.reconciliations[-1][0] is True
    assert ledger.intent is not None
    assert "worker_isolation" not in ledger.intent["payload"]
    assert "worker_isolation_binding_sha256" in ledger.intent["payload"]

    incomplete = request.model_dump(mode="json")
    incomplete.pop("profile_hash")
    with pytest.raises(ValidationError):
        IssueDeliveryEffectRequest.model_validate(incomplete)
    broadened = request.model_dump(mode="json")
    broadened["target"]["other_issue"] = 5559
    with pytest.raises(ValidationError):
        IssueDeliveryEffectRequest.model_validate(broadened)
    with pytest.raises(ValidationError):
        EffectReadback.model_validate(
            {
                "request_sha256": request.content_sha256,
                "outcome": "applied",
                "evidence": {
                    "source": "github-authoritative-readback",
                    "observed_target_sha256": _sha(
                        json.dumps(
                            request.target.model_dump(mode="json"), sort_keys=True
                        ).encode()
                    ),
                    "local_path": "/tmp/leak",
                },
            }
        )


def test_unit_unknown_effect_requires_readback_before_retry(tmp_path: Path) -> None:
    (
        executor,
        request,
        authority,
        _destination_guard,
        _repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path)
    transport.raise_on_apply = True
    transport.readbacks = ["unknown", "not_applied", "applied"]
    ledger.lose_next_unknown_write = True

    first = executor.execute(request)
    assert first.outcome == "unknown"
    assert transport.apply_calls == 1
    assert ledger.state == "unknown"
    assert authority.reads[-1] == "readback"

    authority.revoked = True
    fresh_executor = IssueDeliveryHostExecutor(
        authority=authority,
        ledger=ledger,
        repository_authority=_RepositoryAuthority(),
        credentials=credentials,
        destination=_DestinationGuard(executor.frozen_destination),
        frozen_destination=executor.frozen_destination,
        worker_isolation=executor.worker_isolation,
        transport=transport,
        trusted_executor_artifact=tmp_path / "issue_delivery_effect_executor.py",
        trusted_worker_isolation_artifact=tmp_path
        / "issue_delivery_worker_isolation.py",
    )
    second = fresh_executor.execute(request)
    assert second.outcome == "retry_after_readback"
    assert ledger.state == "pending"
    assert ledger.recovery_claims == 2
    assert transport.apply_calls == 1
    assert credentials.calls == 1
    assert authority.reads[-1] == "readback"

    (
        denied_executor,
        denied_request,
        denied_authority,
        _denied_destination,
        _denied_repository,
        _denied_credentials,
        denied_ledger,
        denied_transport,
    ) = _executor(tmp_path / "readback-revoked")
    denied_transport.on_apply = lambda: setattr(
        denied_authority, "readback_revoked", True
    )
    with pytest.raises(ValueError, match="readback permission revoked"):
        denied_executor.execute(denied_request)
    assert denied_transport.apply_calls == 1
    assert denied_ledger.state == "unknown"
    assert denied_transport.readbacks == ["applied"]


def test_issue_delivery_ledger_reuses_outbox_with_bounded_scope() -> None:
    client = object()
    default_outbox = BuilderOpsOutboxExecutor(  # type: ignore[arg-type]
        client,
        repository=REPOSITORY,
        worker_id="verification-worker",
    )
    assert default_outbox.envelope["scope"] == "verification-executor"
    assert default_outbox.claim_ttl_seconds == 300

    ledger = BuilderOpsIssueDeliveryEffectLedger(  # type: ignore[arg-type]
        client,
        repository=REPOSITORY,
        run_id="run-5558",
        approval_id="approval-5558",
        worker_id="issue-delivery-host",
    )
    assert ledger.outbox.envelope["scope"] == "issue-delivery-executor"
    assert ledger.outbox.claim_ttl_seconds == ledger.claim_ttl_seconds


def test_issue_delivery_approval_binds_executor_and_worker_boundary() -> None:
    assert (
        "app/builderops/issue_delivery_effect_executor.py"
        in REQUIRED_WORKFLOW_ARTIFACTS
    )


def test_production_manifest_allocates_unique_approval_identity(tmp_path: Path) -> None:
    first = _production_manifest(
        checkout=tmp_path / "checkout-1",
        worktree=tmp_path / "worktree-1",
        base_sha="a" * 40,
        operation_key="operation-1",
    )
    second = _production_manifest(
        checkout=tmp_path / "checkout-2",
        worktree=tmp_path / "worktree-2",
        base_sha="b" * 40,
        operation_key="operation-2",
    )
    assert first["approval_id"] != second["approval_id"]
    assert first["operation_key"] != second["operation_key"]
    replay = _production_manifest(
        checkout=tmp_path / "checkout-1",
        worktree=tmp_path / "worktree-1",
        base_sha="a" * 40,
        operation_key="operation-1",
    )
    assert replay["approval_id"] == first["approval_id"]
    assert (
        "app/builderops/issue_delivery_worker_isolation.py"
        in REQUIRED_WORKFLOW_ARTIFACTS
    )


@pytest.mark.pg
def test_unknown_effect_requires_readback_before_retry(
    issue_delivery_production_harness: Callable[..., _ProductionHarness],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = issue_delivery_production_harness()
    issue_delivery_pg_store = harness.store
    registry = harness.registry
    client = harness.client
    destination = harness.destination
    frozen = harness.frozen
    isolation = harness.isolation
    request = harness.request
    ledger = harness.ledger
    credentials = harness.credentials
    transport = harness.transport
    transport.raise_on_apply = True
    transport.readbacks = ["unknown", "not_applied"]
    executor = harness.executor

    original_mark_unknown = client.mark_outbox_unknown
    lose_first_response = True

    def committed_unknown_with_lost_response(*args: Any, **kwargs: Any) -> Any:
        nonlocal lose_first_response
        result = original_mark_unknown(*args, **kwargs)
        if lose_first_response:
            lose_first_response = False
            raise TimeoutError("unknown transition response was lost")
        return result

    monkeypatch.setattr(
        client, "mark_outbox_unknown", committed_unknown_with_lost_response
    )
    first = executor.execute(request)
    assert first.outcome == "unknown"
    assert transport.apply_calls == credentials.calls == 1
    assert ledger.status(first.operation_key)["status"] == "unknown"

    def expire_current_fence() -> None:
        with psycopg.connect(issue_delivery_pg_store.dsn) as conn:
            conn.execute(
                "UPDATE builderops_outbox "
                "SET claim_expires_at = clock_timestamp() - interval '1 second' "
                "WHERE repository = %s AND operation_key = %s",
                (REPOSITORY, first.operation_key),
            )

    expire_current_fence()
    # The first process must discard its now-expired cached claim and obtain a
    # fresh readback-only recovery fence, never an effect-eligible claim.
    ledger.clock = lambda: datetime.max.replace(tzinfo=timezone.utc)
    cached_recovery = ledger.claim_for_readback(first.operation_key)
    assert cached_recovery["readback_only"] is True
    assert cached_recovery["effect_eligible"] is False
    assert cached_recovery["recovery_kind"] == "recovered_attempt"

    expire_current_fence()
    credential_manifest = json.loads(registry.manifest_path.read_text(encoding="utf-8"))
    credential_manifest["credentials"][0]["revoked"] = True
    registry.manifest_path.write_text(json.dumps(credential_manifest), encoding="utf-8")
    # A process with no cached claim can still use the separately scoped
    # readback grant after owner revocation, but cannot repeat the GitHub effect.
    fresh_ledger = BuilderOpsIssueDeliveryEffectLedger(
        client,
        repository=REPOSITORY,
        run_id=request.run_id,
        approval_id=request.approval_id,
        worker_id="issue-delivery-host",
    )
    fresh_executor = IssueDeliveryHostExecutor(
        authority=client,
        ledger=fresh_ledger,
        repository_authority=_RepositoryAuthority(),
        credentials=credentials,
        destination=destination,
        frozen_destination=frozen,
        worker_isolation=isolation,
        transport=transport,
    )
    recovered = fresh_executor.execute(request)
    assert recovered.outcome == "retry_after_readback"
    assert fresh_ledger.status(first.operation_key)["status"] == "pending"
    assert transport.apply_calls == credentials.calls == 1

    with psycopg.connect(issue_delivery_pg_store.dsn) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count, MAX(claim_fencing_token) AS fence "
            "FROM builderops_outbox WHERE repository = %s AND operation_key = %s",
            (REPOSITORY, first.operation_key),
        ).fetchone()
        receipt_events = conn.execute(
            "SELECT event_type FROM builderops_receipts "
            "WHERE repository = %s AND task_id = %s ORDER BY receipt_sequence",
            (REPOSITORY, f"issue-delivery-effect:{request.content_sha256}"),
        ).fetchall()
    assert row == (1, 3)
    assert [event[0] for event in receipt_events].count("outbox.recovered") == 2
    assert any(event[0] == "outbox.reconciled.pending" for event in receipt_events)

    # Stall an old process before the final fence check, then expire, recover,
    # and negatively reconcile its attempt.  When resumed, the old process
    # must observe the new DB fence and never invoke the external transport.
    race = issue_delivery_production_harness()
    stalled_ledger = BuilderOpsIssueDeliveryEffectLedger(
        race.client,
        repository=REPOSITORY,
        run_id=race.request.run_id,
        approval_id=race.request.approval_id,
        worker_id="issue-delivery-host",
    )
    blocked_credentials = _BlockingCredentials()
    stale_transport = _Transport()
    stalled_executor = IssueDeliveryHostExecutor(
        authority=race.client,
        ledger=stalled_ledger,
        repository_authority=_RepositoryAuthority(),
        credentials=blocked_credentials,
        destination=race.destination,
        frozen_destination=race.frozen,
        worker_isolation=race.isolation,
        transport=stale_transport,
    )
    stalled_result: list[object] = []

    def run_stalled_executor() -> None:
        try:
            stalled_result.append(stalled_executor.execute(race.request))
        except Exception as exc:
            stalled_result.append(exc)

    thread = Thread(target=run_stalled_executor, daemon=True)
    thread.start()
    assert blocked_credentials.entered.wait(timeout=10)
    race_operation_key = stalled_ledger.operation_key(
        request_sha256=race.request.content_sha256,
        effect_type="github.issue-delivery.claim.v1",
    )
    with psycopg.connect(race.store.dsn) as conn:
        conn.execute(
            "UPDATE builderops_outbox "
            "SET claim_expires_at = clock_timestamp() - interval '1 second' "
            "WHERE repository = %s AND operation_key = %s",
            (REPOSITORY, race_operation_key),
        )
    recovery_ledger = BuilderOpsIssueDeliveryEffectLedger(
        race.client,
        repository=REPOSITORY,
        run_id=race.request.run_id,
        approval_id=race.request.approval_id,
        worker_id="issue-delivery-host",
    )
    recovery_claim = recovery_ledger.claim_for_readback(race_operation_key)
    assert recovery_claim["effect_eligible"] is False
    recovery_ledger.reconcile(
        recovery_claim,
        observed_applied=False,
        evidence={
            "outcome": "not_applied",
            "request_sha256": race.request.content_sha256,
            "source": "github-authoritative-readback",
        },
    )
    blocked_credentials.release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(stalled_result) == 1
    assert isinstance(stalled_result[0], ValueError)
    assert "not exact authority" in str(stalled_result[0])
    assert stale_transport.apply_calls == 0

    with psycopg.connect(race.store.dsn) as conn:
        race_row = conn.execute(
            "SELECT status, claim_fencing_token FROM builderops_outbox "
            "WHERE repository = %s AND operation_key = %s",
            (REPOSITORY, race_operation_key),
        ).fetchone()
    assert race_row == ("pending", 2)


def test_unit_revocation_and_target_drift_fail_closed(tmp_path: Path) -> None:
    (
        executor,
        request,
        authority,
        destination,
        repository,
        credentials,
        ledger,
        transport,
    ) = _executor(tmp_path)
    authority.revoked = True
    with pytest.raises(ValueError, match="revoked"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    authority.revoked = False
    changed_target = request.target.model_dump(mode="json")
    changed_target["issue_number"] = 5559
    transport.target_override = {"target": changed_target}
    with pytest.raises(ValueError, match="target/source/profile"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0
    assert ledger.state == "pending"

    transport.target_override = None
    destination.drifted = True
    with pytest.raises(ValueError, match="destination"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    destination.drifted = False
    repository.drifted = True
    with pytest.raises(ValueError, match="protected repository manifest changed"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    (tmp_path / "issue_delivery_effect_executor.py").write_text(
        "replaced\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="artifact"):
        executor.execute(request)
    assert transport.apply_calls == credentials.calls == 0

    epoch_executor, epoch_request, epoch_authority, *_ = _executor(tmp_path / "epoch")
    epoch_authority.epoch_drifted = True
    with pytest.raises(ValueError, match="authority changed"):
        epoch_executor.execute(epoch_request)

    source_executor, source_request, *_rest, source_transport = _executor(
        tmp_path / "source"
    )
    source_transport.target_override = {"source_revision": "b" * 40}
    with pytest.raises(ValueError, match="target/source/profile"):
        source_executor.execute(source_request)
    assert source_transport.apply_calls == 0

    profile_executor, profile_request, *_rest, profile_transport = _executor(
        tmp_path / "profile"
    )
    profile_transport.target_override = {"profile_hash": "e" * 64}
    with pytest.raises(ValueError, match="target/source/profile"):
        profile_executor.execute(profile_request)
    assert profile_transport.apply_calls == 0

    parent_executor, parent_request, *_rest, parent_transport = _executor(
        tmp_path / "parent", effect_kind="parent_evidence", parent=True
    )
    foreign_parent = parent_request.model_dump(mode="json")
    foreign_parent["target"]["issue_number"] = 5400
    with pytest.raises(ValueError, match="parent evidence"):
        parent_executor.execute(
            IssueDeliveryEffectRequest.model_validate(foreign_parent)
        )
    assert parent_transport.apply_calls == 0

    readback_executor, readback_request, *_rest, readback_transport = _executor(
        tmp_path / "readback"
    )
    readback_transport.raise_on_apply = True
    readback_transport.readback_target_override = "f" * 64
    with pytest.raises(ValueError, match="readback target changed"):
        readback_executor.execute(readback_request)
    assert readback_transport.apply_calls == 1

    stale_executor, stale_request, *_rest, stale_ledger, stale_transport = _executor(
        tmp_path / "stale-fence"
    )
    stale_ledger.effect_revalidation_override = {"fencing_token": 2}
    with pytest.raises(ValueError, match="fence changed"):
        stale_executor.execute(stale_request)
    assert stale_transport.apply_calls == 0

    expired_executor, expired_request, *_ = _executor(tmp_path / "expired-fence")
    expired_claim = {
        "repository": REPOSITORY,
        "operation_key": "outbox-operation",
        "worker_id": "host-executor",
        "fencing_token": 1,
        "intent_lsn": "0/1",
        "claim_lsn": "0/2",
        "receipt_sequence": 1,
        "expires_at": "2000-01-01T00:00:00+00:00",
        "task_id": f"issue-delivery-effect:{expired_request.content_sha256}",
        "effect_type": "github.issue-delivery.claim.v1",
        "effect_eligible": True,
        "payload": {},
    }
    with pytest.raises(ValueError, match="not exact authority"):
        expired_executor._validate_effect_claim(
            expired_claim,
            "outbox-operation",
            "github.issue-delivery.claim.v1",
            {},
            repository=REPOSITORY,
        )


def test_unit_host_prepares_and_freezes_destination_before_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    worktree = tmp_path / "worktrees" / "issue-5558"
    checkout.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(checkout)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "config", "user.name", "Issue Delivery Test"],
        check=True,
    )
    (checkout / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "tracked.txt"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-m", "base"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "remote",
            "add",
            "origin",
            "https://github.com/RasmusTho/agentic-pkm-mvp.git",
        ],
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    approval = {
        "repository": REPOSITORY,
        "destination": DestinationBinding(
            identity="destination:shared",
            run_id="run-5558",
            host_identity="host:test",
            system_identity="system:builderops",
            channel="dev",
            repository=REPOSITORY,
            checkout=checkout,
            worktree=worktree,
            branch="codex/5558-host-prepared",
            base_ref="main",
            base_sha=base_sha,
        ).as_manifest(),
    }
    guard = GitIssueDeliveryDestination()
    calls: list[bool] = []

    launcher = object.__new__(ContentOnlyIssueDeliverySessionLauncher)

    def fake_launch(self, context_pack, *, execution_routing=None):
        del self, context_pack, execution_routing
        calls.append(True)
        return {
            "session_id": "session",
            "worker_receipt": {},
            "isolation_receipt": _isolation_receipt(),
        }

    monkeypatch.setattr(ContentOnlyIssueDeliverySessionLauncher, "launch", fake_launch)

    worker = PreparedIssueDeliveryWorker.create(
        approval=approval,
        destination=guard,
        launcher_factory=lambda frozen: (
            launcher
            if frozen.binding.worktree.is_dir()
            else pytest.fail("worktree not prepared")
        ),
    )
    result = worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    assert result["isolation_receipt"]["git_metadata_write_denied"] is True
    assert calls == [True]

    absent = worktree.with_name("issue-5558-absent")
    worktree.rename(absent)
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    absent.rename(worktree)

    original = worktree.with_name("issue-5558-original")
    worktree.rename(original)
    worktree.mkdir()
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    worktree.rmdir()
    original.rename(worktree)

    subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "remote",
            "set-url",
            "origin",
            "https://github.com/example/issue-delivery-mismatch.git",
        ],
        check=True,
    )
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "remote",
            "set-url",
            "origin",
            "https://github.com/RasmusTho/agentic-pkm-mvp.git",
        ],
        check=True,
    )

    subprocess.run(
        ["git", "-C", str(worktree), "switch", "-c", "foreign"],
        check=True,
        capture_output=True,
    )
    with pytest.raises(ValueError, match="Git identity"):
        worker.launch({"branch_worktree_plan": {"worktree": str(worktree)}})
    assert calls == [True]
