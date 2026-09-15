"""FCA-ID-A production admission and transaction recovery proofs."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneConflictError,
    ControlPlaneProtocolError,
    ControlPlaneScopeError,
    ControlPlaneUnavailableError,
)
from app.builderops.control_plane.models import AuthorityEnvelope, StateConflict
from app.builderops.control_plane.store import PostgresBuilderOpsStore
from app.builderops.control_plane.service import create_app, issue_delivery_manifest_hash
from app.builderops.control_plane.issue_delivery import canonical_hash
from app.builderops.epic_dispatch import HANDOFF_RECEIPT_SCHEMA

pytestmark = pytest.mark.pg

REPOSITORY = "RasmusTho/agentic-pkm-mvp"


def _dsn() -> str:
    value = os.getenv("BUILDEROPS_DATABASE_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
    if not value:
        pytest.skip("no explicit non-production BuilderOps PostgreSQL DSN configured")
    return value


def _schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@pytest.fixture
def store() -> PostgresBuilderOpsStore:
    base = _dsn()
    try:
        with psycopg.connect(base, connect_timeout=2, autocommit=True) as conn:
            schema = f"builderops_issue_delivery_{uuid4().hex}"
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL unavailable for BuilderOps issue-delivery test: {exc}")
    dsn = _schema_dsn(base, schema)
    value = PostgresBuilderOpsStore(dsn)
    value.initialize()
    try:
        yield value
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def registry(tmp_path: Path) -> CredentialRegistry:
    entries = []
    for credential_id, principal, token, scopes, kind in (
        (
            "owner",
            "owner:human",
            "owner-token",
            ["issue_delivery:approve", "issue_delivery:read", "status:read"],
            "human",
        ),
        ("reader", "destination:reader", "reader-token", ["issue_delivery:read"], "agent"),
        (
            "executor-low",
            "destination:shared",
            "executor-low-token",
            ["issue_delivery:read"],
            "agent",
        ),
        (
            "executor-high",
            "destination:shared",
            "executor-high-token",
            ["issue_delivery:execute"],
            "agent",
        ),
        (
            "executor-other",
            "destination:other",
            "executor-other-token",
            ["issue_delivery:execute"],
            "agent",
        ),
        ("inquiry", "inquiry:agent", "inquiry-token", ["inquiries:approve"], "agent"),
        ("generic", "generic:agent", "generic-token", ["records:write"], "agent"),
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
                "principal_kind": kind,
            }
        )
    manifest = tmp_path / "credentials.json"
    manifest.write_text(json.dumps({"credentials": entries}), encoding="utf-8")
    return CredentialRegistry(manifest)


def _manifest(*, operation_key: str = "operation-5550") -> dict[str, object]:
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
    artifacts = [
        {"path": "app/builderops/cli.py", "sha256": "1" * 64},
        {"path": "app/builderops/epic_dispatch.py", "sha256": "1" * 64},
        {"path": ".codex/agents/slice-implementer.toml", "sha256": "1" * 64},
        {"path": ".codex/skills/issue-to-code/SKILL.md", "sha256": "1" * 64},
        {"path": ".codex/skills/publish-pr/SKILL.md", "sha256": "1" * 64},
        {
            "path": ".codex/skills/verification-and-closure/SKILL.md",
            "sha256": "1" * 64,
        },
    ]
    artifacts.sort(key=lambda item: item["path"])
    dispatch_decision = {
        "id": "dispatch-5550",
        "issue_number": 5550,
        "selected_path": "subagent",
        "selected_for_dispatch": True,
        "dispatch_slot": 1,
        "context_pack_id": "context-5550",
        "budget_class": "medium",
        "candidate_index": 0,
        "title": "task: admit exact one-Issue delivery approval",
        "expected_value": "high",
        "context_cost_estimate": {
            "measurement": "proxy",
            "input_tokens": "unknown(pre-dispatch-runtime-dependent)",
            "agent_starts": 1,
            "context_pack_bytes": 128,
            "compactions": "unknown(pre-dispatch-runtime-dependent)",
        },
        "stop_condition": "stop on authority ambiguity",
        "skip_reason": None,
        "runtime_model_hint": {
            "runtime": "codex",
            "carrier": "codex",
            "selection_intent": "general_delivery",
            "capability": "luna",
            "model_class": "standard",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "xhigh",
            "runtime_difference": "invocation-hint-only",
        },
    }
    dispatch_plan = {
        "schema_version": 2,
        "run_id": "run-5550",
        "requested_max_parallel": 1,
        "max_parallel": 1,
        "parallel_cap_reason": None,
        "runtime_targets": ["codex"],
        "selected_count": 1,
        "selected_helper_slots": 0,
        "decisions": [dispatch_decision],
        "context_packs": [
            {
                "schema_version": 2,
                "context_pack_id": "context-5550",
                "dispatch_slot": 1,
                "issue_contract": {
                    "repository": REPOSITORY,
                    "number": 5550,
                    "title": "task: admit exact one-Issue delivery approval",
                    "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/5550",
                    "scope": "one addressed Ready Issue",
                },
                "runtime": dispatch_decision["runtime_model_hint"],
                "branch_worktree_plan": {
                    "branch": "codex/5550-issue-delivery-approval",
                    "worktree": "/worktrees/issue-5550",
                    "worker_self_claim": True,
                    "coordinator_preclaim": False,
                },
                "skill_loaded": ".codex/skills/issue-to-code/SKILL.md",
                "source_anchors": ["docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: FCA-ID-A"],
                "owner_docs": ["docs/BUILDER_FACTORY_ACCEPTANCE/README.md"],
                "known_constraints": ["one Issue, one writer, no canary route"],
                "validation_ledger": [
                    "tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_production_admission"
                ],
                "publication_closure_expectations": {
                    "publish_skill": ".codex/skills/publish-pr/SKILL.md",
                    "verification_skill": ".codex/skills/verification-and-closure/SKILL.md",
                    "builderops_routing_required": True,
                    "github_lifecycle_truth": "Issues/PRs/CI",
                    "no_project_or_label_mutation_by_dispatch_planner": True,
                    "terminal_delivery_expected": True,
                },
                "coordination": {
                    "routine_worker_to_worker": "prohibited",
                    "discovered_overlap": "reject-whole-explicit-set-before-dispatch",
                    "coordinator_scope": "cross_issue_only",
                    "worker_scope": "one_issue_end_to_end",
                    "issue_local_helper_budget": 0,
                    "issue_local_helper_rationale": None,
                    "sole_writer": "issue_agent",
                },
                "return_schema": HANDOFF_RECEIPT_SCHEMA,
                "context_cost_baseline": {
                    "measurement": "actual",
                    "context_pack_bytes_excluding_baseline": 128,
                },
            }
        ],
        "epic_run_state_update": {
            "dispatch_decisions": [
                {
                    "id": "dispatch-5550",
                    "issue_number": 5550,
                    "selected_path": "subagent",
                    "selected_for_dispatch": True,
                    "runtime_model_hint": dispatch_decision["runtime_model_hint"],
                    "budget_class": "medium",
                    "stop_condition": "stop on authority ambiguity",
                    "skip_reason": None,
                    "context_pack_id": "context-5550",
                }
            ]
        },
        "github_mutations": [],
        "agent_spawns": [],
        "source": "builderops.epic_dispatch.dry_run",
        "run_state_seen": False,
        "scope": {
            "kind": "independent_issue_set",
            "issue_numbers": [5550],
            "parent_closure": "prohibited-without-real-governed-parent",
        },
    }
    return {
        "contract_version": "fca-issue-delivery.v1",
        "operation_type": "deliver_ready_issue",
        "approval_id": "approval-5550",
        "operation_key": operation_key,
        "repository": REPOSITORY,
        "issue": {
            "number": 5550,
            "node_id": "I_kwDOQEip6s8AAAACdXiyQA",
            "title": "task: admit exact one-Issue delivery approval",
            "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/5550",
            "scope": "one addressed Ready Issue",
            "labels": ["agent:ready"],
            "state": "open",
            "body_hash": "a" * 64,
            "acceptance_criteria_hash": "b" * 64,
        },
        "source": {
            "revision": "a5f0e10b666e74c4b8de36a67563a99e30ee801d",
            "refs": ["github:issue:5550", "git:a5f0e10b666e74c4b8de36a67563a99e30ee801d"],
        },
        "context": {
            "pack_id": "context-5550",
            "content_hash": canonical_hash(dispatch_plan["context_packs"][0]),
            "dispatch_plan": dispatch_plan,
            "expected_plan_hash": canonical_hash(dispatch_plan),
        },
        "workflow": {
            "version": "fca-issue-delivery.v1",
            "content_hash": canonical_hash(artifacts),
            "entrypoint": "app/builderops/epic_dispatch.py::dispatch_issue_sessions",
            "launcher": "app/builderops/epic_dispatch.py::CodexIssueSessionLauncher.launch",
            "artifacts": artifacts,
        },
        "destination": {
            "identity": "destination:shared",
            "run_id": "run-5550",
            "host_identity": "host:local",
            "system_identity": "system:builderops",
            "channel": "dev",
            "checkout": "/workspaces/agentic-pkm-mvp",
            "worktree": "/worktrees/issue-5550",
            "branch": "codex/5550-issue-delivery-approval",
            "base_ref": "main",
            "base_sha": "e" * 40,
        },
        "profile": {
            "content_hash": "f" * 64,
            "provider_census_hash": "1" * 64,
            "configuration_digest": "2" * 64,
            "selection_intent": "general_delivery",
            "resolved": {
                "capability": "luna",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "carrier": "codex",
            },
            "verification_profile": {
                "content_hash": "3" * 64,
                "criterion_hashes": {
                    "AC1": "4" * 64,
                    "AC2": "5" * 64,
                    "AC3": "6" * 64,
                    "AC4": "7" * 64,
                },
            },
        },
        "permitted_effects": [
            "repository_worktree",
            "issue_claim",
            "publication",
            "review_merge",
            "closure_reconciliation",
        ],
        "explicit_non_effects": [
            "deployment",
            "credential_provisioning",
            "owner_acceptance",
            "release_stable_movement",
            "host_setup",
            "destructive_database_vault_operations",
            "other_repository_issue_effects",
            "universal_unattended_execution",
        ],
        "parent_evidence": {"kind": "none"},
        "expires_at": expiry,
        "owner_profile": {"kind": "human-owner", "principal": "owner:human"},
    }


def _client(store: PostgresBuilderOpsStore, registry: CredentialRegistry, token: str) -> BuilderOpsControlPlaneClient:
    service = create_app(store=store, credentials=registry)
    return BuilderOpsControlPlaneClient(
        ClientConfig(base_url="http://builderops", token=token),
        http_client=TestClient(service),
        max_retries=0,
    )


def test_issue_approval_production_admission(store, registry, monkeypatch) -> None:
    owner = _client(store, registry, "owner-token")
    reader = _client(store, registry, "reader-token")
    executor_low = _client(store, registry, "executor-low-token")
    executor_high = _client(store, registry, "executor-high-token")
    executor_other = _client(store, registry, "executor-other-token")
    inquiry = _client(store, registry, "inquiry-token")
    generic = _client(store, registry, "generic-token")
    manifest = _manifest()

    unsupported_repository = deepcopy(manifest)
    unsupported_repository["repository"] = "OtherOrg/other-repository"
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=unsupported_repository)

    preview = owner.issue_delivery_preview(manifest=manifest)
    assert preview["state"] == "previewed"
    assert preview["manifest"]["operation_type"] == "deliver_ready_issue"
    assert preview["manifest"]["owner_principal"] == "owner:human"
    assert preview["manifest"]["authority_epoch"] == 1

    held = owner.issue_delivery_start(decision="hold", manifest=preview["manifest"])
    assert held["state"] == "held"
    assert held["effects"] == []
    assert store.authority_counts(REPOSITORY.lower())["records"] == 0

    started = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    assert started["state"] == "approved"
    assert started["approval"]["approval_manifest_hash"] == preview["manifest"]["approval_manifest_hash"]
    assert "fingerprint" not in started["approval"]["permission"]
    assert started["receipt"]["receipt_sequence"] > 0

    replay = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    assert replay["state"] == "approved"
    assert replay["replayed"] is True
    assert replay["receipt"]["receipt_sequence"] == started["receipt"]["receipt_sequence"]

    readback = reader.issue_delivery_readback(repository=REPOSITORY, approval_id="approval-5550")
    assert readback["state"] == "approved"
    assert readback["manifest"]["operation_key"] == "operation-5550"
    assert readback["operation"]["operation_key"] == "operation-5550"
    readback_permission = readback["manifest"]["permission"]
    assert "fingerprint" not in readback_permission
    assert "permission_version" in readback_permission
    owner_credential = registry.current_credential("owner")
    assert owner_credential is not None
    assert owner_credential.fingerprint not in json.dumps(readback, sort_keys=True)

    # A principal-wide grant lookup must not let a read-only credential borrow
    # its sibling's execute grant.  The high-privilege credential is allowed
    # only because the presented credential itself carries that scope.
    with pytest.raises(ControlPlaneScopeError):
        executor_low.issue_delivery_authority(manifest=started["approval"], purpose="execute")
    authority = executor_high.issue_delivery_authority(
        manifest=started["approval"], purpose="execute"
    )
    assert authority["purpose"] == "execute"
    with pytest.raises(ControlPlaneScopeError):
        executor_other.issue_delivery_authority(manifest=started["approval"], purpose="execute")

    # Readback remains available to its separate reader after authority epoch
    # drift so an invalidated approval can still be reconciled.
    current_readiness = store.readiness()
    monkeypatch.setattr(
        store,
        "readiness",
        lambda: {**current_readiness, "authority_epoch": current_readiness["authority_epoch"] + 1},
    )
    stale_readback = reader.issue_delivery_authority(
        manifest=started["approval"], purpose="readback"
    )
    assert stale_readback["purpose"] == "readback"
    assert "fingerprint" not in stale_readback["approval"]["permission"]
    assert owner_credential.fingerprint not in json.dumps(stale_readback, sort_keys=True)
    monkeypatch.setattr(store, "readiness", lambda: current_readiness)

    for field, replacement in (
        ("version", "fca-issue-delivery.v0"),
        ("entrypoint", "app/builderops/cli.py::dispatch_sessions"),
        ("launcher", "app/builderops/epic_dispatch.py::launch"),
    ):
        invalid_workflow = deepcopy(manifest)
        invalid_workflow["workflow"][field] = replacement  # type: ignore[index]
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=invalid_workflow)
    invalid_artifacts = deepcopy(manifest)
    invalid_artifacts["workflow"]["artifacts"][0]["path"] = "app/other_launcher.py"  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_artifacts)
    invalid_artifact_hash = deepcopy(manifest)
    invalid_artifact_hash["workflow"]["artifacts"][0]["sha256"] = "2" * 64  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_artifact_hash)

    invalid_plan = deepcopy(manifest)
    invalid_plan["context"].pop("expected_plan_hash")  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_plan)
    invalid_context_hash = deepcopy(manifest)
    invalid_context_hash["context"]["content_hash"] = "c" * 64  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_context_hash)
    invalid_plan = deepcopy(manifest)
    invalid_plan["context"]["dispatch_plan"]["selected_count"] = 2  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_plan)
    for missing_plan_field in ("scope", "run_state_seen"):
        incomplete_plan = deepcopy(manifest)
        incomplete_plan["context"]["dispatch_plan"].pop(missing_plan_field)  # type: ignore[union-attr]
        incomplete_plan["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
            incomplete_plan["context"]["dispatch_plan"]  # type: ignore[union-attr]
        )
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=incomplete_plan)
    for missing_context_field in ("validation_ledger", "publication_closure_expectations"):
        incomplete_context = deepcopy(manifest)
        incomplete_context["context"]["dispatch_plan"]["context_packs"][0].pop(  # type: ignore[union-attr]
            missing_context_field
        )
        incomplete_context["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
            incomplete_context["context"]["dispatch_plan"]  # type: ignore[union-attr]
        )
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=incomplete_context)
    for context_issue_field, replacement in (
        ("repository", "OtherOrg/other-repository"),
        ("title", "another Issue"),
        ("url", "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1"),
        ("scope", "another scope"),
    ):
        mismatched_context_issue = deepcopy(manifest)
        mismatched_context_issue["context"]["dispatch_plan"]["context_packs"][0]["issue_contract"][  # type: ignore[union-attr]
            context_issue_field
        ] = replacement
        mismatched_context_issue["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
            mismatched_context_issue["context"]["dispatch_plan"]  # type: ignore[union-attr]
        )
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=mismatched_context_issue)
    invalid_issue_url = deepcopy(manifest)
    invalid_issue_url["issue"]["url"] = "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1"  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_issue_url)
    missing_ready_label = deepcopy(manifest)
    missing_ready_label["issue"]["labels"] = ["type:task"]  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=missing_ready_label)
    invalid_plan = deepcopy(manifest)
    invalid_plan["context"]["dispatch_plan"]["run_id"] = "run/5550"  # type: ignore[union-attr]
    invalid_plan["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        invalid_plan["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_plan)
    for destination_field, replacement in (
        ("run_id", "other-run-5550"),
        ("branch", "codex/other-issue"),
        ("worktree", "/worktrees/other-issue"),
    ):
        invalid_destination = deepcopy(manifest)
        invalid_destination["destination"][destination_field] = replacement  # type: ignore[union-attr]
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=invalid_destination)
    invalid_runtime = deepcopy(manifest)
    invalid_runtime["context"]["dispatch_plan"]["context_packs"][0]["runtime"]["model"] = "gpt-5.6-sol"  # type: ignore[union-attr]
    invalid_runtime["context"]["dispatch_plan"]["decisions"][0]["runtime_model_hint"]["model"] = "gpt-5.6-sol"  # type: ignore[union-attr]
    invalid_runtime["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        invalid_runtime["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_runtime)
    invalid_census_target = deepcopy(manifest)
    invalid_census_target["context"]["dispatch_plan"]["context_packs"][0]["runtime"]["model"] = "gpt-5.6-sol"  # type: ignore[union-attr]
    invalid_census_target["context"]["dispatch_plan"]["decisions"][0]["runtime_model_hint"]["model"] = "gpt-5.6-sol"  # type: ignore[union-attr]
    invalid_census_target["profile"]["resolved"]["model"] = "gpt-5.6-sol"  # type: ignore[union-attr]
    invalid_census_target["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        invalid_census_target["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_census_target)
    missing_owner_profile = deepcopy(manifest)
    missing_owner_profile["owner_profile"] = {"kind": "human-owner"}
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=missing_owner_profile)
    invalid_profile_target = deepcopy(manifest)
    invalid_profile_target["profile"]["resolved"]["reasoning_effort"] = "high"  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_profile_target)
    invalid_plan = deepcopy(manifest)
    invalid_plan["context"]["dispatch_plan"].pop("epic_run_state_update")  # type: ignore[union-attr]
    invalid_plan["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        invalid_plan["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_plan)
    invalid_plan = deepcopy(manifest)
    invalid_plan["context"]["dispatch_plan"]["decisions"][0]["execution_routing"] = {  # type: ignore[union-attr]
        "mode": "canary"
    }
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_plan)
    invalid_plan = deepcopy(manifest)
    invalid_plan["context"]["dispatch_plan"]["decisions"][0]["selected_path"] = "inline"  # type: ignore[union-attr]
    invalid_plan["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        invalid_plan["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_plan)

    for field in ("provider_census_hash", "configuration_digest", "selection_intent"):
        invalid_profile = deepcopy(manifest)
        invalid_profile["profile"].pop(field)  # type: ignore[union-attr]
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=invalid_profile)
    invalid_profile = deepcopy(manifest)
    invalid_profile["profile"]["resolved"].pop("carrier")  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_profile)
    invalid_profile = deepcopy(manifest)
    invalid_profile["profile"]["resolved"]["carrier"] = "claude"  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_profile)
    invalid_profile = deepcopy(manifest)
    invalid_profile["profile"]["resolved"]["capability"] = "terra"  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_profile)
    invalid_profile = deepcopy(manifest)
    invalid_profile["profile"]["selection_intent"] = "coordination"  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_profile)
    invalid_profile = deepcopy(manifest)
    invalid_profile["profile"]["verification_profile"]["criterion_hashes"] = {}  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_profile)

    shared_checkout = deepcopy(manifest)
    shared_checkout["destination"]["worktree"] = shared_checkout["destination"]["checkout"]  # type: ignore[union-attr]
    shared_checkout["context"]["dispatch_plan"]["context_packs"][0]["branch_worktree_plan"]["worktree"] = shared_checkout["destination"]["checkout"]  # type: ignore[union-attr]
    shared_checkout["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        shared_checkout["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=shared_checkout)
    base_branch = deepcopy(manifest)
    base_branch["destination"]["branch"] = base_branch["destination"]["base_ref"]  # type: ignore[union-attr]
    base_branch["context"]["dispatch_plan"]["context_packs"][0]["branch_worktree_plan"]["branch"] = base_branch["destination"]["base_ref"]  # type: ignore[union-attr]
    base_branch["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        base_branch["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=base_branch)
    normalized_shared_checkout = deepcopy(manifest)
    normalized_shared_checkout["destination"]["worktree"] = "/workspaces/agentic-pkm-mvp/./"  # type: ignore[union-attr]
    normalized_shared_checkout["destination"]["checkout"] = "/workspaces/agentic-pkm-mvp"  # type: ignore[union-attr]
    normalized_shared_checkout["context"]["dispatch_plan"]["context_packs"][0]["branch_worktree_plan"]["worktree"] = "/workspaces/agentic-pkm-mvp/./"  # type: ignore[union-attr]
    normalized_shared_checkout["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        normalized_shared_checkout["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=normalized_shared_checkout)

    for revision in ("main", "main:a5f0e10b666e74c4b8de36a67563a99e30ee801d", "HEAD"):
        invalid_source = deepcopy(manifest)
        invalid_source["source"]["revision"] = revision  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_source)
    mismatched_source_ref = deepcopy(manifest)
    mismatched_source_ref["source"]["refs"][1] = "git:" + "b" * 40  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=mismatched_source_ref)

    for non_effect in (
        "release_stable_movement",
        "host_setup",
        "destructive_database_vault_operations",
        "other_repository_issue_effects",
        "universal_unattended_execution",
    ):
        incomplete_non_effects = deepcopy(manifest)
        incomplete_non_effects["explicit_non_effects"].remove(non_effect)  # type: ignore[union-attr]
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=incomplete_non_effects)

    foreign_parent = deepcopy(manifest)
    foreign_parent["parent_evidence"] = {
        "kind": "issue",
        "repository": "OtherOrg/other-repository",
        "number": 5399,
        "node_id": "I_foreign_parent",
        "relationship": {
            "kind": "parent",
            "child_issue_number": 5550,
            "authenticated": True,
        },
        "contract_version": "fca-parent.v1",
        "contract_hash": "8" * 64,
        "write_permission": {
            "scope": "parent_evidence:write",
            "effects": ["pr_receipt_comments", "child_generated_ledger_writeback"],
        },
    }
    with pytest.raises((ControlPlaneProtocolError, ControlPlaneScopeError)):
        owner.issue_delivery_preview(manifest=foreign_parent)

    incomplete_parent = deepcopy(manifest)
    incomplete_parent["parent_evidence"] = {"kind": "issue"}
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=incomplete_parent)
    foreign_parent_start = deepcopy(preview["manifest"])
    foreign_parent_start["parent_evidence"] = foreign_parent["parent_evidence"]
    foreign_parent_start["approval_manifest_hash"] = issue_delivery_manifest_hash(
        foreign_parent_start
    )
    with pytest.raises(ControlPlaneScopeError):
        owner.issue_delivery_start(decision="start", manifest=foreign_parent_start)
    foreign_owner_profile_start = deepcopy(preview["manifest"])
    foreign_owner_profile_start["owner_profile"]["principal"] = "owner:other"  # type: ignore[union-attr]
    foreign_owner_profile_start["approval_manifest_hash"] = issue_delivery_manifest_hash(
        foreign_owner_profile_start
    )
    with pytest.raises(ControlPlaneScopeError):
        owner.issue_delivery_start(decision="start", manifest=foreign_owner_profile_start)

    slash_bound_id = deepcopy(manifest)
    slash_bound_id["approval_id"] = "team/approval-1"
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=slash_bound_id)

    for client in (inquiry, generic):
        with pytest.raises(ControlPlaneScopeError):
            client.issue_delivery_preview(manifest=manifest)
    with pytest.raises(ControlPlaneScopeError):
        generic.commit_record(
            envelope={
                "repository": REPOSITORY,
                "scope": "generic-record",
                "stack": "builderops-control-plane",
                "source_refs": ["test:issue-5550"],
            },
            record_id="generic-record:issue-delivery-prefix",
            record_type="BuilderOpsReceipt",
            state="active",
            payload={"kind": "generic"},
            idempotency_key="issue-delivery:operation-prefix-reservation",
        )
    with pytest.raises(StateConflict):
        store.claim_lease(
            envelope=AuthorityEnvelope(
                repository=REPOSITORY,
                scope="generic-lease",
                stack="builderops-control-plane",
                actor="generic:agent",
                source_refs=("test:issue-5550",),
            ),
            resource_id="generic-resource",
            holder="generic:agent",
            idempotency_key="issue-delivery:lease-prefix-reservation",
            request={},
        )

    changed_source = dict(preview["manifest"])
    changed_source["source"] = {**changed_source["source"], "revision": "main:changed"}
    with pytest.raises(ControlPlaneConflictError):
        owner.issue_delivery_start(decision="start", manifest=changed_source)

    changed_key = dict(preview["manifest"])
    changed_key["operation_key"] = "operation-5550-new"
    with pytest.raises(ControlPlaneConflictError):
        owner.issue_delivery_start(decision="start", manifest=changed_key)


def test_issue_approval_transaction_recovery(store, registry, monkeypatch) -> None:
    owner = _client(store, registry, "owner-token")
    preview = owner.issue_delivery_preview(manifest=_manifest(operation_key="operation-recovery"))
    original = store.commit_record

    def fail_before_commit(**kwargs):  # type: ignore[no-untyped-def]
        return original(**kwargs, fault_at="after_authority_object")

    monkeypatch.setattr(store, "commit_record", fail_before_commit)
    with pytest.raises(ControlPlaneUnavailableError):
        owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    with pytest.raises(KeyError):
        store.get_record(REPOSITORY, "issue-delivery-approval:approval-5550")

    monkeypatch.setattr(store, "commit_record", original)
    recovered = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    assert recovered["state"] == "approved"
    assert recovered["replayed"] is False
    assert store.get_record(REPOSITORY, "issue-delivery-approval:approval-5550")["state"] == "approved"


def test_issue_approval_concurrent_identical_start_replays_winner(
    store, registry, monkeypatch
) -> None:
    owner_a = _client(store, registry, "owner-token")
    owner_b = _client(store, registry, "owner-token")
    preview = owner_a.issue_delivery_preview(
        manifest=_manifest(operation_key="operation-concurrent")
    )
    barrier = threading.Barrier(2)
    original = store.commit_record

    def synchronized_commit(**kwargs):  # type: ignore[no-untyped-def]
        barrier.wait(timeout=10)
        return original(**kwargs)

    monkeypatch.setattr(store, "commit_record", synchronized_commit)
    def start(client: BuilderOpsControlPlaneClient) -> dict[str, object]:
        return client.issue_delivery_start(decision="start", manifest=preview["manifest"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(start, (owner_a, owner_b)))

    assert sorted(item["replayed"] for item in outcomes) == [False, True]
    assert len({item["receipt"]["receipt_sequence"] for item in outcomes}) == 1


def test_issue_approval_concurrent_competing_start_preserves_conflict(
    store, registry, monkeypatch
) -> None:
    owner_a = _client(store, registry, "owner-token")
    owner_b = _client(store, registry, "owner-token")
    preview_a = owner_a.issue_delivery_preview(
        manifest=_manifest(operation_key="operation-competing-race")
    )
    manifest_b = _manifest(operation_key="operation-competing-race")
    manifest_b["approval_id"] = "approval-5550-other"
    preview_b = owner_b.issue_delivery_preview(manifest=manifest_b)
    barrier = threading.Barrier(2)
    original = store.commit_record

    def synchronized_commit(**kwargs):  # type: ignore[no-untyped-def]
        barrier.wait(timeout=10)
        return original(**kwargs)

    monkeypatch.setattr(store, "commit_record", synchronized_commit)

    def start(args):  # type: ignore[no-untyped-def]
        client, manifest = args
        try:
            return "approved", client.issue_delivery_start(decision="start", manifest=manifest)
        except ControlPlaneConflictError:
            return "conflict", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                start,
                (
                    (owner_a, preview_a["manifest"]),
                    (owner_b, preview_b["manifest"]),
                ),
            )
        )

    assert sorted(item[0] for item in outcomes) == ["approved", "conflict"]
