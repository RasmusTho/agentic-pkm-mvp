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


class SourceEffectStatus(StrEnum):
    """State of the canonical source-of-truth effect."""

    NOT_APPLIED = "not_applied"
    COMMITTED = "committed"
    UNKNOWN = "unknown"


class ConvergenceState(StrEnum):
    """State of a derived consequence of a source effect."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    CONVERGED = "converged"
    DEGRADED = "degraded"
    REBUILD_REQUIRED = "rebuild_required"


class ReceiptStatus(StrEnum):
    """Terminality of the durable receipt required by an operation."""

    PENDING = "pending"
    COMMITTED = "committed"
    FAILED = "failed"


@dataclass(frozen=True)
class OperationContext:
    active_context_ref: str
    vault_generation: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_context_ref": self.active_context_ref,
            "vault_generation": self.vault_generation,
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationContext":
        return cls(
            str(value["active_context_ref"]),
            value.get("vault_generation"),
            dict(value.get("extensions", {})),
        )


@dataclass(frozen=True)
class OperationProvenance:
    """Cross-surface identity of the actor and client that invoked an operation."""

    actor: str
    client: str
    surface: str
    delegation: Mapping[str, Any] | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "client": self.client,
            "surface": self.surface,
            "delegation": None if self.delegation is None else dict(self.delegation),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationProvenance":
        return cls(
            actor=str(value["actor"]),
            client=str(value["client"]),
            surface=str(value["surface"]),
            delegation=None if value.get("delegation") is None else dict(value["delegation"]),
            extensions=dict(value.get("extensions", {})),
        )


@dataclass(frozen=True)
class OperationConvergence:
    """Separate source-effect success from Store, index, and link convergence."""

    source_effect: SourceEffectStatus
    store: ConvergenceState = ConvergenceState.NOT_REQUIRED
    index: ConvergenceState = ConvergenceState.NOT_REQUIRED
    link: ConvergenceState = ConvergenceState.NOT_REQUIRED
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_effect": self.source_effect.value,
            "store": self.store.value,
            "index": self.index.value,
            "link": self.link.value,
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationConvergence":
        return cls(
            source_effect=SourceEffectStatus(value["source_effect"]),
            store=ConvergenceState(value.get("store", ConvergenceState.NOT_REQUIRED)),
            index=ConvergenceState(value.get("index", ConvergenceState.NOT_REQUIRED)),
            link=ConvergenceState(value.get("link", ConvergenceState.NOT_REQUIRED)),
            extensions=dict(value.get("extensions", {})),
        )


@dataclass(frozen=True)
class OperationItemOutcome:
    """Schema-bound per-target envelope metadata with an opaque domain payload."""

    resource_id: str | None = None
    status: OperationStatus | None = None
    input_version: str | int | None = None
    resulting_version: str | int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "status": None if self.status is None else self.status.value,
            "input_version": self.input_version,
            "resulting_version": self.resulting_version,
            "payload": dict(self.payload),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationItemOutcome":
        if "payload" not in value:
            return cls(payload=dict(value))
        status = value.get("status")
        return cls(
            resource_id=None if value.get("resource_id") is None else str(value["resource_id"]),
            status=None if status is None else OperationStatus(status),
            input_version=value.get("input_version"),
            resulting_version=value.get("resulting_version"),
            payload=dict(value.get("payload", {})),
            extensions=dict(value.get("extensions", {})),
        )


@dataclass(frozen=True)
class OperationConflict:
    """Schema-bound optimistic-concurrency metadata with an opaque domain payload."""

    resource_id: str | None = None
    expected_version: str | int | None = None
    observed_version: str | int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "expected_version": self.expected_version,
            "observed_version": self.observed_version,
            "payload": dict(self.payload),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationConflict":
        if "payload" not in value:
            return cls(payload=dict(value))
        return cls(
            resource_id=None if value.get("resource_id") is None else str(value["resource_id"]),
            expected_version=value.get("expected_version"),
            observed_version=value.get("observed_version"),
            payload=dict(value.get("payload", {})),
            extensions=dict(value.get("extensions", {})),
        )


@dataclass(frozen=True)
class OperationReceipt:
    """Schema-bound receipt reference and terminality with an opaque domain payload."""

    receipt_id: str | None = None
    status: ReceiptStatus = ReceiptStatus.PENDING
    payload: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "status": self.status.value,
            "payload": dict(self.payload),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationReceipt":
        if "payload" not in value:
            return cls(payload=dict(value))
        return cls(
            receipt_id=None if value.get("receipt_id") is None else str(value["receipt_id"]),
            status=ReceiptStatus(value.get("status", ReceiptStatus.PENDING)),
            payload=dict(value.get("payload", {})),
            extensions=dict(value.get("extensions", {})),
        )


@dataclass(frozen=True)
class OperationRecovery:
    """Typed recovery posture with optional domain-specific instructions."""

    action: str
    instructions: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "instructions": self.instructions,
            "payload": dict(self.payload),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationRecovery":
        return cls(
            action=str(value["action"]),
            instructions=None if value.get("instructions") is None else str(value["instructions"]),
            payload=dict(value.get("payload", {})),
            extensions=dict(value.get("extensions", {})),
        )


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
    provenance: OperationProvenance | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "request_id": self.request_id,
            "context": self.context.to_dict(),
            "targets": [dict(target) for target in self.targets],
            "arguments": dict(self.arguments),
            "mode": self.mode,
            "expected_version": self.expected_version,
            "delegation": None if self.delegation is None else dict(self.delegation),
            "batch_policy": None if self.batch_policy is None else dict(self.batch_policy),
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationRequest":
        return cls(
            operation_id=str(value["operation_id"]),
            request_id=str(value["request_id"]),
            context=OperationContext.from_dict(value["context"]),
            targets=tuple(dict(item) for item in value.get("targets", ())),
            arguments=dict(value.get("arguments", {})),
            operation_version=str(value.get("operation_version", "ygg.operation.v1")),
            mode=str(value.get("mode", "execute")),
            expected_version=value.get("expected_version"),
            delegation=None if value.get("delegation") is None else dict(value["delegation"]),
            batch_policy=None if value.get("batch_policy") is None else dict(value["batch_policy"]),
            provenance=None
            if value.get("provenance") is None
            else OperationProvenance.from_dict(value["provenance"]),
            extensions=dict(value.get("extensions", {})),
        )


@dataclass(frozen=True)
class OperationOutcome:
    request_id: str
    status: OperationStatus
    operation_id: str
    context: OperationContext
    provenance: OperationProvenance | None = None
    convergence: OperationConvergence | None = None
    items: tuple[OperationItemOutcome, ...] = ()
    conflict: OperationConflict | None = None
    receipt: OperationReceipt | None = None
    recovery: OperationRecovery | None = None
    warnings: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "operation_id": self.operation_id,
            "context": self.context.to_dict(),
            "provenance": None if self.provenance is None else self.provenance.to_dict(),
            "convergence": None if self.convergence is None else self.convergence.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "conflict": None if self.conflict is None else self.conflict.to_dict(),
            "receipt": None if self.receipt is None else self.receipt.to_dict(),
            "recovery": None if self.recovery is None else self.recovery.to_dict(),
            "warnings": list(self.warnings),
            "extensions": dict(self.extensions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OperationOutcome":
        return cls(
            request_id=str(value["request_id"]),
            status=OperationStatus(value["status"]),
            operation_id=str(value["operation_id"]),
            context=OperationContext.from_dict(value["context"]),
            provenance=None
            if value.get("provenance") is None
            else OperationProvenance.from_dict(value["provenance"]),
            convergence=None
            if value.get("convergence") is None
            else OperationConvergence.from_dict(value["convergence"]),
            items=tuple(OperationItemOutcome.from_dict(item) for item in value.get("items", ())),
            conflict=None
            if value.get("conflict") is None
            else OperationConflict.from_dict(value["conflict"]),
            receipt=None
            if value.get("receipt") is None
            else OperationReceipt.from_dict(value["receipt"]),
            recovery=None
            if value.get("recovery") is None
            else OperationRecovery.from_dict(value["recovery"]),
            warnings=tuple(str(item) for item in value.get("warnings", ())),
            extensions=dict(value.get("extensions", {})),
        )


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
