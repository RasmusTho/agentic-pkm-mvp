"""Type-neutral governed archival contracts.

The types in this module are intentionally provider-free.  They describe the
authority and lifecycle seam that owner-native adapters implement; they do not
choose a database, archive backend, identifier registry, or retention policy
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Sequence


class _ValueEnum(str, Enum):
    """String-valued enum with stable wire-friendly values."""


class ArtifactClass(_ValueEnum):
    RAW_SOURCE = "raw_source"
    RETAINED_SOURCE = "retained_source"
    HUMAN_ARTIFACT = "human_artifact"
    DERIVED = "derived"
    RECEIPT = "receipt"


class Durability(_ValueEnum):
    DURABLE = "durable"
    EPHEMERAL = "ephemeral"
    REBUILDABLE = "rebuildable"


class AuthorityOwner(_ValueEnum):
    HKA = "hka"
    SIP = "sip"
    GOV = "gov"
    PDM = "pdm"
    DRI = "dri"
    SOURCE_ADAPTER = "source_adapter"


class PolicyProfile(_ValueEnum):
    RAW_EVIDENCE = "raw_evidence"
    RETAINED_SOURCE = "retained_source"
    HKA_RECOVERY = "hka_recovery"
    REBUILDABLE_DERIVATIVE = "rebuildable_derivative"

    @property
    def terminal_outcomes(self) -> frozenset[str]:
        """Return policy-specific terminal outcomes, never one universal delete rule."""

        return {
            self.RAW_EVIDENCE: frozenset({"erased", "unavailable"}),
            self.RETAINED_SOURCE: frozenset({"retained", "restored", "unavailable"}),
            self.HKA_RECOVERY: frozenset({"recovered", "conflict", "unavailable"}),
            self.REBUILDABLE_DERIVATIVE: frozenset({"rebuildable", "discarded", "unavailable"}),
        }[self]


class TransitionStage(_ValueEnum):
    RESERVED = "reserved"
    COPIED = "copied"
    VERIFIED = "verified"
    ACTIVE = "active"
    RESTORING = "restoring"
    RETIREMENT_PENDING = "retirement_pending"
    ERASURE_PENDING = "erasure_pending"
    RETIRED = "retired"
    RESTORED = "restored"
    ERASED = "erased"


class Liveness(_ValueEnum):
    ACTIVE = "active"
    PENDING = "pending"
    RESTORING = "restoring"
    ERASURE_PENDING = "erasure_pending"
    UNAVAILABLE = "unavailable"
    TERMINAL = "terminal"


def _opaque(value: str, field: str) -> str:
    """Validate an opaque identifier without treating a location as authority."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty opaque string")
    candidate = value.strip()
    if "/" in candidate or "\\" in candidate or "://" in candidate:
        raise ValueError(f"{field} must not be a path or URI")
    return candidate


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    """Stable owner-native artifact identity; never derived from location text."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque(self.value, "artifact identity"))


@dataclass(frozen=True, slots=True)
class RepresentationRef:
    """Opaque registered representation reference, not a filesystem path."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque(self.value, "representation reference"))


@dataclass(frozen=True, slots=True)
class Provenance:
    source_refs: tuple[str, ...]
    origin: str
    captured_at: str

    def __post_init__(self) -> None:
        if not self.origin.strip() or not self.captured_at.strip():
            raise ValueError("provenance origin and captured_at are required")
        if any(not ref.strip() for ref in self.source_refs):
            raise ValueError("provenance source references must be non-empty")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    identity: ArtifactIdentity
    artifact_class: ArtifactClass
    durability: Durability
    owner: AuthorityOwner
    policy: PolicyProfile
    generation: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("generation must be positive")


@dataclass(frozen=True, slots=True)
class RepresentationDescriptor:
    reference: RepresentationRef
    artifact: ArtifactIdentity
    generation: int
    content_identity: str
    format: str
    encrypted: bool

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("representation generation must be positive")
        if not self.content_identity.strip() or not self.format.strip():
            raise ValueError("representation content_identity and format are required")


@dataclass(frozen=True, slots=True)
class Receipt:
    """Redacted lifecycle evidence; location/path fields are intentionally absent."""

    kind: str
    artifact: ArtifactIdentity
    representation: RepresentationRef | None
    generation: int
    stage: TransitionStage
    liveness: Liveness

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("receipt kind is required")
        if self.generation < 1:
            raise ValueError("receipt generation must be positive")


class ArchivalAdapter(Protocol):
    """Owner-native adapter seam for the governed transition kernel."""

    def enumerate_representations(
        self, artifact: ArtifactIdentity, generation: int
    ) -> Sequence[RepresentationDescriptor]: ...

    def resolve_representation(
        self, reference: RepresentationRef
    ) -> RepresentationDescriptor: ...

    def authorize_read(
        self, artifact: ArtifactIdentity, representation: RepresentationRef
    ) -> Receipt: ...

    def reserve_representation(
        self, artifact: ArtifactIdentity, generation: int
    ) -> RepresentationRef: ...

    def verify_representation(
        self, representation: RepresentationRef
    ) -> Receipt: ...

    def activate_representation(
        self, representation: RepresentationRef
    ) -> Receipt: ...

    def retire_representation(
        self, representation: RepresentationRef
    ) -> Receipt: ...

    def restore(
        self, artifact: ArtifactIdentity, representation: RepresentationRef
    ) -> Receipt: ...

    def erase_or_revoke(
        self, artifact: ArtifactIdentity, generation: int
    ) -> Receipt: ...

    def doctor(self) -> Sequence[Receipt]: ...
