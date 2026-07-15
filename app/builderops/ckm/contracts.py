"""Transport-neutral public contracts for CKM measurement and access.

This module deliberately contains no query executor.  It defines the stable
identity, snapshot, envelope, value-state, ordering, and cursor vocabulary that
the Q1b read path must implement.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from app.builderops.ckm.schema import CKM_SCHEMA_VERSION

JsonDict = dict[str, Any]

ENVELOPE_SCHEMA_VERSION = 1
RESOURCE_SCHEMA_VERSION = 1
CURSOR_SCHEMA_VERSION = 1

SUPPORTED_RESOURCE_TYPES = frozenset(
    {"capability", "artifact", "evidence_edge", "assessment", "finding"}
)
SUPPORTED_VALUE_STATES = frozenset(
    {"measured", "missing", "not_applicable", "unsupported"}
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
            if self.reason is not None:
                raise ValueError("measured values must not carry a refusal reason")
        elif self.value is not None:
            raise ValueError(f"{self.state} values must not carry a measured value")

    @classmethod
    def measured(cls, value: Any) -> "TaggedValue":
        return cls(state="measured", value=value)

    @classmethod
    def missing(cls, reason: str) -> "TaggedValue":
        return cls(state="missing", reason=reason)

    @classmethod
    def not_applicable(cls, reason: str) -> "TaggedValue":
        return cls(state="not_applicable", reason=reason)

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
class SnapshotManifest:
    epoch: str
    state_revision: int
    ckm_schema_version: int
    envelope_schema_version: int
    resource_schema_version: int
    taxonomy_digest: str
    watermarks: Mapping[str, str]
    provenance: Sequence[Mapping[str, Any]]
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
            "read_set_digest": canonical_digest(read_set),
        }
        return cls(**unsigned, snapshot_digest=canonical_digest(unsigned))

    def to_dict(self) -> JsonDict:
        return {
            **asdict(self),
            "watermarks": dict(sorted(self.watermarks.items())),
            "provenance": [dict(item) for item in self.provenance],
        }


@dataclass(frozen=True)
class TruncationMetadata:
    truncated: bool
    returned_count: int
    limit: int
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if self.returned_count < 0 or self.limit <= 0:
            raise ValueError("returned_count must be non-negative and limit must be positive")
        if self.truncated != (self.next_cursor is not None):
            raise ValueError("truncation and next_cursor must be stated together")


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
    truncation: TruncationMetadata
    projection: ProjectionMarker = field(default_factory=ProjectionMarker)
    schema_version: int = ENVELOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if any(resource.resource_type != self.resource_type for resource in self.resources):
            raise ValueError("every resource must match the envelope resource type")
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
            "truncation": asdict(self.truncation),
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


@dataclass(frozen=True)
class CursorPayload:
    resource_type: str
    query_digest: str
    snapshot_digest: str
    limit: int
    last_key: Sequence[str]
    envelope_schema_version: int = ENVELOPE_SCHEMA_VERSION
    resource_schema_version: int = RESOURCE_SCHEMA_VERSION
    cursor_schema_version: int = CURSOR_SCHEMA_VERSION

    def to_dict(self) -> JsonDict:
        return {
            "cursor_schema_version": self.cursor_schema_version,
            "envelope_schema_version": self.envelope_schema_version,
            "resource_schema_version": self.resource_schema_version,
            "resource_type": self.resource_type,
            "query_digest": self.query_digest,
            "snapshot_digest": self.snapshot_digest,
            "limit": self.limit,
            "last_key": list(self.last_key),
        }

    def encode(self, secret: bytes) -> str:
        if not secret:
            raise ValueError("cursor secret must not be empty")
        body = canonical_json(self.to_dict()).encode("utf-8")
        signature = hmac.new(secret, body, hashlib.sha256).digest()
        return f"{_b64url(body)}.{_b64url(signature)}"

    @classmethod
    def decode(cls, token: str, secret: bytes) -> "CursorPayload":
        try:
            encoded_body, encoded_signature = token.split(".", 1)
            body = _b64url_decode(encoded_body)
            signature = _b64url_decode(encoded_signature)
            expected = hmac.new(secret, body, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature mismatch")
            raw = json.loads(body)
            if not isinstance(raw, dict):
                raise ValueError("payload is not an object")
            validate_contract_request(
                envelope_schema_version=raw.get("envelope_schema_version"),
                resource_schema_version=raw.get("resource_schema_version"),
                cursor_schema_version=raw.get("cursor_schema_version"),
                resource_type=raw.get("resource_type"),
            )
            limit = raw.get("limit")
            last_key = raw.get("last_key")
            if not isinstance(limit, int) or limit <= 0:
                raise ValueError("limit must be a positive integer")
            if not isinstance(last_key, list) or not all(isinstance(v, str) for v in last_key):
                raise ValueError("last_key must be a list of strings")
            return cls(
                cursor_schema_version=raw["cursor_schema_version"],
                envelope_schema_version=raw["envelope_schema_version"],
                resource_schema_version=raw["resource_schema_version"],
                resource_type=raw["resource_type"],
                query_digest=str(raw.get("query_digest", "")),
                snapshot_digest=str(raw.get("snapshot_digest", "")),
                limit=limit,
                last_key=tuple(last_key),
            )
        except CkmContractError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CkmContractError(
                code="invalid_cursor",
                message="cursor is malformed or its signature is invalid",
            ) from exc

    def assert_bound_to(
        self,
        *,
        resource_type: str,
        query_digest: str,
        snapshot_digest: str,
        limit: int,
    ) -> None:
        actual = (self.resource_type, self.query_digest, self.snapshot_digest, self.limit)
        expected = (resource_type, query_digest, snapshot_digest, limit)
        if actual != expected:
            raise CkmContractError(
                code="cursor_binding_mismatch",
                message="cursor does not belong to this resource, query, snapshot, and limit",
            )


def validate_contract_request(
    *,
    ckm_schema_version: Any = CKM_SCHEMA_VERSION,
    envelope_schema_version: Any = ENVELOPE_SCHEMA_VERSION,
    resource_schema_version: Any = RESOURCE_SCHEMA_VERSION,
    cursor_schema_version: Any = CURSOR_SCHEMA_VERSION,
    resource_type: Any,
    filters: Mapping[str, Any] | None = None,
    supported_filters: frozenset[str] = frozenset(),
    history_mode: str = "current",
) -> None:
    versions = {
        "ckm": (ckm_schema_version, CKM_SCHEMA_VERSION),
        "envelope": (envelope_schema_version, ENVELOPE_SCHEMA_VERSION),
        "resource": (resource_schema_version, RESOURCE_SCHEMA_VERSION),
        "cursor": (cursor_schema_version, CURSOR_SCHEMA_VERSION),
    }
    for kind, (requested, supported) in versions.items():
        if requested != supported:
            raise CkmContractError(
                code="unsupported_version",
                message=f"unsupported {kind} schema version: {requested}",
                details={"schema": kind, "requested": requested, "supported": [supported]},
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


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
