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
    receipt_sequence: int
    expires_at: datetime


def _lsn_value(lsn: str) -> int:
    try:
        high, low = lsn.split("/", 1)
        return (int(high, 16) << 32) + int(low, 16)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid PostgreSQL LSN: {lsn!r}") from exc


@dataclass(frozen=True)
class RecoveryWatermark:
    """Independent recovery readback, not a client-asserted scalar LSN.

    BCP-02 will construct this proof by reading the independent recovery target.
    BCP-01 consumes it only after the named receipt/outbox/claim row is visible
    there, preventing an LSN sampled before a binding write from authorizing work.
    """

    recovered_through: str
    observed_receipts: frozenset[tuple[str, int, str]] = frozenset()
    observed_intents: frozenset[tuple[str, str, str]] = frozenset()
    observed_claims: frozenset[tuple[str, str, int, int, str]] = frozenset()

    @classmethod
    def stalled(cls) -> RecoveryWatermark:
        return cls(recovered_through="0/0")

    def covers_transition(self, result: TransactionResult) -> bool:
        return bool(
            _lsn_value(self.recovered_through) >= _lsn_value(result.recovery_lsn)
            and (result.repository, result.receipt_sequence, result.recovery_lsn)
            in self.observed_receipts
        )

    def covers_intent(self, result: TransactionResult) -> bool:
        return bool(
            result.operation_key
            and self.covers_transition(result)
            and (result.repository, result.operation_key, result.recovery_lsn)
            in self.observed_intents
        )

    def covers_claim(self, claim: OutboxClaim) -> bool:
        identity = (
            claim.repository,
            claim.operation_key,
            claim.fencing_token,
            claim.receipt_sequence,
            claim.claim_lsn,
        )
        return bool(
            _lsn_value(self.recovered_through) >= _lsn_value(claim.claim_lsn)
            and identity in self.observed_claims
            and (claim.repository, claim.receipt_sequence, claim.claim_lsn)
            in self.observed_receipts
        )


@runtime_checkable
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
        expected_states: tuple[str, ...] | None = None,
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

    def heartbeat_lease(self, lease: Lease, *, ttl_seconds: int) -> Lease: ...

    def release_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        fault_at: str | None = None,
    ) -> TransactionResult: ...

    def complete_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        fault_at: str | None = None,
    ) -> TransactionResult: ...

    def claim_outbox(
        self,
        *,
        envelope: AuthorityEnvelope,
        operation_key: str | None,
        worker_id: str,
        watermark: RecoveryWatermark,
        claim_ttl_seconds: int = 300,
        fault_at: str | None = None,
    ) -> OutboxClaim: ...

    def effect_eligible(
        self,
        claim: OutboxClaim,
        *,
        watermark: RecoveryWatermark,
    ) -> bool: ...

    def reconcile_outbox(
        self, claim: OutboxClaim, *, observed_applied: bool, evidence: Mapping[str, Any]
    ) -> None: ...
