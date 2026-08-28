"""Read-only DRI disposition checks for rebuildable derivatives.

This module intentionally owns no archive representation, receipt, deletion, or
owner-state transition.  It evaluates only owner-native source and recipe
readbacks supplied by its callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.archival.contracts import ArtifactIdentity, Generation, OpaqueReference


class DerivativeDisposition(str, Enum):
    """The only classifications a read-only derivative doctor may return."""

    REBUILDABLE_NON_AUTHORITATIVE = "rebuildable_non_authoritative"
    REQUIRES_OWNER_ADMISSION = "requires_owner_admission"
    REFUSED = "refused"


class DerivativeFindingCode(str, Enum):
    MISSING_SOURCE_IDENTITY = "missing_source_identity"
    MISSING_SOURCE_GENERATION = "missing_source_generation"
    STALE_SOURCE_LINEAGE = "stale_source_lineage"
    MISSING_REBUILD_RECIPE = "missing_rebuild_recipe"
    UNAVAILABLE_REBUILD_RECIPE = "unavailable_rebuild_recipe"
    DERIVATIVE_AS_ARCHIVE_AUTHORITY = "derivative_as_archive_authority"
    OWNER_ADMISSION_REQUIRED = "owner_admission_required"


class OwnerAdmissionRoute(str, Enum):
    """Owner-native destinations for an explicit non-rebuildable reclassification."""

    HKA = "hka"
    RETAINED_SOURCE = "retained_source"


@dataclass(frozen=True)
class RebuildRecipe:
    reference: OpaqueReference
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, OpaqueReference):
            raise ValueError("recipe reference must be a typed opaque reference")
        if not isinstance(self.version, str) or not self.version:
            raise ValueError("recipe version must be a non-empty string")


@dataclass(frozen=True)
class DerivativeCandidate:
    """Owner-supplied derivative lineage; never inferred from paths or scans."""

    identity: ArtifactIdentity
    generation: Generation
    source_identity: ArtifactIdentity | None
    source_generation: Generation | None
    recipe: RebuildRecipe | None
    explicitly_nonrebuildable: bool = False
    requested_owner_admission: OwnerAdmissionRoute | None = None
    claimed_archive_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ArtifactIdentity):
            raise ValueError("derivative identity must be an artifact identity")
        if not isinstance(self.generation, Generation):
            raise ValueError("derivative generation must be a generation")
        if self.source_identity is not None and not isinstance(
            self.source_identity, ArtifactIdentity
        ):
            raise ValueError("source identity must be an artifact identity")
        if self.source_generation is not None and not isinstance(
            self.source_generation, Generation
        ):
            raise ValueError("source generation must be a generation")
        if self.recipe is not None and not isinstance(self.recipe, RebuildRecipe):
            raise ValueError("recipe must be a rebuild recipe")
        if type(self.explicitly_nonrebuildable) is not bool:
            raise ValueError("explicitly_nonrebuildable must be a bool")
        if self.requested_owner_admission is not None and not isinstance(
            self.requested_owner_admission, OwnerAdmissionRoute
        ):
            raise ValueError("requested_owner_admission must be an owner admission route")
        if type(self.claimed_archive_authority) is not bool:
            raise ValueError("claimed_archive_authority must be a bool")


@dataclass(frozen=True)
class DerivativeFinding:
    code: DerivativeFindingCode
    candidate: DerivativeCandidate


@dataclass(frozen=True)
class DerivativeDispositionResult:
    candidate: DerivativeCandidate
    disposition: DerivativeDisposition
    findings: tuple[DerivativeFinding, ...]
    owner_admission: OwnerAdmissionRoute | None = None

    @property
    def archive_authority(self) -> bool:
        """Derivatives cannot become last-copy authority through this doctor."""

        return False


class DerivativeSourceLookup(Protocol):
    """Read-only owner-native source lineage lookup."""

    def is_current(self, identity: ArtifactIdentity, generation: Generation) -> bool: ...


class RebuildRecipeLookup(Protocol):
    """Read-only recipe/version availability lookup."""

    def is_available(self, recipe: RebuildRecipe) -> bool: ...


class DerivativeDispositionDoctor:
    """Classify one supplied derivative without mutating any owner or archive state."""

    def __init__(
        self,
        source_lookup: DerivativeSourceLookup,
        recipe_lookup: RebuildRecipeLookup,
    ) -> None:
        self._source_lookup = source_lookup
        self._recipe_lookup = recipe_lookup

    def diagnose(self, candidate: DerivativeCandidate) -> DerivativeDispositionResult:
        findings: list[DerivativeFinding] = []

        if candidate.claimed_archive_authority:
            findings.append(
                DerivativeFinding(DerivativeFindingCode.DERIVATIVE_AS_ARCHIVE_AUTHORITY, candidate)
            )

        if candidate.explicitly_nonrebuildable:
            if candidate.requested_owner_admission is None:
                findings.append(
                    DerivativeFinding(DerivativeFindingCode.OWNER_ADMISSION_REQUIRED, candidate)
                )
                return self._refused(candidate, findings)
            return DerivativeDispositionResult(
                candidate,
                DerivativeDisposition.REQUIRES_OWNER_ADMISSION,
                tuple(findings),
                candidate.requested_owner_admission,
            )

        if candidate.source_identity is None:
            findings.append(
                DerivativeFinding(DerivativeFindingCode.MISSING_SOURCE_IDENTITY, candidate)
            )
        elif candidate.source_generation is None:
            findings.append(
                DerivativeFinding(DerivativeFindingCode.MISSING_SOURCE_GENERATION, candidate)
            )
        elif not self._source_lookup.is_current(
            candidate.source_identity, candidate.source_generation
        ):
            findings.append(
                DerivativeFinding(DerivativeFindingCode.STALE_SOURCE_LINEAGE, candidate)
            )

        if candidate.recipe is None:
            findings.append(
                DerivativeFinding(DerivativeFindingCode.MISSING_REBUILD_RECIPE, candidate)
            )
        elif not self._recipe_lookup.is_available(candidate.recipe):
            findings.append(
                DerivativeFinding(DerivativeFindingCode.UNAVAILABLE_REBUILD_RECIPE, candidate)
            )

        if findings:
            return self._refused(candidate, findings)
        return DerivativeDispositionResult(
            candidate, DerivativeDisposition.REBUILDABLE_NON_AUTHORITATIVE, ()
        )

    @staticmethod
    def _refused(
        candidate: DerivativeCandidate,
        findings: list[DerivativeFinding],
    ) -> DerivativeDispositionResult:
        return DerivativeDispositionResult(candidate, DerivativeDisposition.REFUSED, tuple(findings))
