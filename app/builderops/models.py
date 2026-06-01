"""Validation helpers for BuilderOps Vault records.

The implementation keeps the #1501 store intentionally small: it validates the
object envelope and required fields from the object model, then stores the full
record as JSON. Later issues can add leases, idempotency, and richer receipts
without changing the record contract exposed here.
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
SOURCE_REF_LIST_FIELDS = frozenset({"source_refs", "target_refs"})


class BuilderOpsValidationError(ValueError):
    """Raised when a BuilderOps record does not satisfy the schema contract."""


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

    if data["authority_class"] not in AUTHORITY_CLASSES:
        raise BuilderOpsValidationError(f"invalid authority_class: {data['authority_class']}")
    if data["lifecycle_state"] not in LIFECYCLE_STATES:
        raise BuilderOpsValidationError(f"invalid lifecycle_state: {data['lifecycle_state']}")
    if data["promotion_status"] not in PROMOTION_STATUSES:
        raise BuilderOpsValidationError(f"invalid promotion_status: {data['promotion_status']}")
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

    for field in NONEMPTY_LIST_FIELDS & REQUIRED_FIELDS[object_type]:
        if field in SOURCE_REF_LIST_FIELDS:
            validate_source_refs(data[field], field)
        else:
            validate_nonempty_list(data[field], field)
    validate_source_refs(data["source_refs"])
    return data
