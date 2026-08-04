"""Validation helpers for BuilderOps Vault records.

The implementation validates the object envelope and required fields from the
object model, then stores the full record as JSON. Store-level leases,
idempotency keys, and transition receipts are layered around this record
contract without changing the object semantics exposed here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

JsonDict = dict[str, Any]

AUTHORITY_CLASSES = frozenset({
    "raw",
    "operational",
    "analytical",
    "staged",
    "decision",
    "projection",
    "receipt",
})

LIFECYCLE_STATES = frozenset({
    "draft",
    "active",
    "review_pending",
    "accepted",
    "promoted",
    "projected",
    "archived",
    "discarded",
    "superseded",
})

PROMOTION_STATUSES = frozenset({
    "none",
    "not_promotable",
    "candidate",
    "promotion_pending",
    "promoted",
    "rejected",
    "discarded",
    "superseded",
})

# Canonical PromotionIntent target-surface registry (issue #4171).
#
# This is the single validation authority for `target_authority_surface`:
# store creation (`SqliteBuilderOpsStore.create_record`) and the promotion
# gateway's transition path both resolve targets through
# `canonicalize_promotion_target_surface`, so a record can never be created
# with a target the gateway later refuses to transition.
PROMOTION_TARGET_SURFACES = frozenset({
    "github_issue",
    "pr_branch_proposal",
    "adr_doc_proposal",
    "owner_doc_writeback_proposal",
    "generated_projection",
    "discard_receipt",
})

PROMOTION_TARGET_ALIASES: dict[str, str] = {
    "github": "github_issue",
    "github_issue": "github_issue",
    "issue": "github_issue",
    "pr": "pr_branch_proposal",
    "pull_request": "pr_branch_proposal",
    "branch": "pr_branch_proposal",
    "pr_branch_proposal": "pr_branch_proposal",
    "adr": "adr_doc_proposal",
    "decision_doc": "adr_doc_proposal",
    "adr_doc_proposal": "adr_doc_proposal",
    "repo_doc": "owner_doc_writeback_proposal",
    "repo_skill": "owner_doc_writeback_proposal",
    "repo_skill_and_workflow_doc": "owner_doc_writeback_proposal",
    "owner_doc": "owner_doc_writeback_proposal",
    "doc_writeback": "owner_doc_writeback_proposal",
    "owner_doc_writeback_proposal": "owner_doc_writeback_proposal",
    "skill": "owner_doc_writeback_proposal",
    "skill_or_agents_proposal": "owner_doc_writeback_proposal",
    "workflow_doc": "owner_doc_writeback_proposal",
    "agents_md": "owner_doc_writeback_proposal",
    "generated_projection": "generated_projection",
    "projection": "generated_projection",
    "discard": "discard_receipt",
    "discard_receipt": "discard_receipt",
}

OBJECT_PREFIXES = {
    "AgentWorklog": "awl",
    "LearningSignal": "lrn",
    "RetroCluster": "retro",
    "BuilderDecision": "dec",
    "PromotionIntent": "prom",
    "DocsFreshnessRecord": "docsfresh",
    "RoadmapExecutionItem": "roadexec",
    "BuilderOpsReceipt": "receipt",
}

OBJECT_DEFAULTS: dict[str, JsonDict] = {
    "AgentWorklog": {
        "authority_class": "raw",
        "lifecycle_state": "active",
        "promotion_status": "none",
        "task_context": {},
        "receipt_refs": [],
    },
    "LearningSignal": {
        "authority_class": "operational",
        "lifecycle_state": "active",
        "promotion_status": "candidate",
        "receipt_refs": [],
    },
    "RetroCluster": {
        "authority_class": "analytical",
        "lifecycle_state": "active",
        "promotion_status": "candidate",
        "receipt_refs": [],
    },
    "BuilderDecision": {
        "authority_class": "decision",
        "lifecycle_state": "review_pending",
        "promotion_status": "none",
        "decision_domain": "builderops",
        "receipt_refs": [],
    },
    "PromotionIntent": {
        "authority_class": "staged",
        "lifecycle_state": "review_pending",
        "promotion_status": "promotion_pending",
        "receipt_refs": [],
    },
    "DocsFreshnessRecord": {
        "authority_class": "operational",
        "lifecycle_state": "active",
        "promotion_status": "none",
        "receipt_refs": [],
    },
    "RoadmapExecutionItem": {
        "authority_class": "operational",
        "lifecycle_state": "active",
        "promotion_status": "none",
        "receipt_refs": [],
    },
    "BuilderOpsReceipt": {
        "authority_class": "receipt",
        "lifecycle_state": "active",
        "promotion_status": "not_promotable",
    },
}

ALLOWED_AUTHORITY_BY_TYPE: dict[str, frozenset[str]] = {
    "AgentWorklog": frozenset({"raw", "operational"}),
    "LearningSignal": frozenset({"operational", "analytical"}),
    "RetroCluster": frozenset({"analytical"}),
    "BuilderDecision": frozenset({"decision"}),
    "PromotionIntent": frozenset({"staged"}),
    "DocsFreshnessRecord": frozenset({"operational"}),
    "RoadmapExecutionItem": frozenset({"operational"}),
    "BuilderOpsReceipt": frozenset({"receipt"}),
}

ALLOWED_LIFECYCLE_BY_TYPE: dict[str, frozenset[str]] = {
    "AgentWorklog": frozenset({
        "draft",
        "active",
        "review_pending",
        "promoted",
        "archived",
        "discarded",
        "superseded",
    }),
    "LearningSignal": frozenset({
        "draft",
        "active",
        "review_pending",
        "accepted",
        "promoted",
        "archived",
        "discarded",
        "superseded",
    }),
    "RetroCluster": frozenset({
        "draft",
        "active",
        "review_pending",
        "accepted",
        "promoted",
        "archived",
        "discarded",
        "superseded",
    }),
    "BuilderDecision": frozenset({
        "draft",
        "review_pending",
        "accepted",
        "promoted",
        "archived",
        "superseded",
    }),
    "PromotionIntent": frozenset({
        "draft",
        "review_pending",
        "accepted",
        "promoted",
        "discarded",
        "superseded",
    }),
    "DocsFreshnessRecord": frozenset({
        "draft",
        "active",
        "review_pending",
        "projected",
        "archived",
        "discarded",
        "superseded",
    }),
    "RoadmapExecutionItem": frozenset({
        "draft",
        "active",
        "review_pending",
        "promoted",
        "projected",
        "archived",
        "discarded",
        "superseded",
    }),
    "BuilderOpsReceipt": frozenset({"active", "archived", "superseded"}),
}

REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "AgentWorklog": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "body",
        "task_context",
        "receipt_refs",
    }),
    "LearningSignal": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "content",
        "signal_type",
        "receipt_refs",
    }),
    "RetroCluster": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "analysis",
        "cluster_subject",
        "member_refs",
        "receipt_refs",
    }),
    "BuilderDecision": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "decision_statement",
        "decision_scope",
        "decision_domain",
        "rationale",
        "receipt_refs",
    }),
    "PromotionIntent": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "target_authority_surface",
        "target_action",
        "target_ref",
        "target_authority_class",
        "intended_output",
        "receipt_refs",
    }),
    "DocsFreshnessRecord": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "doc_ref",
        "owner",
        "review_cadence",
        "freshness_posture",
        "last_reviewed_at",
        "next_review_due_at",
        "receipt_refs",
    }),
    "RoadmapExecutionItem": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "roadmap_ref",
        "execution_state",
        "owner",
        "next_decision",
        "receipt_refs",
    }),
    "BuilderOpsReceipt": frozenset({
        "id",
        "object_type",
        "authority_class",
        "lifecycle_state",
        "promotion_status",
        "created_at",
        "updated_at",
        "created_by",
        "source_refs",
        "summary",
        "event_type",
        "actor",
        "occurred_at",
        "target_refs",
        "action",
        "receipt_body",
        "idempotency_key",
    }),
}

NONEMPTY_LIST_FIELDS = frozenset({"source_refs", "member_refs", "target_refs"})
SOURCE_REF_LIST_FIELDS = frozenset({
    "active_issues",
    "freshness_evidence_refs",
    "last_verified_against",
    "shipped_refs",
    "source_refs",
    "successor_refs",
    "target_refs",
})

# Terminal LearningSignal dispositions must name the artifact that enacted or
# explicitly declined the divergence (issue #4267): a bare `superseded` or
# `discarded` status transition with no linked successor artifact reads as
# "handled" while the underlying defect stays unrepaired.
TERMINAL_SIGNAL_LIFECYCLE_STATES = frozenset({"discarded", "superseded"})
SUCCESSOR_REF_TYPES = frozenset({"github_issue", "github_pr", "promotion_intent"})


class BuilderOpsValidationError(ValueError):
    """Raised when a BuilderOps record does not satisfy the schema contract."""


class BuilderOpsConflictError(BuilderOpsValidationError):
    """Raised when a write conflicts with an existing BuilderOps safety guard."""


class BuilderOpsLeaseError(BuilderOpsValidationError):
    """Raised when a material update lacks a valid BuilderOps lease."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_record_id(object_type: str) -> str:
    prefix = OBJECT_PREFIXES[object_type]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}_{uuid4().hex[:8]}"


def normalize_actor(value: Mapping[str, Any] | str | None) -> JsonDict:
    if value is None:
        return {"actor_type": "agent", "id": "cli"}
    if isinstance(value, str):
        actor_id = value.strip()
        if not actor_id:
            raise BuilderOpsValidationError("actor id must not be empty")
        return {"actor_type": "agent", "id": actor_id}
    actor = dict(value)
    if not actor.get("actor_type") or not actor.get("id"):
        raise BuilderOpsValidationError("actor requires actor_type and id")
    return actor


def canonicalize_promotion_target_surface(value: Any) -> str:
    """Resolve a PromotionIntent target surface to its canonical registry name.

    Raises the canonical allowed-value error for surfaces outside
    ``PROMOTION_TARGET_SURFACES``. Both store creation and the promotion
    gateway validate through this single function (issue #4171).
    """
    raw = str(value if value is not None else "").strip().lower()
    normalized = raw.replace("-", "_").replace(" ", "_")
    canonical = PROMOTION_TARGET_ALIASES.get(normalized)
    if canonical is None:
        allowed = ", ".join(sorted(PROMOTION_TARGET_SURFACES))
        raise BuilderOpsValidationError(
            f"unsupported promotion target_authority_surface: {raw}; allowed: {allowed}"
        )
    return canonical


def validate_source_refs(value: Any, field_name: str = "source_refs") -> None:
    if not isinstance(value, list) or not value:
        raise BuilderOpsValidationError(f"{field_name} must be a non-empty list")
    for ref in value:
        if not isinstance(ref, dict):
            raise BuilderOpsValidationError(f"{field_name} entries must be objects")
        if not ref.get("ref_type") or not ref.get("ref"):
            raise BuilderOpsValidationError(f"{field_name} entries require ref_type and ref")


def validate_nonempty_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list) or not value:
        raise BuilderOpsValidationError(f"{field_name} must be a non-empty list")


def normalize_record(record: Mapping[str, Any]) -> JsonDict:
    data = dict(record)
    object_type = data.get("object_type")
    if object_type not in OBJECT_DEFAULTS:
        raise BuilderOpsValidationError(f"unsupported object_type: {object_type}")

    defaults = deepcopy(OBJECT_DEFAULTS[object_type])
    defaults.update(data)
    data = defaults
    data.setdefault("id", new_record_id(object_type))
    now = utc_now()
    data.setdefault("created_at", now)
    data.setdefault("updated_at", data["created_at"])
    data["created_by"] = normalize_actor(data.get("created_by"))
    if object_type == "BuilderOpsReceipt" and data.get("actor") is not None:
        data["actor"] = normalize_actor(data["actor"])

    if data["authority_class"] not in AUTHORITY_CLASSES:
        raise BuilderOpsValidationError(f"invalid authority_class: {data['authority_class']}")
    if data["lifecycle_state"] not in LIFECYCLE_STATES:
        raise BuilderOpsValidationError(f"invalid lifecycle_state: {data['lifecycle_state']}")
    if data["promotion_status"] not in PROMOTION_STATUSES:
        raise BuilderOpsValidationError(f"invalid promotion_status: {data['promotion_status']}")
    if data["authority_class"] not in ALLOWED_AUTHORITY_BY_TYPE[object_type]:
        allowed = ", ".join(sorted(ALLOWED_AUTHORITY_BY_TYPE[object_type]))
        raise BuilderOpsValidationError(
            f"{object_type} authority_class must be one of: {allowed}"
        )
    if data["lifecycle_state"] not in ALLOWED_LIFECYCLE_BY_TYPE[object_type]:
        allowed = ", ".join(sorted(ALLOWED_LIFECYCLE_BY_TYPE[object_type]))
        raise BuilderOpsValidationError(
            f"{object_type} lifecycle_state must be one of: {allowed}"
        )
    if object_type == "BuilderOpsReceipt" and data["promotion_status"] != "not_promotable":
        raise BuilderOpsValidationError("BuilderOpsReceipt promotion_status must be not_promotable")

    missing = [
        field
        for field in sorted(REQUIRED_FIELDS[object_type])
        if field not in data or data[field] is None or data[field] == ""
    ]
    if missing:
        raise BuilderOpsValidationError(
            f"{object_type} missing required field(s): {', '.join(missing)}"
        )

    for field in SOURCE_REF_LIST_FIELDS:
        if field in data:
            validate_source_refs(data[field], field)
    for field in NONEMPTY_LIST_FIELDS & REQUIRED_FIELDS[object_type]:
        if field not in SOURCE_REF_LIST_FIELDS:
            validate_nonempty_list(data[field], field)
    validate_source_refs(data["source_refs"])
    validate_terminal_signal_successor(data)
    return data


def validate_terminal_signal_successor(record: Mapping[str, Any]) -> None:
    """Require a linked successor artifact on terminal LearningSignal dispositions.

    A `LearningSignal` reaching `superseded` or `discarded` must name, in
    `successor_refs`, at least one Issue, PR, or PromotionIntent
    (`ref_type` in ``SUCCESSOR_REF_TYPES``) that actually enacted or explicitly
    declined the divergence. Enforced per
    `docs/architecture/SBS_OPERATING_MODEL.md :: Builder Learning, Evaluation,
    And TCD Governance Loop` (issue #4267).
    """

    if record.get("object_type") != "LearningSignal":
        return
    if record.get("lifecycle_state") not in TERMINAL_SIGNAL_LIFECYCLE_STATES:
        return
    successors = record.get("successor_refs")
    if not isinstance(successors, list) or not successors:
        raise BuilderOpsValidationError(
            "LearningSignal terminal disposition "
            f"'{record.get('lifecycle_state')}' requires successor_refs naming "
            "the Issue, PR, or PromotionIntent that enacted or explicitly "
            "declined the divergence"
        )
    validate_source_refs(successors, "successor_refs")
    if not any(ref.get("ref_type") in SUCCESSOR_REF_TYPES for ref in successors):
        allowed = ", ".join(sorted(SUCCESSOR_REF_TYPES))
        raise BuilderOpsValidationError(
            "LearningSignal terminal disposition "
            f"'{record.get('lifecycle_state')}' requires at least one "
            f"successor_refs entry with ref_type in: {allowed}"
        )
