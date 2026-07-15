"""Domain-neutral contracts for the BuilderOps PostgreSQL authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol


class ControlPlaneError(RuntimeError):
    """Base error for fail-closed control-plane operations."""


class EnvelopeValidationError(ControlPlaneError):
    """Raised when mandatory authority scope is missing or ambiguous."""


class IdempotencyConflict(ControlPlaneError):
    """Raised when a key is reused for a different request."""


class LeaseUnavailable(ControlPlaneError):
    """Raised when another non-expired lease owns a resource."""


class StaleFencingToken(ControlPlaneError):
    """Raised when an expired or superseded lease attempts a mutation."""


class DurabilityPending(ControlPlaneError):
    """Raised while the independent recovery watermark trails a commit."""


class UnknownEffectNeedsReconciliation(ControlPlaneError):
    """Raised when readback is mandatory before an external-effect retry."""


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class AuthorityEnvelope:
    """Mandatory multi-repository authority context persisted on every row."""

    repository: str
    scope: str
    stack: str
    actor: str
    source_refs: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        values = (self.scope, self.stack, self.actor)
        if not _REPOSITORY.fullmatch(self.repository) or any(
            part in {".", ".."} for part in self.repository.split("/")
        ):
            raise EnvelopeValidationError("repository must be an unambiguous owner/name reference")
        if any(not value.strip() for value in values):
            raise EnvelopeValidationError("scope, stack, and actor are mandatory")
        if not self.source_refs or any(not ref.strip() for ref in self.source_refs):
            raise EnvelopeValidationError("at least one non-empty source reference is mandatory")
        if self.schema_version <= 0:
            raise EnvelopeValidationError("schema_version must be positive")

    def as_json(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "scope": self.scope,
            "stack": self.stack,
            "actor": self.actor,
            "source_refs": list(self.source_refs),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class TransactionResult:
    repository: str
    task_id: str
    state: str
    receipt_sequence: int
    recovery_lsn: str
    operation_key: str | None
    replayed: bool = field(default=False, compare=False)


@dataclass(frozen=True)
class Lease:
    repository: str
    resource_id: str
    holder: str
    fencing_token: int
    expires_at: datetime


@dataclass(frozen=True)
class OutboxClaim:
    repository: str
    operation_key: str
    worker_id: str
    fencing_token: int
    intent_lsn: str
    claim_lsn: str


class StorePort(Protocol):
    """Domain-neutral service boundary implemented by the PostgreSQL authority."""

    def readiness(self) -> dict[str, int]: ...

    def commit_transition(
        self,
        *,
        envelope: AuthorityEnvelope,
        task_id: str,
        to_state: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        outbox: Mapping[str, Any] | None = None,
        lease: Lease | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult: ...
