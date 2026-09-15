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
from posixpath import normpath
from typing import Any

from app.builderops.control_plane.models import canonical_repository

CONTRACT_VERSION = "fca-issue-delivery.v1"
OPERATION_TYPE = "deliver_ready_issue"
RECORD_TYPE = "IssueDeliveryApproval"
RECORD_PREFIX = "issue-delivery-approval:"
IDEMPOTENCY_PREFIX = "issue-delivery:"
# FCA-ID-A is intentionally qualified only for the repository whose owner
# document and live Issue contract define this first delivery operation.
QUALIFIED_REPOSITORY = "rasmustho/agentic-pkm-mvp"
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
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SELECTION_INTENTS = frozenset(
    {"coordination", "general_delivery", "strong_reasoning", "verification"}
)
_CAPABILITIES = frozenset({"spark", "luna", "terra", "sol"})
_REASONING_EFFORTS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_CARRIERS = frozenset({"codex"})
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
        "approval_digest",
        "state",
    }
)
_NON_BINDING_FIELDS = frozenset(
    {"approval_manifest_hash", "approval_digest", "contract", "state", "approved_at"}
)
_TOP_LEVEL_CONTEXT_ALIASES = frozenset({"context_pack", "context_pack_ref"})
_TOP_LEVEL_ISSUE_ALIASES = frozenset(
    {
        "issue_number",
        "issue_node_id",
        "issue_title",
        "issue_state",
        "issue_body_hash",
    }
)
_TOP_LEVEL_SOURCE_ALIASES = frozenset(
    {
        "source_revision",
        "source_revisions",
        "source_refs",
        "source_hash",
        "source_content_hash",
    }
)


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


def _coalesce_aliases(
    value: Mapping[str, Any], aliases: tuple[str, ...], name: str
) -> tuple[bool, Any]:
    """Return one authority value and reject disagreeing compatibility aliases."""

    present = [(key, value[key]) for key in aliases if key in value]
    if not present:
        return False, None
    first = present[0][1]
    if any(candidate != first for _key, candidate in present[1:]):
        raise IssueDeliveryContractError(f"{name} aliases disagree")
    return True, first


def _without_aliases(value: Mapping[str, Any], aliases: frozenset[str]) -> dict[str, Any]:
    """Drop legacy spellings after their values have been cross-checked."""

    return {key: item for key, item in value.items() if key not in aliases}


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
    if value.get("issue") is not None:
        for key in _TOP_LEVEL_ISSUE_ALIASES:
            if key not in value:
                continue
            if key in issue and issue[key] != value[key]:
                raise IssueDeliveryContractError(
                    f"Issue field alias {key} disagrees with nested issue"
                )
            issue.setdefault(key, value[key])
    present, number = _coalesce_aliases(
        issue, ("number", "issue_number"), "Issue number"
    )
    if not present:
        number = None
    if type(number) is not int or number < 1:
        raise IssueDeliveryContractError("exact numeric Issue identity is required")
    _present, node_id = _coalesce_aliases(
        issue, ("node_id", "issue_node_id"), "Issue node identity"
    )
    node_id = _text(node_id, "issue node identity")
    if _NODE_ID.fullmatch(node_id) is None:
        raise IssueDeliveryContractError("issue node identity is malformed")
    _present, title = _coalesce_aliases(
        issue, ("title", "issue_title"), "Issue title"
    )
    title = _text(title, "issue title", limit=4096)
    _present, state = _coalesce_aliases(
        issue, ("state", "issue_state"), "Issue state"
    )
    state = _text(state, "issue state", limit=32).lower()
    if state != "open":
        raise IssueDeliveryContractError("Issue-delivery admission requires an open Issue")
    _present, body_hash = _coalesce_aliases(
        issue, ("body_hash", "issue_body_hash"), "Issue body hash"
    )
    body_hash = _sha(body_hash, "Issue body hash")
    criteria_hash = _sha(
        issue.get("acceptance_criteria_hash"), "acceptance criteria hash"
    )
    issue_url = _text(issue.get("url"), "Issue URL", limit=1024)
    issue_scope = _text(issue.get("scope"), "Issue scope", limit=8192)
    labels = issue.get("labels")
    if not isinstance(labels, (list, tuple)) or not labels:
        raise IssueDeliveryContractError("immutable Issue labels are required")
    normalized_labels = [_text(label, "Issue label", limit=256) for label in labels]
    agent_labels = {label for label in normalized_labels if label.startswith("agent:")}
    if agent_labels != {"agent:ready"}:
        raise IssueDeliveryContractError("Issue-delivery admission requires the agent:ready label")
    return {
        **_without_aliases(issue, _TOP_LEVEL_ISSUE_ALIASES),
        "number": number,
        "node_id": node_id,
        "title": title,
        "state": state,
        "body_hash": body_hash,
        "acceptance_criteria_hash": criteria_hash,
        "url": issue_url,
        "scope": issue_scope,
        "labels": normalized_labels,
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
    if value.get("source") is not None:
        for key in _TOP_LEVEL_SOURCE_ALIASES:
            if key not in value:
                continue
            if key in source and source[key] != value[key]:
                raise IssueDeliveryContractError(
                    f"source field alias {key} disagrees with nested source"
                )
            source.setdefault(key, value[key])
    _present, revision = _coalesce_aliases(
        source, ("revision", "source_revision"), "source revision"
    )
    _revisions_present, revisions = _coalesce_aliases(
        source, ("revisions", "source_revisions"), "source revisions"
    )
    if _present and _revisions_present:
        if not isinstance(revisions, (list, tuple)) or len(revisions) != 1 or revisions[0] != revision:
            raise IssueDeliveryContractError("source revision aliases disagree")
    elif not _present and _revisions_present:
        if isinstance(revisions, (list, tuple)) and len(revisions) == 1:
            revision = revisions[0]
    revision = _text(revision, "source revision", limit=64).lower()
    if _GIT_SHA.fullmatch(revision) is None:
        raise IssueDeliveryContractError(
            "source revision must be one immutable 40-character Git commit"
        )
    _refs_present, refs = _coalesce_aliases(
        source, ("refs", "source_refs"), "source references"
    )
    if not _refs_present:
        refs = []
    if refs:
        refs = _list_of_text(refs, "source references")
        for ref in refs:
            if ref.startswith("git:") and _GIT_SHA.fullmatch(ref.removeprefix("git:")) is None:
                raise IssueDeliveryContractError(
                    "Git source references must bind immutable commits"
                )
    else:
        refs = []
    for ref in refs:
        if ref.startswith("git:") and ref.removeprefix("git:") != revision:
            raise IssueDeliveryContractError(
                "Git source references must match the normalized source revision"
            )
    _content_hash_present, content_hash = _coalesce_aliases(
        source,
        ("content_hash", "source_hash", "source_content_hash"),
        "source content hash",
    )
    if content_hash is not None:
        content_hash = _sha(content_hash, "source content hash")
    if content_hash is None and not refs:
        raise IssueDeliveryContractError("source hash or source reference is required")
    return {
        **_without_aliases(
            source,
            _TOP_LEVEL_SOURCE_ALIASES
            | frozenset({"revision", "revisions", "refs", "content_hash"}),
        ),
        "revision": revision,
        "refs": refs,
        **({"content_hash": content_hash} if content_hash else {}),
    }


def _dispatch_plan_fields(
    value: Any, *, issue_number: int, context_pack_id: str, channel: str
) -> dict[str, Any]:
    """Validate the complete one-Issue frozen plan admitted by FCA-ID-A."""

    try:
        from app.builderops.epic_dispatch import validate_issue_delivery_plan

        plan = validate_issue_delivery_plan(
            _mapping(value, "frozen dispatch plan"),
            issue_number=issue_number,
            context_pack_id=context_pack_id,
            channel=channel,
        )
    except Exception as exc:
        raise IssueDeliveryContractError(
            "frozen dispatch plan fails the canonical planner and launcher preflight"
        ) from exc
    return dict(plan)


def _context_fields(value: Any, *, issue_number: int, channel: str) -> dict[str, Any]:
    context = _mapping(value, "context")
    if "content_hash" not in context:
        raise IssueDeliveryContractError(
            "context content hash must be declared at the top level"
        )
    _present, context_hash_value = _coalesce_aliases(
        context, ("content_hash", "hash", "context_hash"), "context hash"
    )
    context_hash = _sha(context_hash_value, "context hash")
    _pack_present, pack_id = _coalesce_aliases(
        context, ("pack_id", "context_pack_id"), "context pack id"
    )
    pack_id = _text(pack_id, "context pack id")
    _plan_present, plan = _coalesce_aliases(
        context, ("dispatch_plan", "frozen_dispatch_plan"), "dispatch plan"
    )
    expected_plan_hash = _sha(
        context.get("expected_plan_hash"), "expected dispatch plan hash"
    )
    plan = _dispatch_plan_fields(
        plan,
        issue_number=issue_number,
        context_pack_id=pack_id,
        channel=channel,
    )
    if expected_plan_hash != canonical_hash(plan):
        raise IssueDeliveryContractError(
            "expected dispatch plan hash does not bind the frozen dispatch plan"
        )
    selected_context_pack = plan["context_packs"][0]
    if context_hash != canonical_hash(selected_context_pack):
        raise IssueDeliveryContractError(
            "context hash does not bind the selected context pack"
        )
    return {
        **_without_aliases(
            context,
            frozenset({"hash", "context_hash", "context_pack_id", "frozen_dispatch_plan"}),
        ),
        "pack_id": pack_id,
        "content_hash": context_hash,
        "dispatch_plan": plan,
        "expected_plan_hash": expected_plan_hash,
    }


def _execution_profile_fields(value: Any) -> dict[str, Any]:
    """Require a closed, resolved execution and verification profile."""

    profile = _mapping(value, "profile")
    if set(profile) != {
        "content_hash",
        "provider_census_hash",
        "configuration_digest",
        "selection_intent",
        "resolved",
        "verification_profile",
    }:
        raise IssueDeliveryContractError("execution profile fields are not the closed approved set")
    provider_census_hash = _sha(profile.get("provider_census_hash"), "provider census hash")
    configuration_digest = _sha(
        profile.get("configuration_digest"), "execution configuration digest"
    )
    selection_intent = _text(profile.get("selection_intent"), "execution selection intent", limit=64)
    if selection_intent not in _SELECTION_INTENTS or selection_intent != "general_delivery":
        raise IssueDeliveryContractError("execution selection intent is unsupported")
    resolved = _mapping(profile.get("resolved"), "resolved execution target")
    if set(resolved) != {"capability", "model", "reasoning_effort", "carrier"}:
        raise IssueDeliveryContractError("resolved execution target fields are incomplete")
    capability = _text(resolved.get("capability"), "resolved execution capability", limit=32)
    if capability not in _CAPABILITIES:
        raise IssueDeliveryContractError("resolved execution capability is unsupported")
    model = _text(resolved.get("model"), "resolved execution model", limit=256)
    reasoning_effort = _text(
        resolved.get("reasoning_effort"), "resolved execution reasoning effort", limit=32
    )
    if reasoning_effort not in _REASONING_EFFORTS:
        raise IssueDeliveryContractError("resolved execution reasoning effort is unsupported")
    carrier = _text(resolved.get("carrier"), "resolved execution carrier", limit=32)
    if carrier not in _CARRIERS:
        raise IssueDeliveryContractError("resolved execution carrier is unsupported")
    verification = _mapping(profile.get("verification_profile"), "verification profile")
    if set(verification) != {"content_hash", "criterion_hashes"}:
        raise IssueDeliveryContractError("verification profile fields are incomplete")
    verification_hash = _sha(verification.get("content_hash"), "verification profile hash")
    criterion_hashes = verification.get("criterion_hashes")
    if isinstance(criterion_hashes, Mapping):
        if not criterion_hashes:
            raise IssueDeliveryContractError("verification criterion hashes are required")
        normalized_criteria: dict[str, str] = {}
        for criterion, digest in criterion_hashes.items():
            criterion_id = _text(criterion, "verification criterion id", limit=256)
            normalized_criteria[criterion_id] = _sha(digest, "verification criterion hash")
        if len(normalized_criteria) != len(criterion_hashes):
            raise IssueDeliveryContractError("verification criterion ids must be unique")
    elif isinstance(criterion_hashes, (list, tuple)) and criterion_hashes:
        normalized_criteria = {
            str(index): _sha(digest, "verification criterion hash")
            for index, digest in enumerate(criterion_hashes, start=1)
        }
    else:
        raise IssueDeliveryContractError("verification criterion hashes are required")
    profile_hash = _sha(profile.get("content_hash"), "execution profile hash")
    if verification_hash != canonical_hash(normalized_criteria):
        raise IssueDeliveryContractError(
            "verification profile hash does not bind its criterion hashes"
        )
    canonical_profile = {
        "provider_census_hash": provider_census_hash,
        "configuration_digest": configuration_digest,
        "selection_intent": selection_intent,
        "resolved": {
            "capability": capability,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "carrier": carrier,
        },
        "verification_profile": {
            "content_hash": verification_hash,
            "criterion_hashes": normalized_criteria,
        },
    }
    if profile_hash != canonical_hash(canonical_profile):
        raise IssueDeliveryContractError(
            "execution profile hash does not bind the closed execution profile"
        )
    return {
        **profile,
        "content_hash": profile_hash,
        "provider_census_hash": provider_census_hash,
        "configuration_digest": configuration_digest,
        "selection_intent": selection_intent,
        "resolved": {
            **resolved,
            "capability": capability,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "carrier": carrier,
        },
        "verification_profile": {
            **verification,
            "content_hash": verification_hash,
            "criterion_hashes": normalized_criteria,
        },
    }


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
    _version_present, version = _coalesce_aliases(
        workflow, ("version", "contract_version"), "workflow version"
    )
    version = _text(version, "workflow version")
    if version != CONTRACT_VERSION:
        raise IssueDeliveryContractError("workflow version is not approved")
    _hash_present, declared_hash = _coalesce_aliases(
        workflow, ("content_hash", "workflow_hash"), "workflow hash"
    )
    if not _hash_present:
        raise IssueDeliveryContractError("workflow hash is required")
    workflow_hash = _sha(declared_hash, "workflow hash")
    entrypoint = _text(workflow.get("entrypoint"), "workflow entrypoint", limit=1024)
    if entrypoint != WORKFLOW_ENTRYPOINT:
        raise IssueDeliveryContractError("workflow entrypoint is not approved")
    launcher = _text(workflow.get("launcher"), "workflow launcher", limit=1024)
    if launcher != WORKFLOW_LAUNCHER:
        raise IssueDeliveryContractError("workflow launcher is not approved")
    _artifacts_present, artifacts_raw = _coalesce_aliases(
        workflow, ("artifacts", "artifact_manifest"), "workflow artifact manifest"
    )
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
    artifacts.sort(key=lambda item: item["path"])
    if paths != REQUIRED_WORKFLOW_ARTIFACTS:
        raise IssueDeliveryContractError("workflow artifact manifest is incomplete or unrelated")
    if workflow_hash != canonical_hash(artifacts):
        raise IssueDeliveryContractError("workflow hash does not bind its artifact manifest")
    return {
        **_without_aliases(
            workflow,
            frozenset({"contract_version", "workflow_hash", "artifact_manifest"}),
        ),
        "version": version,
        "content_hash": workflow_hash,
        "entrypoint": entrypoint,
        "launcher": launcher,
        "artifacts": artifacts,
    }


def _destination_fields(value: Any) -> dict[str, Any]:
    destination = _mapping(value, "destination")
    identity = _text(destination.get("identity"), "destination identity", limit=256)
    _run_present, run_id = _coalesce_aliases(
        destination, ("run_id", "proposed_run_id"), "proposed run identity"
    )
    run_id = _text(run_id, "proposed run identity", limit=256)
    required_text = {
        "host_identity": ("host_identity", "host"),
        "system_identity": ("system_identity", "system"),
        "checkout": ("checkout", "checkout_path"),
        "worktree": ("worktree", "worktree_path"),
        "branch": ("branch", "branch_name"),
        "channel": ("channel",),
        "base_ref": ("base_ref",),
    }
    resolved: dict[str, str] = {}
    for normalized_name, aliases in required_text.items():
        _present, candidate = _coalesce_aliases(
            destination, aliases, f"destination {normalized_name}"
        )
        resolved[normalized_name] = _text(candidate, f"destination {normalized_name}", limit=1024)
    base_sha = _text(destination.get("base_sha"), "observed destination base SHA", limit=40).lower()
    if _GIT_SHA.fullmatch(base_sha) is None:
        raise IssueDeliveryContractError("observed destination base SHA must be a Git commit")
    return {
        **_without_aliases(
            destination,
            frozenset(
                {
                    "proposed_run_id",
                    "host",
                    "system",
                    "checkout_path",
                    "worktree_path",
                    "branch_name",
                }
            ),
        ),
        "identity": identity,
        "run_id": run_id,
        **resolved,
        "base_sha": base_sha,
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

    _present, repository_value = _coalesce_aliases(
        parent, ("repository", "parent_repository"), "parent repository"
    )
    repository = canonical_repository(
        _text(repository_value, "parent repository", limit=256)
    )
    _present, number = _coalesce_aliases(
        parent, ("number", "parent_issue_number"), "parent Issue number"
    )
    if type(number) is not int or number < 1:
        raise IssueDeliveryContractError("exact parent Issue number is required")
    _present, node_id = _coalesce_aliases(
        parent, ("node_id", "parent_node_id"), "parent Issue node identity"
    )
    node_id = _text(node_id, "parent Issue node identity")
    if _NODE_ID.fullmatch(node_id) is None:
        raise IssueDeliveryContractError("parent Issue node identity is malformed")

    relationship = parent.get("relationship")
    if isinstance(relationship, Mapping):
        relationship = dict(relationship)
        _present, relation_kind = _coalesce_aliases(
            relationship, ("kind", "type"), "parent Issue relationship"
        )
        relation_kind = _text(relation_kind, "parent Issue relationship", limit=64)
        _relation_number_present, related_issue_number = _coalesce_aliases(
            relationship,
            ("child_issue_number", "issue_number"),
            "parent child Issue number",
        )
        _authenticated_present, authenticated = _coalesce_aliases(
            relationship, ("authenticated",), "parent relationship authentication"
        )
        _parent_number_present, parent_number = _coalesce_aliases(
            parent,
            ("child_issue_number", "issue_number"),
            "parent child Issue number",
        )
        if _parent_number_present:
            if _relation_number_present and parent_number != related_issue_number:
                raise IssueDeliveryContractError("parent child Issue number aliases disagree")
            related_issue_number = parent_number
        _parent_auth_present, parent_auth = _coalesce_aliases(
            parent,
            ("relationship_authenticated", "authenticated"),
            "parent relationship authentication",
        )
        if _parent_auth_present:
            if _authenticated_present and parent_auth != authenticated:
                raise IssueDeliveryContractError(
                    "parent relationship authentication aliases disagree"
                )
            authenticated = parent_auth
    else:
        relation_kind = _text(relationship, "parent Issue relationship", limit=64)
        _present, related_issue_number = _coalesce_aliases(
            parent,
            ("child_issue_number", "issue_number"),
            "parent child Issue number",
        )
        _present, authenticated = _coalesce_aliases(
            parent,
            ("relationship_authenticated", "authenticated"),
            "parent relationship authentication",
        )
    if relation_kind not in {"parent", "parent-child", "child-of"}:
        raise IssueDeliveryContractError("parent Issue relationship is unsupported")
    if related_issue_number != issue_number or authenticated is not True:
        raise IssueDeliveryContractError("parent Issue relationship is not source-authenticated")

    _present, contract_version = _coalesce_aliases(
        parent, ("contract_version", "version"), "parent contract version"
    )
    contract_version = _text(contract_version, "parent contract version")
    _present, contract_hash = _coalesce_aliases(
        parent, ("contract_hash", "content_hash"), "parent contract hash"
    )
    contract_hash = _sha(contract_hash, "parent contract hash")
    _present, write_permission_value = _coalesce_aliases(
        parent, ("write_permission", "permission"), "parent write permission"
    )
    write_permission = _mapping(write_permission_value, "parent write permission")
    _present, permission_scope = _coalesce_aliases(
        write_permission,
        ("scope", "grant"),
        "parent write permission scope",
    )
    permission_scope = _text(permission_scope, "parent write permission scope")
    _present, writes = _coalesce_aliases(
        write_permission,
        ("effects", "writes", "targets"),
        "parent write permission targets",
    )
    if not isinstance(writes, (list, tuple)) or not writes:
        raise IssueDeliveryContractError("parent write permission targets are required")
    writes = _list_of_text(writes, "parent write permission targets")
    required_writes = {"pr_receipt_comments", "child_generated_ledger_writeback"}
    if set(writes) != required_writes or permission_scope != "parent_evidence:write":
        raise IssueDeliveryContractError("parent write permission is not exact")
    normalized_parent = _without_aliases(
        parent,
        frozenset(
            {
                "parent_repository",
                "parent_issue_number",
                "parent_node_id",
                "child_issue_number",
                "issue_number",
                "relationship_authenticated",
                "version",
                "content_hash",
                "permission",
            }
        ),
    )
    return {
        **normalized_parent,
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
        "write_permission": {
            **_without_aliases(write_permission, frozenset({"grant", "writes", "targets"})),
            "scope": permission_scope,
            "effects": writes,
        },
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
        if repository != QUALIFIED_REPOSITORY:
            raise IssueDeliveryContractError(
                "Issue-delivery admission is not qualified for this repository"
            )
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
        _context_present, context_value = _coalesce_aliases(
            raw,
            ("context", "context_pack", "context_pack_ref"),
            "context binding",
        )
        destination = _destination_fields(raw.get("destination"))
        context = _context_fields(
            context_value, issue_number=issue["number"], channel=destination["channel"]
        )
        workflow = _workflow_fields(raw.get("workflow"))
        profile = _execution_profile_fields(raw.get("profile"))
        selected_context = context["dispatch_plan"]["context_packs"][0]
        runtime = selected_context["runtime"]
        resolved = profile["resolved"]
        dispatch_plan = context["dispatch_plan"]
        branch_worktree_plan = selected_context["branch_worktree_plan"]
        context_issue = selected_context["issue_contract"]
        expected_issue_url = (
            f"https://github.com/{repository}/issues/{issue['number']}"
        )
        if issue["url"].casefold() != expected_issue_url.casefold():
            raise IssueDeliveryContractError(
                "approved Issue URL does not bind the canonical repository and number"
            )
        context_repository = canonical_repository(
            _text(context_issue.get("repository"), "context Issue repository")
        )
        if (
            context_repository != repository
            or context_issue.get("number") != issue["number"]
            or context_issue.get("title") != issue["title"]
            or not isinstance(context_issue.get("url"), str)
            or context_issue["url"].casefold() != expected_issue_url.casefold()
            or context_issue.get("scope") != issue["scope"]
        ):
            raise IssueDeliveryContractError(
                "frozen dispatch Issue contract does not match the approved Issue"
            )
        if (
            destination["run_id"] != dispatch_plan["run_id"]
            or destination["branch"] != branch_worktree_plan["branch"]
            or destination["worktree"] != branch_worktree_plan["worktree"]
        ):
            raise IssueDeliveryContractError(
                "destination identity must match the frozen dispatch plan"
            )
        checkout_path = normpath(destination["checkout"])
        worktree_path = normpath(destination["worktree"])
        if (
            not destination["checkout"].startswith("/")
            or not destination["worktree"].startswith("/")
            or checkout_path == "/"
            or worktree_path in {checkout_path, "/"}
        ):
            raise IssueDeliveryContractError(
                "destination worktree must be isolated from the checkout and root"
            )
        branch = destination["branch"].removeprefix("refs/heads/")
        base_ref = destination["base_ref"].removeprefix("refs/heads/")
        if branch == base_ref:
            raise IssueDeliveryContractError(
                "destination branch must be isolated from the base ref"
            )
        for field in ("carrier", "selection_intent", "capability"):
            approved_value = (
                profile["selection_intent"]
                if field == "selection_intent"
                else resolved[field]
            )
            if runtime.get(field) != approved_value:
                raise IssueDeliveryContractError(
                    f"execution profile {field} does not match the frozen dispatch context"
                )
        if (
            runtime.get("model") != resolved["model"]
            or runtime.get("reasoning_effort") != resolved["reasoning_effort"]
        ):
            raise IssueDeliveryContractError(
                "execution profile target does not match the frozen dispatch context"
            )
        effects = _list_of_text(raw.get("permitted_effects"), "permitted effects")
        non_effects = _list_of_text(raw.get("explicit_non_effects"), "explicit non-effects")
        if set(effects) & set(non_effects):
            raise IssueDeliveryContractError("permitted and non-effect sets must be disjoint")
        if set(effects) != PERMITTED_EFFECTS:
            raise IssueDeliveryContractError("permitted effects do not match the closed delivery set")
        if set(non_effects) != NON_EFFECTS:
            raise IssueDeliveryContractError("explicit non-effects do not match the closed delivery set")
        parent = _parent_evidence(raw.get("parent_evidence"), issue_number=issue["number"])
        if parent.get("kind") == "issue" and (
            parent.get("repository") == repository
            and (
                parent.get("number") == issue["number"]
                or parent.get("node_id") == issue["node_id"]
            )
        ):
            raise IssueDeliveryContractError(
                "parent evidence must not refer to the addressed Issue"
            )
        owner_profile = _mapping(raw.get("owner_profile"), "owner profile")
        profile_principal = owner_profile.get(
            "principal", owner_profile.get("owner_principal")
        )
        profile_principal = _text(profile_principal, "owner profile principal", limit=256)
        legacy_profile_principal = owner_profile.get("owner_principal")
        if legacy_profile_principal is not None and legacy_profile_principal != profile_principal:
            raise IssueDeliveryContractError(
                "owner profile principal bindings disagree"
            )
        raw = _without_aliases(
            raw,
            _TOP_LEVEL_ISSUE_ALIASES
            | _TOP_LEVEL_SOURCE_ALIASES
            | _TOP_LEVEL_CONTEXT_ALIASES,
        )
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
            "owner_profile": {**owner_profile, "principal": profile_principal},
        }
        return result
    except IssueDeliveryContractError:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IssueDeliveryContractError("invalid Issue-delivery manifest") from exc


def manifest_hash(value: Mapping[str, Any]) -> str:
    return canonical_hash({key: item for key, item in value.items() if key not in _NON_BINDING_FIELDS})


def approval_digest(value: Mapping[str, Any]) -> str:
    """Hash the complete durable approval, including its grant timestamp."""

    return canonical_hash(
        {key: item for key, item in value.items() if key != "approval_digest"}
    )


def record_id(approval_id: str) -> str:
    return RECORD_PREFIX + approval_id


def receipt_ref(repository: str, approval_id: str) -> str:
    """Return the service-owned durable receipt reference for an approval."""

    return (
        "builderops:record:"
        + canonical_repository(repository)
        + ":"
        + record_id(approval_id)
    )


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
    "receipt_ref",
    "canonical_hash",
    "approval_digest",
    "idempotency_key",
    "manifest_hash",
    "normalize_manifest",
    "record_id",
    "strip_server_fields",
]
