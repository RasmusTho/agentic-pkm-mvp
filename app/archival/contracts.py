"""Provider-free values and protocols for governed archival flow.

The common contract preserves owner-native identity, policy, and storage seams. It offers
neither a central registry nor an implementation that can read, store, or authorize artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol, Sequence, TypeVar, cast


class ArtifactClass(str, Enum):
    """Broad archival classes, not a universal ontology."""

    SOURCE = "source"
    HUMAN = "human"
    DERIVED = "derived"
    RECEIPT = "receipt"


class DerivationClass(str, Enum):
    SOURCE = "source"
    DERIVED = "derived"
    RECEIPT = "receipt"


class DurabilityClass(str, Enum):
    DURABLE = "durable"
    EPHEMERAL = "ephemeral"
    REBUILDABLE = "rebuildable"


class OwnerAuthority(str, Enum):
    """Existing owner boundaries; class-specific adapters retain their own authority."""

    HKA = "hka"
    SIP = "sip"
    GOV = "gov"
    PDM = "pdm"
    DRI = "dri"
    CLASS_ADAPTER = "class_adapter"


class PolicyTerminalOutcome(str, Enum):
    ERASE_ON_RETENTION_OR_REVOCATION = "erase_on_retention_or_revocation"
    RETAIN_UNTIL_OWNER_RETIREMENT = "retain_until_owner_retirement"
    RESTORE_WITH_CONFLICT_CHECK = "restore_with_conflict_check"
    DISCARD_AFTER_REBUILDABILITY_PROOF = "discard_after_rebuildability_proof"


class PolicyProfile(str, Enum):
    """Class-selected policy posture; location never selects policy or authority."""

    RAW_EVIDENCE = "raw_evidence"
    RETAINED_SOURCE = "retained_source"
    HKA_RECOVERY = "hka_recovery"
    REBUILDABLE_DERIVATIVE = "rebuildable_derivative"

    @property
    def terminal_outcome(self) -> PolicyTerminalOutcome:
        return {
            PolicyProfile.RAW_EVIDENCE: PolicyTerminalOutcome.ERASE_ON_RETENTION_OR_REVOCATION,
            PolicyProfile.RETAINED_SOURCE: PolicyTerminalOutcome.RETAIN_UNTIL_OWNER_RETIREMENT,
            PolicyProfile.HKA_RECOVERY: PolicyTerminalOutcome.RESTORE_WITH_CONFLICT_CHECK,
            PolicyProfile.REBUILDABLE_DERIVATIVE: PolicyTerminalOutcome.DISCARD_AFTER_REBUILDABILITY_PROOF,
        }[self]

    @property
    def allows_erase_or_revoke(self) -> bool:
        return self is PolicyProfile.RAW_EVIDENCE

    @property
    def allows_discard_when_rebuildable(self) -> bool:
        return self is PolicyProfile.REBUILDABLE_DERIVATIVE


class TransitionStage(str, Enum):
    ENUMERATED = "enumerated"
    RESERVED = "reserved"
    VERIFIED = "verified"
    ACTIVE = "active"
    RETIRED = "retired"
    RESTORED = "restored"
    ERASE_PENDING = "erase_pending"
    ERASED = "erased"
    REFUSED = "refused"
    CONFLICT = "conflict"
    RESTORE_PENDING = "restore_pending"


class LivenessState(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    STALE = "stale"
    MISSING = "missing"
    ERASED = "erased"
    REFUSED = "refused"
    TRANSITION_PENDING = "transition_pending"
    RESTORE_PENDING = "restore_pending"
    ERASURE_PENDING = "erasure_pending"
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"


_OPAQUE_NAMESPACE = re.compile(r"^[a-z][a-z0-9_-]*$")
_ConcreteContractT = TypeVar("_ConcreteContractT")


def _require_token(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_NAMESPACE.fullmatch(value):
        raise ValueError(f"{field_name} must be an opaque token")
    return value


def _require_concrete_contract(
    value: object,
    expected_type: type[_ConcreteContractT],
    field_name: str,
    *,
    expected_description: str | None = None,
) -> _ConcreteContractT:
    if type(value) is not expected_type:
        description = expected_description or f"an exact {expected_type.__name__} value"
        raise ValueError(f"{field_name} must be {description}")
    return cast(_ConcreteContractT, value)


def _require_optional_contract(
    value: object | None,
    expected_type: type[_ConcreteContractT],
    field_name: str,
) -> _ConcreteContractT | None:
    if value is None:
        return None
    return _require_concrete_contract(value, expected_type, field_name)


def _require_exact_bool(value: object, field_name: str) -> bool:
    return _require_concrete_contract(value, bool, field_name)


@dataclass(frozen=True)
class OpaqueReference:
    """A typed owner-native handle; common types never parse location text."""

    namespace: str
    token: str

    def __post_init__(self) -> None:
        _require_token(self.namespace, "opaque reference namespace")
        if not isinstance(self.token, str) or not self.token:
            raise ValueError("opaque reference token must be a non-empty string")


def _require_opaque_reference(value: OpaqueReference, field_name: str) -> OpaqueReference:
    if not isinstance(value, OpaqueReference):
        raise ValueError(f"{field_name} must be a typed opaque reference, not location text")
    return value


def _require_reference_tuple(
    value: object,
    expected_type: type[object],
    field_name: str,
    *,
    non_empty: bool = False,
) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a tuple of {expected_type.__name__} values")
    if non_empty and not value:
        raise ValueError(f"{field_name} must contain at least one {expected_type.__name__} value")
    if any(not isinstance(item, expected_type) for item in value):
        raise ValueError(f"{field_name} must contain only {expected_type.__name__} values")


@dataclass(frozen=True)
class ArtifactIdentity:
    """An owner-native identity, not a generated global archive identifier."""

    owner: OwnerAuthority
    owner_native_id: OpaqueReference
    owner_namespace: str | None = None

    def __post_init__(self) -> None:
        _require_concrete_contract(self.owner, OwnerAuthority, "owner")
        _require_opaque_reference(self.owner_native_id, "owner_native_id")
        if self.owner is OwnerAuthority.CLASS_ADAPTER:
            if self.owner_namespace is None:
                raise ValueError("class-adapter identity requires an owner namespace")
            _require_token(self.owner_namespace, "owner_namespace")
        elif self.owner_namespace is not None:
            raise ValueError("owner_namespace is only valid for class-adapter identities")


@dataclass(frozen=True)
class RepresentationRef:
    """Opaque adapter handle; only the owner adapter resolves it."""

    adapter: str
    opaque_id: OpaqueReference

    def __post_init__(self) -> None:
        _require_token(self.adapter, "adapter")
        _require_opaque_reference(self.opaque_id, "opaque_id")


@dataclass(frozen=True)
class AccessAuthority:
    """A GOV or owner-issued grant; a mount, path, or URL cannot substitute for it."""

    issuer: OwnerAuthority
    grant_ref: OpaqueReference

    def __post_init__(self) -> None:
        _require_concrete_contract(self.issuer, OwnerAuthority, "issuer")
        _require_opaque_reference(self.grant_ref, "grant_ref")


@dataclass(frozen=True)
class Generation:
    """Owner-native monotonic generation fencing stale transitions and restores."""

    value: int

    def __post_init__(self) -> None:
        _require_concrete_contract(
            self.value,
            int,
            "generation",
            expected_description="a non-negative integer",
        )
        if self.value < 0:
            raise ValueError("generation must be a non-negative integer")


@dataclass(frozen=True)
class ProvenanceRef:
    kind: str
    reference: OpaqueReference

    def __post_init__(self) -> None:
        _require_token(self.kind, "provenance kind")
        _require_opaque_reference(self.reference, "provenance reference")


@dataclass(frozen=True)
class ArtifactDescriptor:
    """Classification, authority, generation, and provenance preserved across representations."""

    identity: ArtifactIdentity
    artifact_class: ArtifactClass
    derivation: DerivationClass
    durability: DurabilityClass
    owner: OwnerAuthority
    generation: Generation
    provenance_refs: tuple[ProvenanceRef, ...]
    policy_profile: PolicyProfile

    def __post_init__(self) -> None:
        _require_concrete_contract(self.identity, ArtifactIdentity, "identity")
        _require_concrete_contract(self.artifact_class, ArtifactClass, "artifact_class")
        _require_concrete_contract(self.derivation, DerivationClass, "derivation")
        _require_concrete_contract(self.durability, DurabilityClass, "durability")
        _require_concrete_contract(self.owner, OwnerAuthority, "owner")
        _require_concrete_contract(self.generation, Generation, "generation")
        _require_concrete_contract(self.policy_profile, PolicyProfile, "policy_profile")
        if self.identity.owner is not self.owner:
            raise ValueError("artifact identity owner must match the declared authoritative owner")
        _require_reference_tuple(
            self.provenance_refs,
            ProvenanceRef,
            "provenance_refs",
            non_empty=True,
        )


@dataclass(frozen=True)
class Liveness:
    """Typed result that prevents partial cleanup from being reported as terminal success."""

    state: LivenessState
    evidence_ref: OpaqueReference

    def __post_init__(self) -> None:
        _require_concrete_contract(self.state, LivenessState, "state")
        _require_opaque_reference(self.evidence_ref, "liveness evidence_ref")

    @property
    def is_terminal(self) -> bool:
        return self.state is LivenessState.ERASED


@dataclass(frozen=True)
class Representation:
    artifact: ArtifactIdentity
    ref: RepresentationRef
    generation: Generation
    stage: TransitionStage
    liveness: Liveness

    def __post_init__(self) -> None:
        _require_concrete_contract(self.artifact, ArtifactIdentity, "artifact")
        _require_concrete_contract(self.ref, RepresentationRef, "ref")
        _require_concrete_contract(self.generation, Generation, "generation")
        _require_concrete_contract(self.stage, TransitionStage, "stage")
        _require_concrete_contract(self.liveness, Liveness, "liveness")


@dataclass(frozen=True)
class RepresentationReservation:
    artifact: ArtifactIdentity
    target: RepresentationRef
    generation: Generation
    reservation_ref: OpaqueReference

    def __post_init__(self) -> None:
        _require_concrete_contract(self.artifact, ArtifactIdentity, "artifact")
        _require_concrete_contract(self.target, RepresentationRef, "target")
        _require_concrete_contract(self.generation, Generation, "generation")
        _require_opaque_reference(self.reservation_ref, "reservation_ref")


@dataclass(frozen=True)
class VerificationResult:
    representation: RepresentationRef
    generation: Generation
    verified: bool
    evidence_ref: OpaqueReference

    def __post_init__(self) -> None:
        _require_concrete_contract(self.representation, RepresentationRef, "representation")
        _require_concrete_contract(self.generation, Generation, "generation")
        _require_exact_bool(self.verified, "verified")
        _require_opaque_reference(self.evidence_ref, "verification evidence_ref")


@dataclass(frozen=True)
class ArchivalReceipt:
    """Redacted transition evidence that cannot replace owner-native state."""

    receipt_ref: OpaqueReference
    artifact: ArtifactIdentity
    generation: Generation
    stage: TransitionStage
    policy_profile: PolicyProfile
    liveness: Liveness
    provenance_refs: tuple[ProvenanceRef, ...]
    representation_refs: tuple[RepresentationRef, ...]
    redacted: bool = True

    def __post_init__(self) -> None:
        _require_opaque_reference(self.receipt_ref, "receipt_ref")
        _require_concrete_contract(self.artifact, ArtifactIdentity, "artifact")
        _require_concrete_contract(self.generation, Generation, "generation")
        _require_concrete_contract(self.stage, TransitionStage, "stage")
        _require_concrete_contract(self.policy_profile, PolicyProfile, "policy_profile")
        _require_concrete_contract(self.liveness, Liveness, "liveness")
        _require_reference_tuple(self.provenance_refs, ProvenanceRef, "provenance_refs")
        _require_reference_tuple(
            self.representation_refs,
            RepresentationRef,
            "representation_refs",
        )
        _require_exact_bool(self.redacted, "redacted")
        if self.redacted is not True:
            raise ValueError("archival receipts must be redacted")


@dataclass(frozen=True)
class OperationBinding:
    """Immutable owner-journal identity established before transition effects."""

    idempotency_key: str
    artifact: ArtifactIdentity
    generation: Generation
    policy: PolicyProfile
    source: RepresentationRef
    target: RepresentationRef

    def __post_init__(self) -> None:
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key:
            raise ValueError("idempotency_key must be a non-empty string")
        _require_concrete_contract(self.artifact, ArtifactIdentity, "artifact")
        _require_concrete_contract(self.generation, Generation, "generation")
        _require_concrete_contract(self.policy, PolicyProfile, "policy")
        _require_concrete_contract(self.source, RepresentationRef, "source")
        _require_concrete_contract(self.target, RepresentationRef, "target")


@dataclass(frozen=True)
class OperationRecord:
    """Owner-native transition-journal readback for one immutable binding."""

    binding: OperationBinding
    reservation: RepresentationReservation | None = None
    copied: bool = False
    verification: VerificationResult | None = None
    receipt: ArchivalReceipt | None = None
    activated: bool = False
    retired: bool = False
    completed: bool = False

    def __post_init__(self) -> None:
        _require_concrete_contract(self.binding, OperationBinding, "binding")
        _require_optional_contract(
            self.reservation, RepresentationReservation, "reservation"
        )
        _require_exact_bool(self.copied, "copied")
        _require_optional_contract(
            self.verification, VerificationResult, "verification"
        )
        _require_optional_contract(self.receipt, ArchivalReceipt, "receipt")
        _require_exact_bool(self.activated, "activated")
        _require_exact_bool(self.retired, "retired")
        _require_exact_bool(self.completed, "completed")


@dataclass(frozen=True)
class CleanupProof:
    """Owner-native proof that every policy-required representation was handled."""

    artifact: ArtifactIdentity
    generation: Generation
    policy: PolicyProfile
    representation_refs: tuple[RepresentationRef, ...]
    complete: bool
    evidence_ref: OpaqueReference

    def __post_init__(self) -> None:
        _require_concrete_contract(self.artifact, ArtifactIdentity, "artifact")
        _require_concrete_contract(self.generation, Generation, "generation")
        _require_concrete_contract(self.policy, PolicyProfile, "policy")
        _require_reference_tuple(
            self.representation_refs,
            RepresentationRef,
            "representation_refs",
            non_empty=True,
        )
        _require_exact_bool(self.complete, "complete")
        _require_opaque_reference(self.evidence_ref, "cleanup evidence_ref")


@dataclass(frozen=True)
class DoctorFinding:
    """Read-only reconciliation evidence; owners decide remediation."""

    code: str
    artifact: ArtifactIdentity | None
    representation: RepresentationRef | None
    liveness: Liveness
    evidence_ref: OpaqueReference

    def __post_init__(self) -> None:
        _require_token(self.code, "doctor finding code")
        _require_optional_contract(self.artifact, ArtifactIdentity, "artifact")
        _require_optional_contract(self.representation, RepresentationRef, "representation")
        _require_concrete_contract(self.liveness, Liveness, "liveness")
        _require_opaque_reference(self.evidence_ref, "doctor finding evidence_ref")


class ArchivalAdapter(Protocol):
    """Owner-native journal, durability, access, restore, and cleanup seam."""

    def enumerate(self, artifact: ArtifactIdentity) -> Sequence[Representation]: ...

    def resolve(self, reference: RepresentationRef) -> Representation: ...

    def authorize_read(
        self, artifact: ArtifactDescriptor, authority: AccessAuthority
    ) -> ArchivalReceipt: ...

    def bind_operation(self, binding: OperationBinding) -> OperationRecord: ...

    def read_operation(self, idempotency_key: str) -> OperationRecord | None: ...

    def reserve(self, binding: OperationBinding) -> RepresentationReservation: ...

    def copy(
        self, binding: OperationBinding, reservation: RepresentationReservation
    ) -> None: ...

    def verify(
        self, binding: OperationBinding, reservation: RepresentationReservation
    ) -> VerificationResult: ...

    def durable_receipt(
        self,
        binding: OperationBinding,
        reservation: RepresentationReservation,
        verification: VerificationResult,
    ) -> ArchivalReceipt: ...

    def activate(
        self,
        binding: OperationBinding,
        reservation: RepresentationReservation,
        verification: VerificationResult,
        receipt: ArchivalReceipt,
    ) -> None: ...

    def retire(
        self,
        binding: OperationBinding,
        representation: Representation,
        receipt: ArchivalReceipt,
    ) -> None: ...

    def complete_operation(
        self, binding: OperationBinding, receipt: ArchivalReceipt
    ) -> ArchivalReceipt: ...

    def restore(
        self,
        artifact: ArtifactDescriptor,
        authority: AccessAuthority,
        representation: RepresentationRef,
    ) -> ArchivalReceipt: ...

    def read_restore(
        self, artifact: ArtifactDescriptor, representation: RepresentationRef
    ) -> ArchivalReceipt | None: ...

    def cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof: ...

    def read_cleanup(self, artifact: ArtifactDescriptor) -> CleanupProof | None: ...

    def doctor(self) -> Sequence[DoctorFinding]: ...
