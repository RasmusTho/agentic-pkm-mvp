"""Shared PostgreSQL Issue-delivery production harness fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import base64
from copy import deepcopy
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
import httpx
from fastapi.testclient import TestClient
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
    EXECUTOR_ARTIFACT,
    EffectAuthorityReadback,
    EffectReadback,
    FrozenIssueDeliveryDestination,
    GitIssueDeliveryDestination,
    IssueDeliveryEffectRequest,
    IssueDeliveryHostExecutor,
    PreparedIssueDeliveryWorker,
    WORKER_ISOLATION_ARTIFACT,
    WorkerIsolationBinding,
)
from app.builderops.control_plane.issue_delivery import (
    REQUIRED_WORKFLOW_ARTIFACTS,
    canonical_hash,
)
from app.builderops.control_plane.service import create_app
from app.builderops.control_plane.store import PostgresBuilderOpsStore
from app.builderops.issue_delivery_worker_isolation import (
    ISOLATION_PROFILE_CONTRACT,
    CredentialProbeResult,
    ExecutableIdentity,
    REQUIRED_SYSTEMD_PROPERTIES_SHA256,
    ResolvedPrincipal,
    WorkerAccessProbeResult,
    canonical_command_sha256,
    file_sha256,
)
from app.builderops.epic_dispatch import CodexIssueSessionLauncher
from app.dispatcher.verification_github import GitHubProtectedRepositoryAuthority

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
    workflow_root: Path,
    *,
    parent: bool = False,
) -> dict[str, Any]:
    artifact_paths = {path: workflow_root / path for path in REQUIRED_WORKFLOW_ARTIFACTS}
    artifact_paths[EXECUTOR_ARTIFACT] = executor_artifact
    artifact_paths[WORKER_ISOLATION_ARTIFACT] = isolation_artifact
    artifacts = [
        {"path": path, "sha256": _sha(artifact_paths[path].read_bytes())}
        for path in sorted(REQUIRED_WORKFLOW_ARTIFACTS)
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
        "destination": {
            **destination.binding.as_manifest(),
            "resolved_checkout": str(destination.binding.checkout.resolve()),
            "resolved_worktree": str(destination.binding.worktree.resolve()),
        },
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


class _Transport:
    def __init__(self) -> None:
        self.apply_calls = 0
        self.raise_on_apply = False
        self.target_override: Mapping[str, Any] | None = None
        self.readback_target_override: str | None = None
        # Production dispatch always consumes the mandatory pre-entry claim
        # readback and may then consume one worker-proposed effect readback.
        self.readbacks = ["applied", "applied"]
        self.on_apply: Callable[[], None] | None = None
        self.on_readback: Callable[[], None] | None = None

    def validate_target(self, request: IssueDeliveryEffectRequest) -> EffectAuthorityReadback:
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
        if self.on_readback is not None:
            self.on_readback()
        return EffectReadback(
            request_sha256=request.content_sha256,
            outcome=self.readbacks.pop(0),
            evidence={
                "source": "github-authoritative-readback",
                "observed_target_sha256": self.readback_target_override
                or canonical_hash(request.target.model_dump(mode="json")),
            },
        )


def _schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@pytest.fixture
def issue_delivery_pg_store() -> PostgresBuilderOpsStore:
    base = os.getenv("BUILDEROPS_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
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
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


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
        # The operation adapter authenticates to the control plane with its
        # own destination-scoped credential. The protected host credential
        # remains independently revocable, so entry/terminal observations can
        # be durably recorded after an external effect grant disappears.
        (
            "issue-delivery-operation",
            "destination:shared",
            "operation-pg-token",
            ["issue_delivery:execute", "issue_delivery:read", "status:read"],
            "agent",
        ),
    ):
        secret = tmp_path / f"{credential_id}.secret"
        secret.write_text(token, encoding="utf-8")
        secret.chmod(0o600)
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


def test_production_fixture_keeps_operation_and_host_outbox_scopes_separate(
    tmp_path: Path,
) -> None:
    """The host ledger may not silently borrow the operation credential."""

    registry = _production_registry(tmp_path)
    operation = registry.current_credential("issue-delivery-operation")
    host = registry.current_credential("issue-delivery-host")

    assert operation is not None and host is not None
    assert "outbox:write" not in operation.scopes
    assert "outbox:write" in host.scopes
    assert operation.principal == host.principal == "destination:shared"


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
    manifest["approval_id"] = f"approval-pg-{_sha(operation_key.encode('utf-8'))[:24]}"
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
    context_pack["branch_worktree_plan"].update({"branch": branch, "worktree": str(worktree)})
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


class _RegistryCredentialResolver:
    """Host credential adapter backed by the real revocable registry."""

    def __init__(self, registry: CredentialRegistry) -> None:
        self.registry = registry
        self.calls = 0

    def resolve(self, *, repository: str, credential_id: str, rotation_generation: int) -> object:
        credential = self.registry.current_credential(credential_id)
        if (
            credential is None
            or credential.rotation_generation != rotation_generation
            or not credential.may_address(repository)
            or "issue_delivery:execute" not in credential.scopes
        ):
            raise ValueError("registered host credential is unavailable")
        self.calls += 1
        return credential


def _production_worker_receipt() -> dict[str, Any]:
    return {
        "role": "slice_implementer",
        "task": "#5551",
        "skill_loaded": ".codex/skills/issue-to-code/SKILL.md",
        "branch": "codex/5551-protected-destination-adapter-v2",
        "worktree": "approved-worktree",
        "actions": ["implemented", "validated"],
        "ac_verdicts": ["pass"],
        "lifecycle_mutations": [],
        "validation": ["named-production-composition"],
        "owner_doc_result": "updated",
        "residual_risk": "external-github-effects-transport-test-double",
        "final_state": "handoff",
        "next_step": "review",
        "context_cost": {
            "measurement": "proxy",
            "input_tokens": "unknown(runtime-not-exposed)",
            "agent_starts": 1,
            "context_pack_bytes": "unknown(not-recorded)",
            "compactions": "unknown(runtime-not-exposed)",
        },
    }


class _ProductionWorkerTransport:
    """External runner transport that emits live JSON events incrementally."""

    supports_streaming = True

    def __init__(
        self,
        approval: Mapping[str, Any],
        *,
        effect_kind: str,
        registry: CredentialRegistry,
        revoke_before_effect: bool,
        lose_response_after_entry: bool,
    ) -> None:
        self.approval = approval
        self.effect_kind = effect_kind
        self.registry = registry
        self.revoke_before_effect = revoke_before_effect
        self.lose_response_after_entry = lose_response_after_entry
        self.calls = 0
        self.entry_observed_during_call = False
        self.pre_entry_check: Callable[[], None] | None = None

    def _effect_target(self, effect_kind: str | None = None) -> dict[str, Any]:
        effect_kind = effect_kind or self.effect_kind
        issue = self.approval["issue"]
        destination = self.approval["destination"]
        number = int(issue["number"])
        if effect_kind == "claim":
            return {
                "kind": "claim",
                "issue_number": number,
                "issue_node_id": str(issue["node_id"]),
                "expected_state": "open",
                "expected_label": "agent:ready",
            }
        if effect_kind == "publication":
            return {
                "kind": "publication",
                "issue_number": number,
                "branch": str(destination["branch"]),
                "base_ref": str(destination["base_ref"]),
                "base_sha": str(destination["base_sha"]),
                "head_sha": "f" * 40,
                "title_sha256": "1" * 64,
                "body_sha256": "2" * 64,
                "expected_remote_ref_state": "absent",
            }
        if effect_kind == "merge":
            return {
                "kind": "merge",
                "issue_number": number,
                "pr_number": 6000,
                "branch": str(destination["branch"]),
                "base_ref": str(destination["base_ref"]),
                "base_sha": str(destination["base_sha"]),
                "head_sha": "f" * 40,
            }
        return {
            "kind": "closure",
            "issue_number": number,
            "pr_number": 6000,
            "merge_commit_sha": "3" * 40,
            "expected_issue_state": "open",
        }

    def _revoke_destination(self) -> None:
        document = json.loads(self.registry.manifest_path.read_text(encoding="utf-8"))
        for entry in document["credentials"]:
            if entry.get("id") == "issue-delivery-host":
                entry["revoked"] = True
        self.registry.manifest_path.write_text(
            json.dumps(document, sort_keys=True), encoding="utf-8"
        )

    def __call__(
        self,
        command: Sequence[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del command
        self.calls += 1
        if self.pre_entry_check is not None:
            self.pre_entry_check()
        callback = kwargs.get("on_stdout_line")
        if not callable(callback):
            raise AssertionError("streaming production runner callback is missing")
        session_id = f"session-production-{self.effect_kind}"
        started = json.dumps(
            {"type": "thread.started", "thread_id": session_id},
            sort_keys=True,
        )
        callback(started + "\n")
        if self.lose_response_after_entry:
            error = RuntimeError("simulated runner response loss after entry")
            error.session_id = session_id  # type: ignore[attr-defined]
            raise error
        if self.revoke_before_effect:
            self._revoke_destination()
        receipt = _production_worker_receipt()
        receipt["worktree"] = "approved-worktree"
        if self.effect_kind != "claim":
            kinds = ("publication", "merge", "closure") if self.effect_kind == "delivery" else (self.effect_kind,)
            receipt["effect_requests"] = [
                {"effect_kind": kind, "target": self._effect_target(kind)} for kind in kinds
            ]
        completed = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(receipt, sort_keys=True),
                },
            },
            sort_keys=True,
        )
        callback(completed + "\n")
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{started}\n{completed}\n",
            stderr="",
        )


def _production_repository_authority() -> GitHubProtectedRepositoryAuthority:
    """Use the real GitHub authority with only its HTTP transport substituted."""

    document = {
        "repository": REPOSITORY,
        "allowed_effects": [
            "github.issue-delivery.claim.v1",
            "github.issue-delivery.publication.v1",
            "github.issue-delivery.merge.v1",
            "github.issue-delivery.closure.v1",
        ],
        "github_credential": {
            "credential_id": "issue-delivery-host",
            "rotation_generation": 1,
        },
    }
    content = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith(
            "/contents/.builderops/delivery-manifest.json"
        ):
            return httpx.Response(
                200,
                json={
                    "type": "file",
                    "encoding": "base64",
                    "sha": "a" * 40,
                    "content": base64.b64encode(content).decode("ascii"),
                },
            )
        return httpx.Response(404, json={"message": "not found"})

    return GitHubProtectedRepositoryAuthority(
        "executor-pg-token",
        http_client=httpx.Client(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(handler),
        ),
    )


def _production_worker_components(
    *,
    case: Path,
    checkout: Path,
    worktree: Path,
    base_sha: str,
    approval: Mapping[str, Any],
    effect_kind: str,
    registry: CredentialRegistry,
    revoke_before_effect: bool,
    lose_response_after_entry: bool,
) -> tuple[
    ContentOnlyIssueDeliverySessionLauncher,
    _ProductionWorkerTransport,
]:
    """Build the real Linux-systemd/content-only composition for PG tests."""

    model_home = case / "worker-model-home"
    model_home.mkdir()
    model_home.chmod(0o700)
    credential_file = case / "issue-delivery-host.secret"
    credential_file.write_text("executor-pg-token", encoding="utf-8")
    credential_file.chmod(0o600)
    git_directory = Path(
        subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--absolute-git-dir"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    ).resolve()
    common_raw = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common_directory = Path(common_raw)
    if not common_directory.is_absolute():
        common_directory = (worktree / common_directory).resolve()
    executor = ResolvedPrincipal(
        user="builder-executor",
        uid=os.geteuid(),
        group="builder-executor",
        gid=os.getegid(),
    )
    worker = ResolvedPrincipal(
        user="issue-worker",
        uid=2001 if os.geteuid() != 2001 else 2002,
        group="issue-worker",
        gid=2001 if os.getegid() != 2001 else 2002,
    )
    identities = {
        "/usr/bin/systemd-run": ExecutableIdentity(
            path="/usr/bin/systemd-run",
            device=11,
            inode=12,
            sha256="1" * 64,
            mode=0o755,
            owner_uid=0,
            owner_gid=0,
        ),
        "/usr/bin/env": ExecutableIdentity(
            path="/usr/bin/env",
            device=21,
            inode=22,
            sha256="2" * 64,
            mode=0o755,
            owner_uid=0,
            owner_gid=0,
        ),
        "/usr/bin/git": ExecutableIdentity(
            path="/usr/bin/git",
            device=25,
            inode=26,
            sha256="3" * 64,
            mode=0o755,
            owner_uid=0,
            owner_gid=0,
        ),
        "/opt/codex/bin/codex": ExecutableIdentity(
            path="/opt/codex/bin/codex",
            device=31,
            inode=32,
            sha256="4" * 64,
            mode=0o755,
            owner_uid=0,
            owner_gid=0,
        ),
    }
    direct_launcher = CodexIssueSessionLauncher(
        repo_root=worktree,
        precreated_worktree_only=True,
    )
    direct_command = direct_launcher.command(
        approval["context"]["dispatch_plan"]["context_packs"][0]
    )
    direct_command[0] = identities["/opt/codex/bin/codex"].path
    worktree_stat = worktree.stat()
    git_stat = git_directory.stat()
    common_stat = common_directory.stat()
    model_stat = model_home.stat()
    credential_stat = credential_file.stat()
    profile_document: dict[str, Any] = {
        "contract": ISOLATION_PROFILE_CONTRACT,
        "profile_id": "pg-issue-delivery-worker",
        "profile_version": 1,
        "executor": {
            "user": executor.user,
            "uid": executor.uid,
            "group": executor.group,
            "gid": executor.gid,
            "supplementary_gids": [],
        },
        "worker": {
            "user": worker.user,
            "uid": worker.uid,
            "group": worker.group,
            "gid": worker.gid,
            "supplementary_gids": [],
        },
        "worktree": {
            "path": str(worktree),
            "device": worktree_stat.st_dev,
            "inode": worktree_stat.st_ino,
            "git_head": base_sha,
            "git_directory": {
                "path": str(git_directory),
                "device": git_stat.st_dev,
                "inode": git_stat.st_ino,
            },
            "git_common_directory": {
                "path": str(common_directory),
                "device": common_stat.st_dev,
                "inode": common_stat.st_ino,
            },
        },
        "model_auth": {
            "home": str(model_home),
            "reference": "codex-worker-subscription-v1",
            "device": model_stat.st_dev,
            "inode": model_stat.st_ino,
        },
        "protected_github_credential": {
            "path": str(credential_file),
            "device": credential_stat.st_dev,
            "inode": credential_stat.st_ino,
        },
        "systemd_run": identities["/usr/bin/systemd-run"].__dict__,
        "environment_executable": identities["/usr/bin/env"].__dict__,
        "git_executable": identities["/usr/bin/git"].__dict__,
        "codex_executable": identities["/opt/codex/bin/codex"].__dict__,
        "command_sha256": canonical_command_sha256(direct_command),
        "environment": {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/opt/codex/bin:/usr/bin:/bin",
        },
        "isolation_properties_sha256": REQUIRED_SYSTEMD_PROPERTIES_SHA256,
    }
    profile_file = case / "worker-isolation.json"
    profile_file.write_text(
        json.dumps(profile_document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    profile_file.chmod(0o600)
    profile_sha = file_sha256(profile_file)
    approval_file = case / "issue-delivery-approval.json"
    approval_file.write_text(
        json.dumps({"approval": approval}, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    approval_file.chmod(0o600)
    runner = _ProductionWorkerTransport(
        approval,
        effect_kind=effect_kind,
        registry=registry,
        revoke_before_effect=revoke_before_effect,
        lose_response_after_entry=lose_response_after_entry,
    )

    def principal_resolver(user: str, group: str) -> ResolvedPrincipal:
        result = {executor.user: executor, worker.user: worker}.get(user)
        if result is None or result.group != group:
            raise ValueError("production worker principal changed")
        return result

    def executable_resolver(path: str) -> ExecutableIdentity:
        return identities[path]

    def model_home_lstat(path: Path) -> os.stat_result:
        metadata = path.lstat()
        if path == model_home:
            values = list(metadata)
            values[4] = worker.uid
            values[5] = worker.gid
            return os.stat_result(values)
        return metadata

    launcher = ContentOnlyIssueDeliverySessionLauncher(
        repo_root=worktree,
        effect_gate_approval_file=approval_file,
        effect_gate_checkout_root=checkout,
        profile_file=profile_file,
        expected_profile_sha256=profile_sha,
        principal_resolver=principal_resolver,
        current_identity=lambda: (executor.uid, executor.gid),
        credential_probe=lambda _path, _worker, _executor: CredentialProbeResult.DENIED,
        worker_access_probe=lambda _roots,
        _denied,
        _worker,
        _executor: WorkerAccessProbeResult.ADMITTED,
        worktree_head_resolver=lambda _path, _git: base_sha,
        worktree_git_topology_resolver=lambda _path, _git: (
            git_directory,
            common_directory,
        ),
        systemd_preflight=lambda: identities["/usr/bin/systemd-run"],
        executable_resolver=executable_resolver,
        path_lstat_resolver=model_home_lstat,
        runner=runner,
        unit_token=lambda: "0123456789abcdef",
        clock=lambda: "2026-09-16T00:00:00Z",
        platform_name="linux",
    )
    return launcher, runner


@dataclass(frozen=True)
class _ProductionHarness:
    store: PostgresBuilderOpsStore
    registry: CredentialRegistry
    owner: BuilderOpsControlPlaneClient
    client: BuilderOpsControlPlaneClient
    host: BuilderOpsControlPlaneClient
    approval: Mapping[str, Any]
    destination: GitIssueDeliveryDestination
    frozen: FrozenIssueDeliveryDestination
    prepared_worker: PreparedIssueDeliveryWorker
    effect_kind: str
    ledger: BuilderOpsIssueDeliveryEffectLedger
    credentials: _RegistryCredentialResolver
    transport: _Transport
    repository_authority: GitHubProtectedRepositoryAuthority
    worker_transport: _ProductionWorkerTransport
    executor: IssueDeliveryHostExecutor
    checkout: Path
    worktree: Path
    preparation_observed: tuple[bool, ...]

    def completed_request(self) -> IssueDeliveryEffectRequest:
        """Launch the fixture worker once, then derive its actual host binding."""

        try:
            isolation = self.executor.worker_isolation
        except ValueError:
            context = self.approval["context"]["dispatch_plan"]["context_packs"][0]
            self.prepared_worker.launch(context)
            self.executor.bind_completed_worker()
            isolation = self.executor.worker_isolation
        return _request(
            self.approval,
            self.frozen,
            isolation,
            REPO_ROOT / "app/builderops/issue_delivery_effect_executor.py",
            REPO_ROOT / "app/builderops/issue_delivery_worker_isolation.py",
            effect_kind=self.effect_kind,
        )


@pytest.fixture
def issue_delivery_production_harness(
    issue_delivery_pg_store: PostgresBuilderOpsStore,
    tmp_path: Path,
) -> Callable[..., _ProductionHarness]:
    counter = 0

    def build(
        *,
        effect_kind: str = "claim",
        parent: bool = False,
        revoke_before_effect: bool = False,
        lose_response_after_entry: bool = False,
        approval_ttl_seconds: float | None = None,
        issue_body: str | None = None,
        preview_observer: Callable[[Mapping[str, Any]], None] | None = None,
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
        # The approved workflow manifest is a source-commit contract.  The
        # production fixture therefore places every exact approved artifact in
        # its real checkout before creating the pinned base commit; a host
        # live-binding reader may verify those bytes rather than trusting the
        # coordinator checkout or a substituted artifact map.
        for artifact in REQUIRED_WORKFLOW_ARTIFACTS:
            source = REPO_ROOT / artifact
            destination_path = checkout / artifact
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination_path)
        subprocess.run(["git", "-C", str(checkout), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
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
        owner = _production_client(issue_delivery_pg_store, registry, "owner-pg-token")
        client = _production_client(issue_delivery_pg_store, registry, "operation-pg-token")
        host = _production_client(issue_delivery_pg_store, registry, "executor-pg-token")
        manifest = _production_manifest(
            checkout=checkout,
            worktree=worktree,
            base_sha=base_sha,
            operation_key=f"operation-pg-{uuid4().hex}",
        )
        if issue_body is not None:
            criteria = re.search(r"^## Acceptance Criteria\s*\n(.*?)(?=^## |\Z)", issue_body, re.MULTILINE | re.DOTALL)
            assert criteria is not None
            manifest["issue"]["body_hash"] = _sha(issue_body.encode())
            manifest["issue"]["acceptance_criteria_hash"] = _sha(criteria[1].encode())
        if approval_ttl_seconds is not None:
            manifest["expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=approval_ttl_seconds)
            ).isoformat()
        if parent:
            raise ValueError("production parent fixture is not yet required")
        preview = owner.issue_delivery_preview(manifest=manifest)
        if preview_observer is not None:
            preview_observer(preview)
        approval = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])[
            "approval"
        ]
        worktree.parent.mkdir(parents=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "worktree",
                "add",
                "-b",
                str(approval["destination"]["branch"]),
                str(worktree),
                base_sha,
            ],
            check=True,
            capture_output=True,
        )
        destination = GitIssueDeliveryDestination()
        preparation_observed: list[bool] = []
        launcher, worker_transport = _production_worker_components(
            case=case,
            checkout=checkout,
            worktree=worktree,
            base_sha=base_sha,
            approval=approval,
            effect_kind=effect_kind,
            registry=registry,
            revoke_before_effect=revoke_before_effect,
            lose_response_after_entry=lose_response_after_entry,
        )

        def launcher_factory(
            frozen: FrozenIssueDeliveryDestination,
        ) -> ContentOnlyIssueDeliverySessionLauncher:
            preparation_observed.append(
                frozen.binding.worktree.is_dir() and frozen.binding.worktree == worktree
            )
            return launcher

        prepared_worker = PreparedIssueDeliveryWorker.create(
            approval=approval,
            destination=destination,
            launcher_factory=launcher_factory,
        )
        frozen = prepared_worker.frozen_destination
        ledger = BuilderOpsIssueDeliveryEffectLedger(
            host,
            repository=REPOSITORY,
            run_id=str(approval["destination"]["run_id"]),
            approval_id=str(approval["approval_id"]),
            worker_id="issue-delivery-host",
        )
        credentials = _RegistryCredentialResolver(registry)
        transport = _Transport()
        repository_authority = _production_repository_authority()
        executor = IssueDeliveryHostExecutor(
            authority=host,
            ledger=ledger,
            repository_authority=repository_authority,
            credentials=credentials,
            destination=destination,
            frozen_destination=frozen,
            transport=transport,
            prepared_worker=prepared_worker,
            expected_isolation_profile_sha256=launcher.expected_profile_sha256,
        )
        return _ProductionHarness(
            store=issue_delivery_pg_store,
            registry=registry,
            owner=owner,
            client=client,
            host=host,
            approval=approval,
            destination=destination,
            frozen=frozen,
            prepared_worker=prepared_worker,
            effect_kind=effect_kind,
            ledger=ledger,
            credentials=credentials,
            transport=transport,
            repository_authority=repository_authority,
            worker_transport=worker_transport,
            executor=executor,
            checkout=checkout,
            worktree=worktree,
            preparation_observed=tuple(preparation_observed),
        )

    return build
