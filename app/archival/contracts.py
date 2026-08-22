"""Provider-free values and protocols for governed archival flow.

The common contract preserves owner-native identity, policy, and storage seams. It offers
neither a central registry nor an implementation that can read, store, or authorize artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Protocol, Sequence


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


class LivenessState(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    STALE = "stale"
    MISSING = "missing"
    ERASED = "erased"
    REFUSED = "refused"


def _looks_like_location(value: str) -> bool:
    normalized = value.strip()
    return (
        "/" in normalized
        or "\\" in normalized
        or normalized.startswith("~")
        or bool(re.match(r"^[A-Za-z]:", normalized))
        or bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", normalized))
    )


def _require_opaque(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty opaque reference")
    if _looks_like_location(value):
        raise ValueError(f"{field_name} must be opaque; location text cannot mint authority")
    return value


@dataclass(frozen=True)
class ArtifactIdentity:
    """An owner-native identity, not a generated global archive identifier."""

    owner: OwnerAuthority
    owner_native_id: str
    owner_namespace: str | None = None

    def __post_init__(self) -> None:
        _require_opaque(self.owner_native_id, "owner_native_id")
        if self.owner is OwnerAuthority.CLASS_ADAPTER:
            if self.owner_namespace is None:
                raise ValueError("class-adapter identity requires an owner namespace")
            _require_opaque(self.owner_namespace, "owner_namespace")
        elif self.owner_namespace is not None:
            raise ValueError("owner_namespace is only valid for class-adapter identities")


@dataclass(frozen=True)
class RepresentationRef:
    """Opaque adapter handle; only the owner adapter resolves it."""

    adapter: str
    opaque_id: str

    def __post_init__(self) -> None:
        _require_opaque(self.adapter, "adapter")
        _require_opaque(self.opaque_id, "opaque_id")


@dataclass(frozen=True)
class AccessAuthority:
    """A GOV or owner-issued grant; a mount, path, or URL cannot substitute for it."""

    issuer: OwnerAuthority
    grant_ref: str

    def __post_init__(self) -> None:
        _require_opaque(self.grant_ref, "grant_ref")


@dataclass(frozen=True)
class Generation:
    """Owner-native monotonic generation fencing stale transitions and restores."""

    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value < 0:
            raise ValueError("generation must be a non-negative integer")


@dataclass(frozen=True)
class ProvenanceRef:
    kind: str
    reference: str

    def __post_init__(self) -> None:
        _require_opaque(self.kind, "provenance kind")
        _require_opaque(self.reference, "provenance reference")


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
        if self.identity.owner is not self.owner:
            raise ValueError("artifact identity owner must match the declared authoritative owner")
        if not self.provenance_refs:
            raise ValueError("artifact descriptors require at least one provenance reference")


@dataclass(frozen=True)
class Liveness:
    """Typed result that prevents partial cleanup from being reported as terminal success."""

    state: LivenessState
    evidence_ref: str

    def __post_init__(self) -> None:
        _require_opaque(self.evidence_ref, "liveness evidence_ref")

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


@dataclass(frozen=True)
class RepresentationReservation:
    artifact: ArtifactIdentity
    target: RepresentationRef
    generation: Generation
    reservation_ref: str

    def __post_init__(self) -> None:
        _require_opaque(self.reservation_ref, "reservation_ref")


@dataclass(frozen=True)
class VerificationResult:
    representation: RepresentationRef
    generation: Generation
    verified: bool
    evidence_ref: str

    def __post_init__(self) -> None:
        _require_opaque(self.evidence_ref, "verification evidence_ref")


@dataclass(frozen=True)
class ArchivalReceipt:
    """Redacted transition evidence that cannot replace owner-native state."""

    receipt_ref: str
    artifact: ArtifactIdentity
    generation: Generation
    stage: TransitionStage
    policy_profile: PolicyProfile
    liveness: Liveness
    provenance_refs: tuple[ProvenanceRef, ...]
    representation_refs: tuple[RepresentationRef, ...]
    redacted: bool = True

    def __post_init__(self) -> None:
        _require_opaque(self.receipt_ref, "receipt_ref")
        if not self.redacted:
            raise ValueError("archival receipts must be redacted")


@dataclass(frozen=True)
class DoctorFinding:
    """Read-only reconciliation evidence; owners decide remediation."""

    code: str
    artifact: ArtifactIdentity | None
    representation: RepresentationRef | None
    liveness: Liveness
    evidence_ref: str

    def __post_init__(self) -> None:
        _require_opaque(self.code, "doctor finding code")
        _require_opaque(self.evidence_ref, "doctor finding evidence_ref")


class ArchivalAdapter(Protocol):
    """Owner-native operations for later transition and class-adapter slices."""

    def enumerate(self, artifact: ArtifactIdentity) -> Sequence[Representation]: ...

    def resolve(self, reference: RepresentationRef) -> Representation: ...

    def authorize_read(
        self, artifact: ArtifactIdentity, authority: AccessAuthority
    ) -> ArchivalReceipt: ...

    def reserve(self, artifact: ArtifactDescriptor, target: RepresentationRef) -> RepresentationReservation: ...

    def verify(self, reservation: RepresentationReservation) -> VerificationResult: ...

    def activate(self, reservation: RepresentationReservation, verification: VerificationResult) -> ArchivalReceipt: ...

    def retire(self, representation: Representation, receipt: ArchivalReceipt) -> ArchivalReceipt: ...

    def restore(self, artifact: ArtifactIdentity, authority: AccessAuthority) -> ArchivalReceipt: ...

    def erase_or_revoke(self, artifact: ArtifactIdentity, authority: AccessAuthority) -> ArchivalReceipt: ...

    def doctor(self) -> Sequence[DoctorFinding]: ...
