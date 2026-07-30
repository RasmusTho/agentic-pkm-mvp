"""Domain-neutral contracts for the BuilderOps PostgreSQL authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable


class ControlPlaneError(RuntimeError):
    """Base error for fail-closed control-plane operations."""


class EnvelopeValidationError(ControlPlaneError):
    """Raised when mandatory authority scope is missing or ambiguous."""


class IdempotencyConflict(ControlPlaneError):
    """Raised when a key is reused for a different request."""


class LeaseUnavailable(ControlPlaneError):
    """Raised when another non-expired lease owns a resource."""


class LeaseRequired(ControlPlaneError):
    """Raised when an existing authority row is mutated without a lease."""


class StateConflict(ControlPlaneError):
    """Raised when a guarded transition observes an unexpected prior state."""


class StaleFencingToken(ControlPlaneError):
    """Raised when an expired or superseded lease attempts a mutation."""


class DurabilityPending(ControlPlaneError):
    """Raised while a locally committed authority row is not fully bound."""


class UnknownEffectNeedsReconciliation(ControlPlaneError):
    """Raised when readback is mandatory before an external-effect retry."""


# The service's HTTP 409 ``detail`` classification and the client's stale-vs-
# generic-conflict matching share these exact identifiers, so a class rename
# here cannot silently desync from the client's classification (BCP-04 review
# finding H3). ``STALE_AUTHORITY_EPOCH_DETAIL`` is not backed by an exception
# class here: the authority-epoch fence is a service/HTTP-layer concern
# (``require_authority_epoch`` in service.py), not a store-layer one.
STALE_FENCING_TOKEN_DETAIL = StaleFencingToken.__name__
LEASE_UNAVAILABLE_DETAIL = LeaseUnavailable.__name__
LEASE_REQUIRED_DETAIL = LeaseRequired.__name__
STALE_AUTHORITY_EPOCH_DETAIL = "StaleAuthorityEpoch"
STALE_DETAIL_NAMES = frozenset(
    {
        STALE_FENCING_TOKEN_DETAIL,
        LEASE_UNAVAILABLE_DETAIL,
        LEASE_REQUIRED_DETAIL,
        STALE_AUTHORITY_EPOCH_DETAIL,
    }
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def canonical_repository(repository: str) -> str:
    """Return the canonical GitHub owner/repository identity or fail closed."""
    if not _REPOSITORY.fullmatch(repository) or any(
        part in {".", ".."} for part in repository.split("/")
    ):
        raise EnvelopeValidationError("repository must be an unambiguous owner/name reference")
    return repository.lower()


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
        object.__setattr__(self, "repository", canonical_repository(self.repository))
        values = (self.scope, self.stack, self.actor)
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", canonical_repository(self.repository))


@dataclass(frozen=True)
class AuthorityObjectResult:
    repository: str
    object_kind: str
    object_id: str
    state: str
    receipt_sequence: int
    recovery_lsn: str
    replayed: bool = field(default=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", canonical_repository(self.repository))


@dataclass(frozen=True)
class Lease:
    repository: str
    resource_id: str
    holder: str
    fencing_token: int
    expires_at: datetime
    lease_kind: str = "task"

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", canonical_repository(self.repository))
        if self.lease_kind not in {"task", "generic"}:
            raise ValueError("lease_kind must be task or generic")


@dataclass(frozen=True)
class OutboxClaim:
    repository: str
    operation_key: str
    worker_id: str
    fencing_token: int
    intent_lsn: str
    claim_lsn: str
    receipt_sequence: int
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", canonical_repository(self.repository))


@dataclass(frozen=True)
class OutboxReconciliation:
    """Receipt-bound readback outcome for one exact fenced external attempt."""

    repository: str
    operation_key: str
    task_id: str
    status: str
    worker_id: str
    fencing_token: int
    claim_receipt_sequence: int
    receipt_sequence: int
    recovery_lsn: str
    replayed: bool = field(default=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", canonical_repository(self.repository))


@runtime_checkable
class StorePort(Protocol):
    """Domain-neutral service boundary implemented by the PostgreSQL authority."""

    def readiness(self) -> dict[str, int]: ...

    def get_task(self, repository: str, task_id: str) -> Mapping[str, Any]: ...

    def list_tasks(
        self, repository: str, *, task_prefix: str | None = None
    ) -> list[Mapping[str, Any]]: ...

    def list_attempts(
        self, repository: str, task_id: str
    ) -> list[Mapping[str, Any]]: ...

    def outbox_intent(
        self, repository: str, operation_key: str
    ) -> Mapping[str, Any]: ...

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
        expected_states: tuple[str, ...] | None = None,
        expected_version: int | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult: ...

    def claim_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        task_id: str,
        holder: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        ttl_seconds: int = 5400,
        fault_at: str | None = None,
    ) -> tuple[TransactionResult, Lease]: ...

    def release_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        expected_version: int | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult: ...

    def complete_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        expected_version: int | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult: ...

    def claim_lease(
        self,
        *,
        envelope: AuthorityEnvelope,
        resource_id: str,
        holder: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        ttl_seconds: int = 5400,
        fault_at: str | None = None,
    ) -> tuple[TransactionResult, Lease]: ...

    def heartbeat_lease(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        ttl_seconds: int,
        fault_at: str | None = None,
    ) -> tuple[TransactionResult, Lease]: ...

    def release_lease(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        fault_at: str | None = None,
    ) -> TransactionResult: ...

    def commit_record(
        self,
        *,
        envelope: AuthorityEnvelope,
        record_id: str,
        record_type: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Lease | None = None,
        expected_states: tuple[str, ...] | None = None,
        fault_at: str | None = None,
    ) -> AuthorityObjectResult: ...

    def commit_attempt(
        self,
        *,
        envelope: AuthorityEnvelope,
        task_id: str,
        attempt_id: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Lease,
        expected_states: tuple[str, ...] | None = None,
        expected_task_version: int | None = None,
        fault_at: str | None = None,
    ) -> AuthorityObjectResult: ...

    def commit_promotion(
        self,
        *,
        envelope: AuthorityEnvelope,
        promotion_id: str,
        status: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Lease | None = None,
        expected_states: tuple[str, ...] | None = None,
        fault_at: str | None = None,
    ) -> AuthorityObjectResult: ...

    def get_record(self, repository: str, record_id: str) -> Mapping[str, Any]: ...

    def get_attempt(self, repository: str, task_id: str, attempt_id: str) -> Mapping[str, Any]: ...

    def get_promotion(self, repository: str, promotion_id: str) -> Mapping[str, Any]: ...

    def replay(
        self,
        repository: str,
        idempotency_key: str,
    ) -> TransactionResult | AuthorityObjectResult | None: ...

    def claim_outbox(
        self,
        *,
        envelope: AuthorityEnvelope,
        operation_key: str | None,
        worker_id: str,
        claim_ttl_seconds: int = 300,
        fault_at: str | None = None,
    ) -> OutboxClaim: ...

    def effect_eligible(
        self,
        claim: OutboxClaim,
    ) -> bool: ...

    def outbox_claim(self, repository: str, operation_key: str) -> OutboxClaim: ...

    def mark_effect_unknown(self, claim: OutboxClaim, *, detail: str) -> None: ...

    def reconcile_outbox(
        self,
        claim: OutboxClaim,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence: Mapping[str, Any],
        fault_at: str | None = None,
    ) -> OutboxReconciliation: ...

    def outbox_status(
        self,
        repository: str,
        operation_key: str | None,
    ) -> str: ...
