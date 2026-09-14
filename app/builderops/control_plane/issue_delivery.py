"""Closed manifest helpers for the first approved Issue-delivery operation.

This module deliberately contains no launcher or GitHub client.  FCA-ID-A is
only the authenticated admission boundary; destination execution and
independent source readback remain owned by the later slices.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.builderops.control_plane.models import canonical_repository

CONTRACT_VERSION = "fca-issue-delivery.v1"
OPERATION_TYPE = "deliver_ready_issue"
RECORD_TYPE = "IssueDeliveryApproval"
RECORD_PREFIX = "issue-delivery-approval:"
IDEMPOTENCY_PREFIX = "issue-delivery:"
WORKFLOW_ENTRYPOINT = "app/builderops/epic_dispatch.py::dispatch_issue_sessions"
WORKFLOW_LAUNCHER = "app/builderops/epic_dispatch.py::CodexIssueSessionLauncher.launch"
REQUIRED_WORKFLOW_ARTIFACTS = frozenset(
    {
        "app/builderops/cli.py",
        "app/builderops/epic_dispatch.py",
        ".codex/agents/slice-implementer.toml",
        ".codex/skills/issue-to-code/SKILL.md",
        ".codex/skills/publish-pr/SKILL.md",
        ".codex/skills/verification-and-closure/SKILL.md",
    }
)

# FCA-ID-A admits the complete repository delivery chain as a named set.  The
# destination slices decide whether an individual effect is currently
# available; admission never turns an arbitrary caller-provided string into
# owner authority.
PERMITTED_EFFECTS = frozenset(
    {
        "repository_worktree",
        "issue_claim",
        "publication",
        "review_merge",
        "closure_reconciliation",
    }
)
REQUIRED_NON_EFFECTS = frozenset(
    {"deployment", "credential_provisioning", "owner_acceptance"}
)
OPTIONAL_NON_EFFECTS = frozenset(
    {
        "release_stable_movement",
        "host_setup",
        "destructive_database_vault_operations",
        "other_repository_issue_effects",
        "universal_unattended_execution",
    }
)
NON_EFFECTS = REQUIRED_NON_EFFECTS | OPTIONAL_NON_EFFECTS

_HASH = re.compile(r"^[0-9a-f]{64}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_:-]{1,256}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_SERVER_FIELDS = frozenset(
    {
        "owner_principal",
        "permission",
        "authority_epoch",
        "approval_receipt_ref",
        "approved_at",
        "previewed_at",
        "approval_manifest_hash",
        "state",
    }
)
_NON_BINDING_FIELDS = frozenset({"approval_manifest_hash", "contract", "state", "approved_at"})


class IssueDeliveryContractError(ValueError):
    """The supplied Issue-delivery manifest is not exact and closed."""


def canonical_hash(value: Any) -> str:
    """Hash canonical JSON bytes used by the immutable approval manifest."""

    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IssueDeliveryContractError("manifest is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _text(value: Any, name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise IssueDeliveryContractError(f"{name} is required")
    return value.strip()


def _sha(value: Any, name: str) -> str:
    candidate = _text(value, name, limit=64).lower()
    if _HASH.fullmatch(candidate) is None:
        raise IssueDeliveryContractError(f"{name} must be a SHA-256 digest")
    return candidate


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise IssueDeliveryContractError(f"{name} is required")
    return dict(value)


def _list_of_text(value: Any, name: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise IssueDeliveryContractError(f"{name} must be a non-empty list")
    result = [_text(item, name, limit=256) for item in value]
    if len(set(result)) != len(result):
        raise IssueDeliveryContractError(f"{name} must contain unique values")
    return result


def _issue_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = value.get("issue")
    if raw is None:
        raw = {
            key: value[key]
            for key in (
                "issue_number",
                "issue_node_id",
                "node_id",
                "title",
                "issue_title",
                "state",
                "issue_state",
                "body_hash",
                "issue_body_hash",
                "acceptance_criteria_hash",
            )
            if key in value
        }
    issue = _mapping(raw, "issue")
    number = issue.get("number", issue.get("issue_number"))
    if type(number) is not int or number < 1:
        raise IssueDeliveryContractError("exact numeric Issue identity is required")
    node_id = issue.get("node_id", issue.get("issue_node_id"))
    node_id = _text(node_id, "issue node identity")
    if _NODE_ID.fullmatch(node_id) is None:
        raise IssueDeliveryContractError("issue node identity is malformed")
    title = _text(issue.get("title", issue.get("issue_title")), "issue title", limit=4096)
    state = _text(issue.get("state", issue.get("issue_state")), "issue state", limit=32).lower()
    if state != "open":
        raise IssueDeliveryContractError("Issue-delivery admission requires an open Issue")
    body_hash = _sha(
        issue.get("body_hash", issue.get("issue_body_hash")), "Issue body hash"
    )
    criteria_hash = _sha(
        issue.get("acceptance_criteria_hash"), "acceptance criteria hash"
    )
    return {
        **issue,
        "number": number,
        "node_id": node_id,
        "title": title,
        "state": state,
        "body_hash": body_hash,
        "acceptance_criteria_hash": criteria_hash,
    }


def _source_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = value.get("source")
    if raw is None:
        raw = {
            key: value[key]
            for key in (
                "source_revision",
                "source_revisions",
                "source_refs",
                "source_hash",
                "source_content_hash",
            )
            if key in value
        }
    source = _mapping(raw, "source")
    revision = source.get("revision", source.get("source_revision"))
    if revision is None:
        revisions = source.get("revisions", source.get("source_revisions"))
        if isinstance(revisions, (list, tuple)) and len(revisions) == 1:
            revision = revisions[0]
    revision = _text(revision, "source revision", limit=1024)
    refs = source.get("refs", source.get("source_refs", []))
    if refs:
        refs = _list_of_text(refs, "source references")
    else:
        refs = []
    content_hash = source.get(
        "content_hash", source.get("source_hash", source.get("source_content_hash"))
    )
    if content_hash is not None:
        content_hash = _sha(content_hash, "source content hash")
    if content_hash is None and not refs:
        raise IssueDeliveryContractError("source hash or source reference is required")
    return {**source, "revision": revision, "refs": refs, **({"content_hash": content_hash} if content_hash else {})}


def _hash_binding(value: Any, name: str) -> dict[str, Any]:
    result = _mapping(value, name)
    candidate = result.get("content_hash", result.get("hash", result.get(f"{name}_hash")))
    if candidate is None:
        # Profile/policy references may use a nested set of hashed bindings;
        # require at least one explicit digest rather than inventing one.
        nested = [item for item in result.values() if isinstance(item, Mapping)]
        if not any(
            any(key in item and _HASH.fullmatch(str(item[key]).lower()) for key in ("content_hash", "hash", "sha256"))
            for item in nested
        ):
            raise IssueDeliveryContractError(f"{name} hash binding is required")
    else:
        result["content_hash"] = _sha(candidate, f"{name} hash")
    return result


def _workflow_fields(value: Any) -> dict[str, Any]:
    workflow = _mapping(value, "workflow")
    version = _text(
        workflow.get("version", workflow.get("contract_version")),
        "workflow version",
    )
    if version != CONTRACT_VERSION:
        raise IssueDeliveryContractError("workflow version is not approved")
    declared_hashes = [
        workflow[key]
        for key in ("content_hash", "workflow_hash")
        if key in workflow
    ]
    if not declared_hashes:
        raise IssueDeliveryContractError("workflow hash is required")
    workflow_hash = _sha(declared_hashes[0], "workflow hash")
    if len(declared_hashes) > 1 and _sha(declared_hashes[1], "workflow hash") != workflow_hash:
        raise IssueDeliveryContractError("workflow hash bindings disagree")
    entrypoint = _text(workflow.get("entrypoint"), "workflow entrypoint", limit=1024)
    if entrypoint != WORKFLOW_ENTRYPOINT:
        raise IssueDeliveryContractError("workflow entrypoint is not approved")
    launcher = _text(workflow.get("launcher"), "workflow launcher", limit=1024)
    if launcher != WORKFLOW_LAUNCHER:
        raise IssueDeliveryContractError("workflow launcher is not approved")
    artifacts_raw = workflow.get("artifacts", workflow.get("artifact_manifest"))
    if not isinstance(artifacts_raw, (list, tuple)) or not artifacts_raw:
        raise IssueDeliveryContractError("workflow artifact manifest is required")
    artifacts: list[dict[str, Any]] = []
    paths: set[str] = set()
    for artifact_raw in artifacts_raw:
        artifact = _mapping(artifact_raw, "workflow artifact")
        path = _text(artifact.get("path"), "workflow artifact path", limit=512)
        digest = _sha(
            artifact.get("sha256", artifact.get("hash")),
            "workflow artifact hash",
        )
        if path in paths:
            raise IssueDeliveryContractError("workflow artifacts must be unique")
        paths.add(path)
        artifacts.append({**artifact, "path": path, "sha256": digest})
    if paths != REQUIRED_WORKFLOW_ARTIFACTS:
        raise IssueDeliveryContractError("workflow artifact manifest is incomplete or unrelated")
    return {
        **workflow,
        "version": version,
        "content_hash": workflow_hash,
        "entrypoint": entrypoint,
        "launcher": launcher,
        "artifacts": artifacts,
    }


def _parent_evidence(value: Any, *, issue_number: int) -> dict[str, Any]:
    parent = _mapping(value, "parent evidence binding")
    parent_kind = _text(parent.get("kind"), "parent evidence kind", limit=32)
    if parent_kind == "none":
        if set(parent) != {"kind"}:
            raise IssueDeliveryContractError("absent parent evidence must be explicit")
        return {"kind": "none"}
    if parent_kind != "issue":
        raise IssueDeliveryContractError("parent evidence kind is unsupported")

    repository = canonical_repository(
        _text(parent.get("repository", parent.get("parent_repository")), "parent repository", limit=256)
    )
    number = parent.get("number", parent.get("parent_issue_number"))
    if type(number) is not int or number < 1:
        raise IssueDeliveryContractError("exact parent Issue number is required")
    node_id = _text(
        parent.get("node_id", parent.get("parent_node_id")),
        "parent Issue node identity",
    )
    if _NODE_ID.fullmatch(node_id) is None:
        raise IssueDeliveryContractError("parent Issue node identity is malformed")

    relationship = parent.get("relationship")
    if isinstance(relationship, Mapping):
        relationship = dict(relationship)
        relation_kind = _text(
            relationship.get("kind", relationship.get("type")),
            "parent Issue relationship",
            limit=64,
        )
        related_issue_number = relationship.get(
            "child_issue_number", relationship.get("issue_number")
        )
        authenticated = relationship.get("authenticated")
    else:
        relation_kind = _text(relationship, "parent Issue relationship", limit=64)
        related_issue_number = parent.get("child_issue_number", parent.get("issue_number"))
        authenticated = parent.get("relationship_authenticated", parent.get("authenticated"))
    if relation_kind not in {"parent", "parent-child", "child-of"}:
        raise IssueDeliveryContractError("parent Issue relationship is unsupported")
    if related_issue_number != issue_number or authenticated is not True:
        raise IssueDeliveryContractError("parent Issue relationship is not source-authenticated")

    contract_version = _text(
        parent.get("contract_version", parent.get("version")),
        "parent contract version",
    )
    contract_hash = _sha(
        parent.get("contract_hash", parent.get("content_hash")),
        "parent contract hash",
    )
    write_permission = _mapping(
        parent.get("write_permission", parent.get("permission")),
        "parent write permission",
    )
    permission_scope = _text(
        write_permission.get("scope", write_permission.get("grant")),
        "parent write permission scope",
    )
    writes = write_permission.get(
        "effects", write_permission.get("writes", write_permission.get("targets"))
    )
    if not isinstance(writes, (list, tuple)) or not writes:
        raise IssueDeliveryContractError("parent write permission targets are required")
    writes = _list_of_text(writes, "parent write permission targets")
    required_writes = {"pr_receipt_comments", "child_generated_ledger_writeback"}
    if set(writes) != required_writes or permission_scope != "parent_evidence:write":
        raise IssueDeliveryContractError("parent write permission is not exact")
    return {
        "kind": "issue",
        "repository": repository,
        "number": number,
        "node_id": node_id,
        "relationship": {
            "kind": relation_kind,
            "child_issue_number": issue_number,
            "authenticated": True,
        },
        "contract_version": contract_version,
        "contract_hash": contract_hash,
        "write_permission": {**write_permission, "scope": permission_scope, "effects": writes},
    }


def normalize_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the caller-controlled portion of a manifest."""

    if not isinstance(value, Mapping):
        raise IssueDeliveryContractError("Issue-delivery manifest is required")
    raw = dict(value)
    try:
        if raw.get("contract_version") != CONTRACT_VERSION:
            raise IssueDeliveryContractError("fca-issue-delivery.v1 contract is required")
        if raw.get("operation_type") != OPERATION_TYPE:
            raise IssueDeliveryContractError("deliver_ready_issue operation is required")
        repository = canonical_repository(_text(raw.get("repository"), "repository", limit=256))
        approval_id = _text(raw.get("approval_id"), "approval id")
        operation_key = _text(raw.get("operation_key"), "operation key")
        if _ID.fullmatch(approval_id) is None or _ID.fullmatch(operation_key) is None:
            raise IssueDeliveryContractError("approval and operation identities are malformed")
        expires_at = _text(raw.get("expires_at"), "expiry", limit=64)
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise IssueDeliveryContractError("expiry must be timezone-aware")
        issue = _issue_fields(raw)
        source = _source_fields(raw)
        context = _hash_binding(
            raw.get("context", raw.get("context_pack", raw.get("context_pack_ref"))),
            "context",
        )
        workflow = _workflow_fields(raw.get("workflow"))
        destination = _mapping(raw.get("destination"), "destination")
        destination_identity = _text(destination.get("identity"), "destination identity", limit=256)
        run_id = _text(destination.get("run_id", destination.get("proposed_run_id")), "proposed run identity", limit=256)
        destination = {**destination, "identity": destination_identity, "run_id": run_id}
        profile = _hash_binding(raw.get("profile"), "profile")
        effects = _list_of_text(raw.get("permitted_effects"), "permitted effects")
        non_effects = _list_of_text(raw.get("explicit_non_effects"), "explicit non-effects")
        if set(effects) & set(non_effects):
            raise IssueDeliveryContractError("permitted and non-effect sets must be disjoint")
        if set(effects) != PERMITTED_EFFECTS:
            raise IssueDeliveryContractError("permitted effects do not match the closed delivery set")
        if not REQUIRED_NON_EFFECTS.issubset(non_effects) or not set(non_effects).issubset(NON_EFFECTS):
            raise IssueDeliveryContractError("explicit non-effects do not match the closed delivery set")
        parent = _parent_evidence(raw.get("parent_evidence"), issue_number=issue["number"])
        owner_profile = raw.get("owner_profile")
        if owner_profile is not None:
            owner_profile = _mapping(owner_profile, "owner profile")
        result = {
            **raw,
            "contract_version": CONTRACT_VERSION,
            "operation_type": OPERATION_TYPE,
            "repository": repository,
            "approval_id": approval_id,
            "operation_key": operation_key,
            "expires_at": expiry.astimezone(timezone.utc).isoformat(),
            "issue": issue,
            "source": source,
            "context": context,
            "workflow": workflow,
            "destination": destination,
            "profile": profile,
            "permitted_effects": effects,
            "explicit_non_effects": non_effects,
            "parent_evidence": parent,
        }
        if owner_profile is not None:
            result["owner_profile"] = owner_profile
        return result
    except IssueDeliveryContractError:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IssueDeliveryContractError("invalid Issue-delivery manifest") from exc


def manifest_hash(value: Mapping[str, Any]) -> str:
    return canonical_hash({key: item for key, item in value.items() if key not in _NON_BINDING_FIELDS})


def record_id(approval_id: str) -> str:
    return RECORD_PREFIX + approval_id


def idempotency_key(operation_key: str) -> str:
    return IDEMPOTENCY_PREFIX + operation_key


def strip_server_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in _SERVER_FIELDS}


__all__ = [
    "CONTRACT_VERSION",
    "IDEMPOTENCY_PREFIX",
    "IssueDeliveryContractError",
    "NON_EFFECTS",
    "OPERATION_TYPE",
    "PERMITTED_EFFECTS",
    "RECORD_PREFIX",
    "RECORD_TYPE",
    "REQUIRED_NON_EFFECTS",
    "REQUIRED_WORKFLOW_ARTIFACTS",
    "WORKFLOW_ENTRYPOINT",
    "WORKFLOW_LAUNCHER",
    "canonical_hash",
    "idempotency_key",
    "manifest_hash",
    "normalize_manifest",
    "record_id",
    "strip_server_fields",
]
