"""Transport-neutral public contracts for CKM measurement and access.

This module deliberately contains no query executor.  It defines the stable
identity, snapshot, envelope, value-state, ordering, and completeness vocabulary that
the Q1b read path must implement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from app.builderops.ckm.schema import CKM_SCHEMA_VERSION

JsonDict = dict[str, Any]

ENVELOPE_SCHEMA_VERSION = 1
RESOURCE_SCHEMA_VERSION = 1
ACCESS_POLICY_VERSION = "ckm-local-access-v1"
EFFECTIVE_AUDIENCE = "single_operator_local"
REDACTION_PROFILE = "none"

SUPPORTED_RESOURCE_TYPES = frozenset(
    {"capability", "artifact", "evidence_edge", "assessment", "finding"}
)
SUPPORTED_VALUE_STATES = frozenset(
    {"measured", "missing", "unassessed", "unsupported"}
)
SUPPORTED_HISTORY_MODES = frozenset({"current"})


def canonical_json(value: Any) -> str:
    """Return the single canonical JSON representation used by public digests."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_public_id(resource_type: str, identity_key: str) -> str:
    """Derive a rebuild-stable opaque identifier from a durable semantic key."""

    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise CkmContractError(
            code="unsupported_resource",
            message=f"unsupported CKM resource type: {resource_type}",
            details={"resource_type": resource_type},
        )
    if not isinstance(identity_key, str) or not identity_key.strip():
        raise ValueError("identity_key must be a non-empty string")
    digest = hashlib.sha256(
        f"ckm-public-id-v1\0{resource_type}\0{identity_key}".encode("utf-8")
    ).hexdigest()[:32]
    return f"ckm_{resource_type}_{digest}"


@dataclass(frozen=True)
class CkmContractError(ValueError):
    """Typed refusal returned by every transport without fallback semantics."""

    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> JsonDict:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class TaggedValue:
    """A value whose absence semantics cannot be confused with measured zero."""

    state: str
    value: Any = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in SUPPORTED_VALUE_STATES:
            raise ValueError(f"unsupported tagged value state: {self.state}")
        if self.state == "measured":
            if self.value is None:
                raise ValueError("measured values must carry a value; use a tagged absence state")
            if self.reason is not None:
                raise ValueError("measured values must not carry a refusal reason")
        else:
            if self.value is not None:
                raise ValueError(f"{self.state} values must not carry a measured value")
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError(f"{self.state} values must carry a non-empty reason")

    @classmethod
    def measured(cls, value: Any) -> "TaggedValue":
        return cls(state="measured", value=value)

    @classmethod
    def missing(cls, reason: str) -> "TaggedValue":
        return cls(state="missing", reason=reason)

    @classmethod
    def unassessed(cls, reason: str) -> "TaggedValue":
        return cls(state="unassessed", reason=reason)

    @classmethod
    def unsupported(cls, reason: str) -> "TaggedValue":
        return cls(state="unsupported", reason=reason)

    def to_dict(self) -> JsonDict:
        payload: JsonDict = {"state": self.state}
        if self.state == "measured":
            payload["value"] = self.value
        else:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class ProjectionMarker:
    status: str = "derived_projection"
    authoritative: bool = False


@dataclass(frozen=True)
class CkmStateIdentity:
    epoch: str
    state_revision: int
    schema_version: int = CKM_SCHEMA_VERSION

    def to_dict(self) -> JsonDict:
        return asdict(self)


@dataclass(frozen=True)
class ObjectClassCompleteness:
    """Accounting for one object class in a bounded complete capture."""

    object_class: str
    included: int
    filtered: int = 0
    omitted: int = 0
    truncated: int = 0

    def __post_init__(self) -> None:
        if self.object_class not in SUPPORTED_RESOURCE_TYPES:
            raise ValueError(f"unsupported completeness object class: {self.object_class}")
        if min(self.included, self.filtered, self.omitted, self.truncated) < 0:
            raise ValueError("completeness counts must be non-negative")


@dataclass(frozen=True)
class CompletenessManifest:
    """Proves whether every declared object class was accounted for completely."""

    object_classes: Sequence[ObjectClassCompleteness]
    complete: bool

    def __post_init__(self) -> None:
        names = [item.object_class for item in self.object_classes]
        if not names or len(names) != len(set(names)):
            raise ValueError("completeness manifest needs distinct object classes")
        actually_complete = all(
            item.omitted == 0 and item.truncated == 0 for item in self.object_classes
        )
        if self.complete != actually_complete:
            raise ValueError("complete must agree with omitted and truncated accounting")

    def to_dict(self) -> JsonDict:
        return {
            "complete": self.complete,
            "object_classes": [asdict(item) for item in self.object_classes],
        }


@dataclass(frozen=True)
class SnapshotManifest:
    epoch: str
    state_revision: int
    ckm_schema_version: int
    envelope_schema_version: int
    resource_schema_version: int
    taxonomy_digest: str
    watermarks: Mapping[str, str]
    provenance: Sequence[Mapping[str, Any]]
    effective_audience: str
    access_policy_version: str
    redaction_profile: str
    completeness: CompletenessManifest
    read_set_digest: str
    snapshot_digest: str

    @classmethod
    def build(
        cls,
        *,
        state: CkmStateIdentity,
        taxonomy_digest: str,
        watermarks: Mapping[str, str],
        provenance: Sequence[Mapping[str, Any]],
        completeness: CompletenessManifest,
        read_set: Any,
    ) -> "SnapshotManifest":
        unsigned: JsonDict = {
            "epoch": state.epoch,
            "state_revision": state.state_revision,
            "ckm_schema_version": state.schema_version,
            "envelope_schema_version": ENVELOPE_SCHEMA_VERSION,
            "resource_schema_version": RESOURCE_SCHEMA_VERSION,
            "taxonomy_digest": taxonomy_digest,
            "watermarks": dict(sorted(watermarks.items())),
            "provenance": [dict(item) for item in provenance],
            "effective_audience": EFFECTIVE_AUDIENCE,
            "access_policy_version": ACCESS_POLICY_VERSION,
            "redaction_profile": REDACTION_PROFILE,
            "completeness": completeness.to_dict(),
            "read_set_digest": canonical_digest(read_set),
        }
        return cls(
            **{key: value for key, value in unsigned.items() if key != "completeness"},
            completeness=completeness,
            snapshot_digest=canonical_digest(unsigned),
        )

    def to_dict(self) -> JsonDict:
        return {
            **asdict(self),
            "watermarks": dict(sorted(self.watermarks.items())),
            "provenance": [dict(item) for item in self.provenance],
            "completeness": self.completeness.to_dict(),
        }


@dataclass(frozen=True)
class ResourceDto:
    public_id: str
    resource_type: str
    display_name: str
    lifecycle: str
    provenance: Sequence[Mapping[str, Any]]
    values: Mapping[str, TaggedValue]
    candidate: bool
    schema_version: int = RESOURCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.resource_type not in SUPPORTED_RESOURCE_TYPES:
            raise ValueError(f"unsupported CKM resource type: {self.resource_type}")
        if not self.public_id or not self.display_name:
            raise ValueError("resource public_id and display_name must not be empty")
        if not self.provenance:
            raise ValueError("resource provenance must not be empty")
        if self.candidate != (self.lifecycle == "candidate"):
            raise ValueError("candidate marker must agree with lifecycle")

    @property
    def total_order_key(self) -> tuple[str, str]:
        return (self.resource_type, self.public_id)

    def to_dict(self) -> JsonDict:
        return {
            "public_id": self.public_id,
            "resource_type": self.resource_type,
            "schema_version": self.schema_version,
            "display_name": self.display_name,
            "lifecycle": self.lifecycle,
            "candidate": self.candidate,
            "provenance": [dict(item) for item in self.provenance],
            "values": {key: value.to_dict() for key, value in sorted(self.values.items())},
        }


@dataclass(frozen=True)
class ResultEnvelope:
    resource_type: str
    query_digest: str
    snapshot: SnapshotManifest
    resources: Sequence[ResourceDto]
    projection: ProjectionMarker = field(default_factory=ProjectionMarker)
    schema_version: int = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if any(resource.resource_type != self.resource_type for resource in self.resources):
            raise ValueError("every resource must match the envelope resource type")
        if not self.snapshot.completeness.complete:
            raise ValueError("result envelopes cannot contain an incomplete snapshot")
        keys = [resource.total_order_key for resource in self.resources]
        if keys != sorted(keys):
            raise ValueError("resources must use the stable public total order")

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": self.schema_version,
            "resource_type": self.resource_type,
            "query_digest": self.query_digest,
            "projection": asdict(self.projection),
            "snapshot": self.snapshot.to_dict(),
            "resources": [resource.to_dict() for resource in self.resources],
        }


@dataclass(frozen=True)
class ErrorEnvelope:
    error: CkmContractError
    schema_version: int = ENVELOPE_SCHEMA_VERSION

    def to_dict(self) -> JsonDict:
        return {
            "schema_version": self.schema_version,
            "error": self.error.to_dict(),
        }


def canonical_query_digest(query: Mapping[str, Any]) -> str:
    return canonical_digest(query)


def validate_contract_request(
    *,
    ckm_schema_version: Any = CKM_SCHEMA_VERSION,
    envelope_schema_version: Any = ENVELOPE_SCHEMA_VERSION,
    resource_schema_version: Any = RESOURCE_SCHEMA_VERSION,
    resource_type: Any,
    effective_audience: Any = EFFECTIVE_AUDIENCE,
    access_policy_version: Any = ACCESS_POLICY_VERSION,
    redaction_profile: Any = REDACTION_PROFILE,
    filters: Mapping[str, Any] | None = None,
    supported_filters: frozenset[str] = frozenset(),
    history_mode: str = "current",
) -> None:
    versions = {
        "ckm": (ckm_schema_version, CKM_SCHEMA_VERSION),
        "envelope": (envelope_schema_version, ENVELOPE_SCHEMA_VERSION),
        "resource": (resource_schema_version, RESOURCE_SCHEMA_VERSION),
    }
    for kind, (requested, supported) in versions.items():
        if requested != supported:
            raise CkmContractError(
                code="unsupported_version",
                message=f"unsupported {kind} schema version: {requested}",
                details={"schema": kind, "requested": requested, "supported": [supported]},
            )
    policy = {
        "effective_audience": (effective_audience, EFFECTIVE_AUDIENCE),
        "access_policy_version": (access_policy_version, ACCESS_POLICY_VERSION),
        "redaction_profile": (redaction_profile, REDACTION_PROFILE),
    }
    mismatches = {
        key: requested
        for key, (requested, supported) in policy.items()
        if requested != supported
    }
    if mismatches:
        raise CkmContractError(
            code="unsupported_access_policy",
            message="unsupported or ambiguous CKM access policy",
            details={"requested": mismatches},
        )
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        raise CkmContractError(
            code="unsupported_resource",
            message=f"unsupported CKM resource type: {resource_type}",
            details={"resource_type": resource_type},
        )
    unknown_filters = sorted(set(filters or {}) - set(supported_filters))
    if unknown_filters:
        raise CkmContractError(
            code="unsupported_filter",
            message=f"unsupported filter(s): {', '.join(unknown_filters)}",
            details={"filters": unknown_filters},
        )
    if history_mode not in SUPPORTED_HISTORY_MODES:
        raise CkmContractError(
            code="unsupported_historical_semantics",
            message=f"unsupported historical semantics: {history_mode}",
            details={"history_mode": history_mode},
        )
