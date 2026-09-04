"""Provider-free ``ygg.operation.v1`` vocabulary.

This package is deliberately declarative: it does not select adapters, dispatch
operations, or write domain state.  Domain payloads remain opaque mappings owned
by their existing subsystem models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class OperationStatus(StrEnum):
    """Terminal and recoverable outcomes defined by the operation envelope."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    NOT_SUPPORTED = "not_supported"
    NOT_ACKNOWLEDGED = "not_acknowledged"
    RECOVERY_REQUIRED = "recovery_required"
    CONVERGENCE_PENDING = "convergence_pending"
    DEGRADED_READ = "degraded_read"


class CapabilitySupport(StrEnum):
    SUPPORTED = "supported"
    POLICY_DISABLED = "policy_disabled"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class OperationContext:
    active_context_ref: str
    vault_generation: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"active_context_ref": self.active_context_ref, "vault_generation": self.vault_generation, "extensions": dict(self.extensions)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationContext":
        return cls(str(value["active_context_ref"]), value.get("vault_generation"), dict(value.get("extensions", {})))


@dataclass(frozen=True)
class OperationRequest:
    operation_id: str
    request_id: str
    context: OperationContext
    targets: tuple[Mapping[str, Any], ...] = ()
    arguments: Mapping[str, Any] = field(default_factory=dict)
    operation_version: str = "ygg.operation.v1"
    mode: str = "execute"
    expected_version: str | int | None = None
    delegation: Mapping[str, Any] | None = None
    batch_policy: Mapping[str, Any] | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"operation_id": self.operation_id, "operation_version": self.operation_version, "request_id": self.request_id, "context": self.context.to_dict(), "targets": [dict(target) for target in self.targets], "arguments": dict(self.arguments), "mode": self.mode, "expected_version": self.expected_version, "delegation": None if self.delegation is None else dict(self.delegation), "batch_policy": None if self.batch_policy is None else dict(self.batch_policy), "extensions": dict(self.extensions)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationRequest":
        return cls(operation_id=str(value["operation_id"]), request_id=str(value["request_id"]), context=OperationContext.from_dict(value["context"]), targets=tuple(dict(item) for item in value.get("targets", ())), arguments=dict(value.get("arguments", {})), operation_version=str(value.get("operation_version", "ygg.operation.v1")), mode=str(value.get("mode", "execute")), expected_version=value.get("expected_version"), delegation=None if value.get("delegation") is None else dict(value["delegation"]), batch_policy=None if value.get("batch_policy") is None else dict(value["batch_policy"]), extensions=dict(value.get("extensions", {})))


@dataclass(frozen=True)
class OperationOutcome:
    request_id: str
    status: OperationStatus
    operation_id: str
    context: OperationContext
    items: tuple[Mapping[str, Any], ...] = ()
    conflict: Mapping[str, Any] | None = None
    receipt: Mapping[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "status": self.status.value, "operation_id": self.operation_id, "context": self.context.to_dict(), "items": [dict(item) for item in self.items], "conflict": None if self.conflict is None else dict(self.conflict), "receipt": None if self.receipt is None else dict(self.receipt), "warnings": list(self.warnings), "extensions": dict(self.extensions)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationOutcome":
        return cls(request_id=str(value["request_id"]), status=OperationStatus(value["status"]), operation_id=str(value["operation_id"]), context=OperationContext.from_dict(value["context"]), items=tuple(dict(item) for item in value.get("items", ())), conflict=None if value.get("conflict") is None else dict(value["conflict"]), receipt=None if value.get("receipt") is None else dict(value["receipt"]), warnings=tuple(str(item) for item in value.get("warnings", ())), extensions=dict(value.get("extensions", {})))


@dataclass(frozen=True)
class CapabilityAvailability:
    operation_id: str
    support: CapabilitySupport
    reason: str | None = None
    operation_version: str = "ygg.operation.v1"
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityDiscovery:
    capabilities: tuple[CapabilityAvailability, ...]

    def for_operation(self, operation_id: str) -> CapabilityAvailability | None:
        return next((item for item in self.capabilities if item.operation_id == operation_id), None)
