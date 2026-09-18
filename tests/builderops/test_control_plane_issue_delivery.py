"""FCA-ID-A production admission and transaction recovery proofs."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from typing import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane import service as control_plane_service
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
from app.builderops.control_plane.issue_delivery import (
    canonical_hash,
    normalize_manifest as normalize_issue_delivery_manifest,
)
from app.builderops.epic_dispatch import CodexIssueSessionLauncher, HANDOFF_RECEIPT_SCHEMA
from app.builderops.issue_delivery_operation import (
    IssueDeliveryOperationAdapter,
    IssueDeliveryOperationRefused,
)

pytestmark = pytest.mark.pg

REPOSITORY = "RasmusTho/agentic-pkm-mvp"


def _bifrost_manifest():
    """The public constituent identity, with an independently tracked hub Issue."""
    value = _manifest()
    value["contract_version"] = "fca-issue-delivery.v2"
    value["repository"] = "rasmustho/bifrost"
    value["destination"]["base_sha"] = value["source"]["revision"]
    value["issue"]["repository"] = REPOSITORY.lower()
    value["workflow"].update(
        version="fca-issue-delivery.v2", repository=REPOSITORY.lower(),
        source_revision="b" * 40,
    )
    value["target_policies"] = {}
    for repository, effects in (
        ("rasmustho/bifrost", ["publication", "merge"]),
        (REPOSITORY.lower(), ["claim", "closure"]),
    ):
        value["target_policies"][repository] = {
            "repository": repository,
            "base_sha": value["destination"]["base_sha"] if "bifrost" in repository else "b" * 40,
            "blob_sha": "c" * 40,
            "content_sha256": "d" * 64,
            "credential_id": "consumer-writer" if "bifrost" in repository else "hub-writer",
            "rotation_generation": 1,
            "allowed_effects": [f"github.issue-delivery.{effect}.v1" for effect in effects],
            "documentation_paths": ["docs/guide.md"] if "bifrost" in repository else [],
            "verification_profile": deepcopy(value["profile"]["verification_profile"]) if "bifrost" in repository else None,
            "required_checks": ["documentation"] if "bifrost" in repository else [],
        }
    pack = value["context"]["dispatch_plan"]["context_packs"][0]
    pack["delivery_sources"] = {
        "contract_version": value["contract_version"],
        "repository": value["repository"],
        "source_revision": value["source"]["revision"],
        "issue_repository": value["issue"]["repository"],
        "workflow_repository": value["workflow"]["repository"],
        "workflow_source_revision": value["workflow"]["source_revision"],
    }
    value["context"]["content_hash"] = canonical_hash(pack)
    value["context"]["expected_plan_hash"] = canonical_hash(value["context"]["dispatch_plan"])
    return value


def test_issue_delivery_v1_compatibility_and_v2_scope() -> None:
    from app.builderops.control_plane.issue_delivery import IssueDeliveryContractError

    legacy = _manifest()
    legacy["expires_at"] = "2099-01-01T00:00:00+00:00"
    assert canonical_hash(normalize_issue_delivery_manifest(legacy)) == (
        "114f9b5bbaa7baea1d10834031b29535336e97d772a1f7c103b382d98b0c43ec"
    )
    v2 = _bifrost_manifest()
    normalized = normalize_issue_delivery_manifest(v2)
    assert normalized["issue"]["repository"] == REPOSITORY.lower()
    assert normalized["workflow"]["source_revision"] != normalized["source"]["revision"]
    assert normalize_issue_delivery_manifest(normalized) == normalized
    for field, bad in (("repository", "other/third"), ("repository", REPOSITORY),
                       ("contract_version", "fca-issue-delivery.v3"),
                       ("target_policies", {})):
        changed = deepcopy(v2)
        changed[field] = bad
        with pytest.raises(IssueDeliveryContractError):
            normalize_issue_delivery_manifest(changed)
    legacy["repository"] = "rasmustho/bifrost"
    with pytest.raises(IssueDeliveryContractError):
        normalize_issue_delivery_manifest(legacy)


def test_host_candidate_versions_preserve_v1_v2_history(issue_delivery_production_harness):
    from app.builderops.control_plane.issue_delivery import delivery_source_pair, tracking_repository
    old = _manifest()
    old["expires_at"] = "2099-01-01T00:00:00+00:00"
    assert canonical_hash(normalize_issue_delivery_manifest(old)) == "114f9b5bbaa7baea1d10834031b29535336e97d772a1f7c103b382d98b0c43ec"
    v2 = _bifrost_manifest()
    v2["expires_at"] = "2099-01-01T00:00:00+00:00"
    # Golden read independently from the unchanged 433bef18 source checkout.
    assert canonical_hash(normalize_issue_delivery_manifest(v2)) == "5f74553cf63984bbade030652765fa8952395f819549f48de49457362d957e1d"
    assert normalize_issue_delivery_manifest(normalize_issue_delivery_manifest(v2)) == normalize_issue_delivery_manifest(v2)
    harness = issue_delivery_production_harness(bifrost=True, host_candidate=True)
    approved = harness.approval
    assert delivery_source_pair(approved)["contract_version"] == "fca-issue-delivery.v3"
    assert tracking_repository(approved) == REPOSITORY.lower()
    assert set(approved["target_policies"]) == {"rasmustho/bifrost", REPOSITORY.lower()}
    from app.builderops.control_plane.issue_delivery import strip_server_fields, IssueDeliveryContractError
    for mutation in ("third", "old_pins", "v2_policy"):
        changed = deepcopy(strip_server_fields(approved))
        if mutation == "third":
            changed["repository"] = "other/third"
        elif mutation == "old_pins":
            changed["workflow"] = v2["workflow"]
        else:
            changed["target_policies"]["rasmustho/bifrost"]["allowed_effects"].remove("git.issue-delivery.candidate-prepare.v1")
        with pytest.raises(IssueDeliveryContractError):
            normalize_issue_delivery_manifest(changed)
    replay = harness.owner.issue_delivery_start(decision="start", manifest=approved)
    assert replay["replayed"] and replay["approval"] == approved


def test_v3_live_start_refuses_unqualified_continuation(issue_delivery_production_harness, monkeypatch):
    from app.builderops import issue_delivery_effect_executor as module
    from app.builderops.control_plane.client import ControlPlaneClientError
    from app.builderops.control_plane.issue_delivery import strip_server_fields
    harness = issue_delivery_production_harness(bifrost=True, host_candidate=True)
    # The disposable composition passed real gates; removing the installed host binding
    # must make those same preview/Start gates refuse, including exact Start replay.
    monkeypatch.setattr(module, "_HOST_ISSUE_DELIVERY_EXECUTOR_RUNTIME", None)
    with pytest.raises(ControlPlaneClientError):
        harness.owner.issue_delivery_preview(manifest=strip_server_fields(harness.approval))
    with pytest.raises(ControlPlaneClientError):
        harness.owner.issue_delivery_start(decision="start", manifest=harness.approval)
    assert harness.worker_transport.calls == harness.transport.apply_calls == 0


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
            ["issue_delivery:read", "status:read"],
            "agent",
        ),
        (
            "executor-high",
            "destination:shared",
            "executor-high-token",
            ["issue_delivery:execute", "status:read"],
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
        {
            "path": "app/builderops/issue_delivery_effect_executor.py",
            "sha256": "1" * 64,
        },
        {
            "path": "app/builderops/issue_delivery_worker_isolation.py",
            "sha256": "1" * 64,
        },
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
    verification_profile = {
        "content_hash": canonical_hash(
            {
                "AC1": "4" * 64,
                "AC2": "5" * 64,
                "AC3": "6" * 64,
                "AC4": "7" * 64,
            }
        ),
        "criterion_hashes": {
            "AC1": "4" * 64,
            "AC2": "5" * 64,
            "AC3": "6" * 64,
            "AC4": "7" * 64,
        },
    }
    profile = {
        "content_hash": "",
        "provider_census_hash": "1" * 64,
        "configuration_digest": "2" * 64,
        "selection_intent": "general_delivery",
        "resolved": {
            "capability": "luna",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "xhigh",
            "carrier": "codex",
        },
        "verification_profile": verification_profile,
    }
    profile["content_hash"] = canonical_hash(
        {key: value for key, value in profile.items() if key != "content_hash"}
    )
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
        "profile": profile,
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


def _operation_live_binding(approval: Mapping[str, object]) -> dict[str, object]:
    destination = approval["destination"]
    source = approval["source"]
    workflow = approval["workflow"]
    issue = approval["issue"]
    assert isinstance(destination, dict)
    assert isinstance(source, dict)
    assert isinstance(workflow, dict)
    assert isinstance(issue, dict)
    return {
        "checkout": str(destination["resolved_checkout"]),
        "worktree": str(destination["resolved_worktree"]),
        "branch": str(destination["branch"]),
        "source_revision": str(source["revision"]),
        "base_sha": str(destination["base_sha"]),
        "workflow_hash": str(workflow["content_hash"]),
        "workflow_artifacts": sorted(
            [
                {"path": str(item["path"]), "sha256": str(item["sha256"])}
                for item in workflow["artifacts"]
            ],
            key=lambda item: item["path"],
        ),
        "current_issue": {
            "number": issue["number"],
            "node_id": issue["node_id"],
            "state": "open",
            "body_hash": issue["body_hash"],
            "acceptance_criteria_hash": issue["acceptance_criteria_hash"],
        },
        "current_source": {"revision": source["revision"], "refs": list(source["refs"])},
        "current_profile": dict(approval["profile"]),
    }


def test_issue_operation_observations_require_execute_but_survive_invalidation(
    store: PostgresBuilderOpsStore,
    registry: CredentialRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_errors: list[Exception] = []
    original_error = control_plane_service._control_plane_error

    def observe_error(exc: Exception):
        # Preserve the real HTTP mapping while checking the precise refusal reason.
        service_errors.append(exc)
        return original_error(exc)

    monkeypatch.setattr(control_plane_service, "_control_plane_error", observe_error)
    owner = _client(store, registry, "owner-token")
    reader = _client(store, registry, "executor-low-token")
    writer = _client(store, registry, "executor-high-token")
    preview = owner.issue_delivery_preview(
        manifest=_manifest(operation_key="operation-observation-write-scope")
    )
    approval = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])["approval"]
    adapter = IssueDeliveryOperationAdapter(
        approval,
        client=writer,
        live_binding_reader=_operation_live_binding,
    )
    immutable_binding = adapter._live_binding(include_current_facts=False)
    monkeypatch.setattr(
        adapter,
        "_live_binding",
        lambda *, include_current_facts=True, post_merge_observation=False: (
            _operation_live_binding(approval)
            if include_current_facts
            else immutable_binding
        ),
    )
    reservation = adapter.reserve()
    adapter.record_attempt()
    entry = adapter.record_entry(session_id="session-observation-write-scope")

    terminal_body = {
        "attempt_receipt_hash": entry["payload"]["attempt_receipt_hash"],
        "destination_resource_key": entry["payload"]["destination_resource_key"],
        "entry_receipt_hash": entry["payload"]["receipt_hash"],
        "session_id": "session-observation-write-scope",
        "worker_receipt": {"final_state": "handoff"},
        "observed_at": "2026-09-16T00:00:00+00:00",
    }
    with pytest.raises(
        IssueDeliveryOperationRefused,
        match="destination receipt was not durably committed",
    ) as forged_receipt:
        adapter._write(
            "terminal",
            "terminal",
            {
                **terminal_body,
                "worker_receipt": {
                    "final_state": "handoff",
                    "diagnostics": {"effect_receipts": [{"outcome": "forged"}]},
                },
                "host_effect_refs": [],
            },
        )
    assert isinstance(forged_receipt.value.__cause__, ControlPlaneConflictError)
    assert isinstance(service_errors[-1], StateConflict)
    assert "worker receipt must not supply protected host effect fields" in str(service_errors[-1])
    assert adapter._read("terminal") is None
    with pytest.raises(
        IssueDeliveryOperationRefused,
        match="destination receipt was not durably committed",
    ) as unavailable_reference:
        adapter._write(
            "terminal",
            "terminal",
            {
                **terminal_body,
                "host_effect_refs": [
                    {
                        "operation_key": "0" * 64,
                        "request_sha256": "1" * 64,
                        "effect_slot_sha256": "2" * 64,
                    }
                ],
            },
        )
    assert isinstance(unavailable_reference.value.__cause__, ControlPlaneConflictError)
    assert isinstance(service_errors[-1], StateConflict)
    assert "reference is unavailable" in str(service_errors[-1])
    assert adapter._read("terminal") is None

    monkeypatch.setattr(store, "outbox_status", lambda *_args: "succeeded")
    monkeypatch.setattr(
        store,
        "outbox_intent",
        lambda *_args: {
            "task_id": "issue-delivery-effect:" + "2" * 64,
            "effect_type": "github.issue-delivery.claim.v1",
            "payload": {
                "contract": "builderops.issue-delivery-effect.v1",
                "request_sha256": "1" * 64,
                "effect_slot_sha256": "2" * 64,
                "approval_id": "foreign-approval",
                "approved_operation_key": approval["operation_key"],
                "repository": approval["repository"],
                "issue_number": approval["issue"]["number"],
                "run_id": approval["destination"]["run_id"],
                "effect_kind": "claim",
            },
        },
    )
    with pytest.raises(
        IssueDeliveryOperationRefused,
        match="destination receipt was not durably committed",
    ) as foreign_reference:
        adapter._write(
            "terminal",
            "terminal",
            {
                **terminal_body,
                "host_effect_refs": [
                    {
                        "operation_key": "0" * 64,
                        "request_sha256": "1" * 64,
                        "effect_slot_sha256": "2" * 64,
                    }
                ],
            },
        )
    assert isinstance(foreign_reference.value.__cause__, ControlPlaneConflictError)
    assert isinstance(service_errors[-1], StateConflict)
    assert "reference is foreign or changed" in str(service_errors[-1])
    assert adapter._read("terminal") is None
    monkeypatch.undo()
    monkeypatch.setattr(control_plane_service, "_control_plane_error", observe_error)

    assert reader.authority_epoch == writer.authority_epoch
    with pytest.raises(ControlPlaneScopeError):
        reader.issue_delivery_operation_record(
            envelope={
                "repository": approval["repository"],
                "scope": "issue-delivery-operation",
                "stack": "builderops-control-plane",
                "source_refs": ["test:read-only-write-refusal"],
            },
            record_id=f"issue-delivery-reservation:{approval['operation_key']}",
            state="reserved",
            payload=reservation["payload"],
            idempotency_key=f"issue-delivery-operation:reservation:{approval['operation_key']}",
            operation_key=approval["operation_key"],
            approval_id=approval["approval_id"],
            approval_manifest_hash=approval["approval_manifest_hash"],
        )

    original_current_credential = registry.current_credential
    monkeypatch.setattr(
        registry,
        "current_credential",
        lambda credential_id: (
            None
            if credential_id == "owner"
            else original_current_credential(credential_id)
        ),
    )
    terminal = adapter.record_terminal(
        session_id="session-observation-write-scope",
        worker_receipt={"final_state": "handoff"},
    )
    assert entry["state"] == "active"
    assert terminal["state"] == "terminal"
    assert terminal["payload"]["host_effect_refs"] == []
    assert reader.issue_delivery_operation_record_read(
        repository=str(approval["repository"]),
        record_id=f"issue-delivery-terminal:{approval['operation_key']}",
    )["state"] == "terminal"
    with pytest.raises(ControlPlaneConflictError, match="StateConflict"):
        writer.issue_delivery_operation_record(
            envelope={
                "repository": approval["repository"],
                "scope": "issue-delivery-operation",
                "stack": "builderops-control-plane",
                "source_refs": ["test:execute-reservation-refusal"],
            },
            record_id=f"issue-delivery-reservation:{approval['operation_key']}",
            state="reserved",
            payload=reservation["payload"],
            idempotency_key=f"issue-delivery-operation:reservation:{approval['operation_key']}",
            operation_key=approval["operation_key"],
            approval_id=approval["approval_id"],
            approval_manifest_hash=approval["approval_manifest_hash"],
        )
    assert isinstance(service_errors[-1], StateConflict)
    assert "owner is unavailable" in str(service_errors[-1])


@pytest.mark.parametrize("boundary", ["preview", "start", "execute", "withdrawal"])
def test_bifrost_presented_owner_cannot_borrow_hub_scope(
    issue_delivery_production_harness, tmp_path, boundary,
) -> None:
    from app.builderops.control_plane.issue_delivery import (
        approval_digest, receipt_ref, record_id, strip_server_fields,
    )

    harness = issue_delivery_production_harness(bifrost=True)
    raw = strip_server_fields(harness.approval)
    raw.pop("contract", None)
    preview = harness.owner.issue_delivery_preview(manifest=raw)["manifest"]
    # Positive control: this actual bearer holds both repositories and the
    # service admits/replays it before the repository grant is withdrawn.
    assert harness.owner.issue_delivery_start(decision="start", manifest=harness.approval)["replayed"]
    original = json.loads(harness.registry.manifest_path.read_text())
    document = deepcopy(original)
    owner = next(row for row in document["credentials"] if row["id"] == "owner")
    sibling = deepcopy(owner)
    secret = tmp_path / "separate-hub-owner.secret"
    secret.write_text("separate-hub-owner-token", encoding="utf-8")
    secret.chmod(0o600)
    sibling.update(id="hub-owner", secret_ref="host-secret:hub-owner",
                   secret_file=str(secret), repositories=[REPOSITORY.lower()])
    owner["repositories"] = ["rasmustho/bifrost"]
    document["credentials"].append(sibling)
    harness.registry.manifest_path.write_text(json.dumps(document))
    current = harness.registry.current_credential("owner")
    assert current is not None and not current.may_address(REPOSITORY)
    assert harness.registry.has_issue_delivery_approval_grant(REPOSITORY, current.principal)

    if boundary == "preview":
        with pytest.raises(ControlPlaneScopeError):
            harness.owner.issue_delivery_preview(manifest=raw)
    elif boundary == "withdrawal":
        with pytest.raises(ControlPlaneConflictError):
            harness.host.issue_delivery_authority(manifest=harness.approval, purpose="execute")
        historical = harness.host.issue_delivery_authority(manifest=harness.approval, purpose="readback")
        assert historical["approval"] == harness.approval
    else:
        # Reproduce public metadata emitted by the formerly vulnerable preview,
        # not an unrelated hash/rotation mismatch. No service verdict is mocked.
        permission = preview["permission"]
        permission["repositories"] = sorted(current.repositories)
        permission.pop("permission_version")
        permission["permission_version"] = canonical_hash(permission)
        if boundary == "start":
            preview["approval_id"] += "-split"
            preview["operation_key"] += "-split"
            preview["approval_receipt_ref"] = receipt_ref(preview["repository"], preview["approval_id"])
            preview["approval_manifest_hash"] = issue_delivery_manifest_hash(preview)
            with pytest.raises(ControlPlaneScopeError):
                harness.owner.issue_delivery_start(decision="start", manifest=preview)
            with pytest.raises(KeyError):
                harness.store.get_record(preview["repository"], record_id(preview["approval_id"]))
        else:
            # Retained database state created by the former vulnerable Start.
            # Inject only persisted input; execute/readback use the real service.
            retained = {**harness.approval, "permission": permission}
            retained["approval_manifest_hash"] = issue_delivery_manifest_hash(retained)
            retained["approval_digest"] = approval_digest(retained)
            with psycopg.connect(harness.store.dsn) as conn:
                conn.execute(
                    "UPDATE builderops_records SET payload = %s::jsonb "
                    "WHERE repository = %s AND record_id = %s",
                    (json.dumps(retained), retained["repository"], record_id(retained["approval_id"])),
                )
            historical = harness.host.issue_delivery_authority(manifest=retained, purpose="readback")
            assert historical["approval"] == retained
            current_readback = harness.owner.issue_delivery_readback(
                repository=retained["repository"], approval_id=retained["approval_id"],
            )
            assert current_readback["state"] == "invalidated"
            assert current_readback["approval"] == retained
            with pytest.raises(ControlPlaneScopeError):
                harness.host.issue_delivery_authority(manifest=retained, purpose="execute")
    assert harness.transport.apply_calls == 0
    assert harness.worker_transport.calls == 0


@pytest.mark.parametrize("bifrost", [False, True])
def test_issue_approval_production_admission(store, registry, monkeypatch, tmp_path, issue_delivery_production_harness, bifrost) -> None:
    if bifrost:
        from app.builderops.control_plane.issue_delivery import strip_server_fields
        from app.builderops.control_plane.client import ControlPlaneClientError
        harness = issue_delivery_production_harness(bifrost=True)
        assert harness.approval["contract_version"] == "fca-issue-delivery.v2"
        assert harness.approval["owner_principal"] == "owner:human"
        manifest = strip_server_fields(harness.approval)
        manifest.pop("contract", None)
        preview = harness.owner.issue_delivery_preview(manifest=manifest)
        assert preview["contract_version"] == "fca-issue-delivery.v2"
        for repository in ("rasmustho/bifrost", REPOSITORY.lower()):
            original = harness.source_state["documents"][repository]
            harness.source_state["documents"][repository] = {}
            with pytest.raises(ControlPlaneClientError):
                harness.owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
            harness.source_state["documents"][repository] = original
        document = json.loads(harness.registry.manifest_path.read_text())
        for credential_id in ("consumer-effect", "hub-effect", "owner"):
            changed = deepcopy(document)
            for row in changed["credentials"]:
                if row["id"] == credential_id:
                    if credential_id == "owner":
                        row["repositories"] = ["rasmustho/bifrost"]
                    else:
                        row["revoked"] = True
            harness.registry.manifest_path.write_text(json.dumps(changed))
            with pytest.raises(ControlPlaneClientError):
                harness.owner.issue_delivery_preview(manifest=manifest)
            harness.registry.manifest_path.write_text(json.dumps(document))
        for version, repo in (("fca-issue-delivery.v1", "rasmustho/bifrost"),
                              ("fca-issue-delivery.v2", "other/third"),
                              ("fca-issue-delivery.v3", "rasmustho/bifrost")):
            changed = deepcopy(manifest)
            changed.update(contract_version=version, repository=repo)
            with pytest.raises(ControlPlaneClientError):
                harness.owner.issue_delivery_preview(manifest=changed)
        assert harness.transport.apply_calls == 0
        return
    owner = _client(store, registry, "owner-token")
    reader = _client(store, registry, "reader-token")
    executor_low = _client(store, registry, "executor-low-token")
    executor_high = _client(store, registry, "executor-high-token")
    executor_other = _client(store, registry, "executor-other-token")
    inquiry = _client(store, registry, "inquiry-token")
    generic = _client(store, registry, "generic-token")
    manifest = _manifest()

    with pytest.raises(StateConflict, match="service admission capability"):
        store.commit_record(
            envelope=AuthorityEnvelope(
                repository=REPOSITORY,
                scope="issue-delivery-approval",
                stack="builderops-control-plane",
                actor="owner:human",
                source_refs=("forged",),
            ),
            record_id="issue-delivery-approval:forged",
            record_type="IssueDeliveryApproval",
            state="approved",
            payload={},
            idempotency_key="issue-delivery:forged",
        )

    unsupported_repository = deepcopy(manifest)
    unsupported_repository["repository"] = "OtherOrg/other-repository"
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=unsupported_repository)

    launcher_roots: list[Path] = []
    original_launcher_init = CodexIssueSessionLauncher.__init__

    def capture_launcher_root(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        launcher_roots.append(Path(kwargs["repo_root"]))
        return original_launcher_init(self, *args, **kwargs)

    monkeypatch.setattr(CodexIssueSessionLauncher, "__init__", capture_launcher_root)
    preview = owner.issue_delivery_preview(manifest=manifest)
    monkeypatch.setattr(CodexIssueSessionLauncher, "__init__", original_launcher_init)
    assert launcher_roots == [Path(manifest["destination"]["checkout"]).resolve()]  # type: ignore[index]
    assert preview["state"] == "previewed"
    assert preview["manifest"]["operation_type"] == "deliver_ready_issue"
    assert preview["manifest"]["owner_principal"] == "owner:human"
    assert preview["manifest"]["authority_epoch"] == 1

    case_variant_repository = deepcopy(preview["manifest"])
    case_variant_repository["repository"] = "RasmusTho/agentic-pkm-mvp"
    case_variant_repository["approval_manifest_hash"] = issue_delivery_manifest_hash(
        case_variant_repository
    )
    with pytest.raises(ControlPlaneConflictError):
        owner.issue_delivery_start(decision="hold", manifest=case_variant_repository)

    forged_receipt_ref = deepcopy(preview["manifest"])
    forged_receipt_ref["approval_receipt_ref"] = (
        "builderops:record:rasmustho/agentic-pkm-mvp:issue-delivery-approval:forged"
    )
    forged_receipt_ref["approval_manifest_hash"] = issue_delivery_manifest_hash(
        forged_receipt_ref
    )
    with pytest.raises(ControlPlaneConflictError):
        owner.issue_delivery_start(decision="start", manifest=forged_receipt_ref)

    held = owner.issue_delivery_start(decision="hold", manifest=preview["manifest"])
    assert held["state"] == "held"
    assert held["effects"] == []
    assert store.authority_counts(REPOSITORY.lower())["records"] == 0

    started = owner.issue_delivery_start(decision="start", manifest=preview["manifest"])
    assert started["state"] == "approved"
    assert started["approval"]["approval_manifest_hash"] == preview["manifest"]["approval_manifest_hash"]
    assert isinstance(started["approval"].get("approval_digest"), str)
    assert "fingerprint" not in started["approval"]["permission"]
    assert started["receipt"]["receipt_sequence"] > 0
    # The durable approval adds the service-owned lifecycle state at the
    # top level; it must still round-trip as an Issue with state=open before
    # the destination's execute admission validates the same payload.
    normalized_started = normalize_issue_delivery_manifest(started["approval"])
    assert normalized_started["issue"]["state"] == "open"

    fingerprint_preview = deepcopy(manifest)
    fingerprint_preview["owner_profile"]["fingerprint"] = "a" * 64  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=fingerprint_preview)
    fingerprint_start = deepcopy(preview["manifest"])
    fingerprint_start["owner_profile"]["fingerprint"] = "a" * 64  # type: ignore[union-attr]
    fingerprint_start["approval_manifest_hash"] = issue_delivery_manifest_hash(
        fingerprint_start
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_start(decision="start", manifest=fingerprint_start)
    verifier_alias = deepcopy(manifest)
    verifier_alias["context"]["provenance"] = {"token_verifier": "a" * 64}  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=verifier_alias)

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

    original_get_record = store.get_record

    def tamper_approval_timestamp(repository: str, record_id: str):  # type: ignore[no-untyped-def]
        row = dict(original_get_record(repository, record_id))
        row["payload"] = dict(row["payload"])
        row["payload"]["approved_at"] = "2026-01-01T00:00:00+00:00"
        return row

    monkeypatch.setattr(store, "get_record", tamper_approval_timestamp)
    with pytest.raises(ControlPlaneConflictError):
        reader.issue_delivery_readback(repository=REPOSITORY, approval_id="approval-5550")
    monkeypatch.setattr(store, "get_record", original_get_record)

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
    def fail_current_launcher_preflight(*_args, **_kwargs):
        raise AssertionError("readback must not rerun current launcher preflight")

    original_launcher_init = CodexIssueSessionLauncher.__init__
    monkeypatch.setattr(CodexIssueSessionLauncher, "__init__", fail_current_launcher_preflight)
    stale_readback = reader.issue_delivery_authority(
        manifest=started["approval"], purpose="readback"
    )
    assert stale_readback["purpose"] == "readback"
    assert "fingerprint" not in stale_readback["approval"]["permission"]
    assert owner_credential.fingerprint not in json.dumps(stale_readback, sort_keys=True)
    monkeypatch.setattr(
        CodexIssueSessionLauncher,
        "__init__",
        original_launcher_init,
    )
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
    conflicting_artifact_hash = deepcopy(manifest)
    conflicting_artifact_hash["workflow"]["artifacts"][0]["hash"] = "2" * 64  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=conflicting_artifact_hash)
    legacy_artifact_hash = deepcopy(manifest)
    legacy_artifact = legacy_artifact_hash["workflow"]["artifacts"][0]  # type: ignore[index]
    legacy_artifact["hash"] = legacy_artifact.pop("sha256")  # type: ignore[union-attr]
    normalized_legacy = normalize_issue_delivery_manifest(legacy_artifact_hash)
    assert all(
        "hash" not in artifact
        for artifact in normalized_legacy["workflow"]["artifacts"]
    )

    invalid_plan = deepcopy(manifest)
    invalid_plan["context"].pop("expected_plan_hash")  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_plan)
    invalid_context_hash = deepcopy(manifest)
    invalid_context_hash["context"]["content_hash"] = "c" * 64  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_context_hash)
    conflicting_context_alias = deepcopy(manifest)
    conflicting_context_alias["context_pack"] = deepcopy(manifest["context"])
    conflicting_context_alias["context_pack"]["pack_id"] = "other-context"  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=conflicting_context_alias)
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
    for issue_alias, replacement in (
        ("node_id", "I_other_issue"),
        ("title", "another Issue"),
        ("state", "closed"),
        ("body_hash", "c" * 64),
        ("acceptance_criteria_hash", "d" * 64),
    ):
        conflicting_issue_alias = deepcopy(manifest)
        conflicting_issue_alias[issue_alias] = replacement
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=conflicting_issue_alias)
    missing_ready_label = deepcopy(manifest)
    missing_ready_label["issue"]["labels"] = ["type:task"]  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=missing_ready_label)
    for conflicting_label in ("agent:blocked", "agent:needs-human", "agent:other"):
        conflicting_lifecycle_label = deepcopy(manifest)
        conflicting_lifecycle_label["issue"]["labels"] = [  # type: ignore[union-attr]
            "agent:ready",
            conflicting_label,
        ]
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=conflicting_lifecycle_label)
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
    invalid_destination_channel = deepcopy(manifest)
    invalid_destination_channel["destination"]["channel"] = "unsupported"  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_destination_channel)
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
    positional_criteria = deepcopy(manifest)
    positional_criteria["profile"]["verification_profile"]["criterion_hashes"] = [  # type: ignore[union-attr]
        "4" * 64
    ]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=positional_criteria)
    invalid_profile_hash = deepcopy(manifest)
    invalid_profile_hash["profile"]["content_hash"] = "9" * 64  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_profile_hash)
    invalid_verification_hash = deepcopy(manifest)
    invalid_verification_hash["profile"]["verification_profile"]["criterion_hashes"]["AC1"] = "8" * 64  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_verification_hash)

    shared_checkout = deepcopy(manifest)
    shared_checkout["destination"]["worktree"] = shared_checkout["destination"]["checkout"]  # type: ignore[union-attr]
    shared_checkout["context"]["dispatch_plan"]["context_packs"][0]["branch_worktree_plan"]["worktree"] = shared_checkout["destination"]["checkout"]  # type: ignore[union-attr]
    shared_checkout["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        shared_checkout["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    shared_checkout["context"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        shared_checkout["context"]["dispatch_plan"]["context_packs"][0]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=shared_checkout)
    base_branch = deepcopy(manifest)
    base_branch["destination"]["branch"] = base_branch["destination"]["base_ref"]  # type: ignore[union-attr]
    base_branch["context"]["dispatch_plan"]["context_packs"][0]["branch_worktree_plan"]["branch"] = base_branch["destination"]["base_ref"]  # type: ignore[union-attr]
    base_branch["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        base_branch["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    base_branch["context"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        base_branch["context"]["dispatch_plan"]["context_packs"][0]  # type: ignore[union-attr]
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
    normalized_shared_checkout["context"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        normalized_shared_checkout["context"]["dispatch_plan"]["context_packs"][0]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=normalized_shared_checkout)
    descendant_worktree = deepcopy(manifest)
    descendant_worktree["destination"]["worktree"] = (  # type: ignore[union-attr]
        "/workspaces/agentic-pkm-mvp/child"
    )
    descendant_worktree["context"]["dispatch_plan"]["context_packs"][0][  # type: ignore[union-attr]
        "branch_worktree_plan"
    ]["worktree"] = "/workspaces/agentic-pkm-mvp/child"
    descendant_worktree["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        descendant_worktree["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    descendant_worktree["context"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        descendant_worktree["context"]["dispatch_plan"]["context_packs"][0]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=descendant_worktree)
    double_slash_worktree = deepcopy(manifest)
    double_slash_worktree["destination"]["worktree"] = (  # type: ignore[union-attr]
        "//workspaces/agentic-pkm-mvp"
    )
    double_slash_worktree["context"]["dispatch_plan"]["context_packs"][0][  # type: ignore[union-attr]
        "branch_worktree_plan"
    ]["worktree"] = "//workspaces/agentic-pkm-mvp"
    double_slash_worktree["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        double_slash_worktree["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    double_slash_worktree["context"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        double_slash_worktree["context"]["dispatch_plan"]["context_packs"][0]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=double_slash_worktree)
    overlapping_worktree = deepcopy(manifest)
    overlapping_worktree["destination"]["checkout"] = (  # type: ignore[union-attr]
        "/workspaces/agentic-pkm-mvp/subdir"
    )
    overlapping_worktree["destination"]["worktree"] = (  # type: ignore[union-attr]
        "/workspaces/agentic-pkm-mvp"
    )
    overlapping_worktree["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        overlapping_worktree["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=overlapping_worktree)
    actual_checkout = tmp_path / "checkout"
    actual_checkout.mkdir()
    symlinked_checkout = tmp_path / "checkout-link"
    symlinked_checkout.symlink_to(actual_checkout, target_is_directory=True)
    symlink_overlap = deepcopy(manifest)
    symlink_overlap["destination"]["checkout"] = str(actual_checkout)  # type: ignore[union-attr]
    symlink_overlap["destination"]["worktree"] = str(symlinked_checkout)  # type: ignore[union-attr]
    symlink_overlap["context"]["dispatch_plan"]["context_packs"][0][  # type: ignore[union-attr]
        "branch_worktree_plan"
    ]["worktree"] = str(symlinked_checkout)
    symlink_overlap["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        symlink_overlap["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    symlink_overlap["context"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        symlink_overlap["context"]["dispatch_plan"]["context_packs"][0]  # type: ignore[union-attr]
    )
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=symlink_overlap)
    sibling_worktree = deepcopy(manifest)
    sibling_worktree["destination"]["worktree"] = (  # type: ignore[union-attr]
        "/workspaces/agentic-pkm-mvp-sibling"
    )
    sibling_worktree["context"]["dispatch_plan"]["context_packs"][0][  # type: ignore[union-attr]
        "branch_worktree_plan"
    ]["worktree"] = "/workspaces/agentic-pkm-mvp-sibling"
    sibling_worktree["context"]["expected_plan_hash"] = canonical_hash(  # type: ignore[union-attr]
        sibling_worktree["context"]["dispatch_plan"]  # type: ignore[union-attr]
    )
    sibling_worktree["context"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        sibling_worktree["context"]["dispatch_plan"]["context_packs"][0]  # type: ignore[union-attr]
    )
    assert owner.issue_delivery_preview(manifest=sibling_worktree)["state"] == "previewed"

    for revision in ("main", "main:a5f0e10b666e74c4b8de36a67563a99e30ee801d", "HEAD"):
        invalid_source = deepcopy(manifest)
        invalid_source["source"]["revision"] = revision  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=invalid_source)
    mismatched_source_ref = deepcopy(manifest)
    mismatched_source_ref["source"]["refs"][1] = "git:" + "b" * 40  # type: ignore[union-attr]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=mismatched_source_ref)
    for alias, replacement in (
        ("source_revision", "b" * 40),
        ("source_revisions", ["b" * 40]),
        ("source_refs", ["git:" + "b" * 40]),
    ):
        conflicting_source_alias = deepcopy(manifest)
        conflicting_source_alias["source"][alias] = replacement  # type: ignore[index]
        with pytest.raises(ControlPlaneProtocolError):
            owner.issue_delivery_preview(manifest=conflicting_source_alias)
    conflicting_source_hash_alias = deepcopy(manifest)
    conflicting_source_hash_alias["source"]["content_hash"] = "c" * 64  # type: ignore[index]
    conflicting_source_hash_alias["source"]["source_hash"] = "d" * 64  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=conflicting_source_hash_alias)

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
    unknown_parent_permission = deepcopy(manifest)
    unknown_parent_permission["parent_evidence"] = deepcopy(foreign_parent["parent_evidence"])
    unknown_parent_permission["parent_evidence"]["repository"] = REPOSITORY  # type: ignore[index]
    unknown_parent_permission["parent_evidence"]["write_permission"]["extra"] = "unexpected"  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=unknown_parent_permission)

    incomplete_parent = deepcopy(manifest)
    incomplete_parent["parent_evidence"] = {"kind": "issue"}
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=incomplete_parent)
    self_parent = deepcopy(manifest)
    self_parent["parent_evidence"] = {
        "kind": "issue",
        "repository": REPOSITORY,
        "number": 5550,
        "node_id": "I_self_parent",
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
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=self_parent)
    self_parent_same_node = deepcopy(self_parent)
    self_parent_same_node["parent_evidence"]["number"] = 5399  # type: ignore[index]
    self_parent_same_node["parent_evidence"]["node_id"] = manifest["issue"]["node_id"]  # type: ignore[index]
    with pytest.raises(ControlPlaneProtocolError):
        owner.issue_delivery_preview(manifest=self_parent_same_node)
    foreign_parent_start = deepcopy(preview["manifest"])
    foreign_parent_start["parent_evidence"] = foreign_parent["parent_evidence"]
    foreign_parent_start["approval_manifest_hash"] = issue_delivery_manifest_hash(
        foreign_parent_start
    )
    with pytest.raises(ControlPlaneScopeError):
        owner.issue_delivery_start(decision="start", manifest=foreign_parent_start)
    foreign_owner_profile_start = deepcopy(preview["manifest"])
    foreign_owner_profile_start["owner_profile"]["principal"] = "owner:other"  # type: ignore[union-attr]
    foreign_owner_profile_start["profile"]["content_hash"] = canonical_hash(  # type: ignore[union-attr]
        {
            key: value
            for key, value in foreign_owner_profile_start["profile"].items()  # type: ignore[union-attr]
            if key != "content_hash"
        }
    )
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
