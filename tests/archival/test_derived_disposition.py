"""Acceptance tests for the read-only GAF-06 derivative disposition doctor."""

from __future__ import annotations

from app.archival.contracts import (
    ArtifactIdentity,
    Generation,
    OpaqueReference,
    OwnerAuthority,
)
from app.archival.derived_disposition import (
    DerivativeCandidate,
    DerivativeDisposition,
    DerivativeDispositionDoctor,
    DerivativeFindingCode,
    OwnerAdmissionRoute,
    RebuildRecipe,
)


class FakeSourceLookup:
    def __init__(self, resolved: bool = True) -> None:
        self.resolved = resolved
        self.calls: list[tuple[ArtifactIdentity, Generation]] = []

    def is_current(self, identity: ArtifactIdentity, generation: Generation) -> bool:
        self.calls.append((identity, generation))
        return self.resolved


class FakeRecipeLookup:
    def __init__(self, resolved: bool = True) -> None:
        self.resolved = resolved
        self.calls: list[RebuildRecipe] = []

    def is_available(self, recipe: RebuildRecipe) -> bool:
        self.calls.append(recipe)
        return self.resolved


def _candidate(**changes: object) -> DerivativeCandidate:
    source = ArtifactIdentity(OwnerAuthority.HKA, OpaqueReference("hka", "note-42"))
    candidate = DerivativeCandidate(
        identity=ArtifactIdentity(OwnerAuthority.DRI, OpaqueReference("dri", "embedding-42")),
        generation=Generation(8),
        source_identity=source,
        source_generation=Generation(4),
        recipe=RebuildRecipe(OpaqueReference("recipe", "embed-v1"), "v1"),
    )
    return DerivativeCandidate(**{**candidate.__dict__, **changes})


def test_rebuildable_derivative_is_not_archive_authority() -> None:
    source_lookup = FakeSourceLookup()
    recipe_lookup = FakeRecipeLookup()

    result = DerivativeDispositionDoctor(source_lookup, recipe_lookup).diagnose(_candidate())

    assert result.disposition is DerivativeDisposition.REBUILDABLE_NON_AUTHORITATIVE
    assert result.findings == ()
    assert result.archive_authority is False
    assert source_lookup.calls
    assert recipe_lookup.calls


def test_missing_source_or_rebuild_recipe_is_loud() -> None:
    missing_source = DerivativeDispositionDoctor(FakeSourceLookup(False), FakeRecipeLookup()).diagnose(
        _candidate()
    )
    missing_recipe = DerivativeDispositionDoctor(FakeSourceLookup(), FakeRecipeLookup(False)).diagnose(
        _candidate(recipe=None)
    )
    missing_generation = DerivativeDispositionDoctor(FakeSourceLookup(), FakeRecipeLookup()).diagnose(
        _candidate(source_generation=None)
    )
    authority_misuse = DerivativeDispositionDoctor(FakeSourceLookup(), FakeRecipeLookup()).diagnose(
        _candidate(claimed_archive_authority=True)
    )

    assert missing_source.disposition is DerivativeDisposition.REFUSED
    assert DerivativeFindingCode.STALE_SOURCE_LINEAGE in {
        finding.code for finding in missing_source.findings
    }
    assert missing_recipe.disposition is DerivativeDisposition.REFUSED
    assert DerivativeFindingCode.MISSING_REBUILD_RECIPE in {
        finding.code for finding in missing_recipe.findings
    }
    assert missing_generation.disposition is DerivativeDisposition.REFUSED
    assert DerivativeFindingCode.MISSING_SOURCE_GENERATION in {
        finding.code for finding in missing_generation.findings
    }
    assert authority_misuse.disposition is DerivativeDisposition.REFUSED
    assert DerivativeFindingCode.DERIVATIVE_AS_ARCHIVE_AUTHORITY in {
        finding.code for finding in authority_misuse.findings
    }


def test_explicit_nonrebuildable_reclassification_routes_to_owner_adapter() -> None:
    result = DerivativeDispositionDoctor(FakeSourceLookup(), FakeRecipeLookup()).diagnose(
        _candidate(
            explicitly_nonrebuildable=True,
            requested_owner_admission=OwnerAdmissionRoute.RETAINED_SOURCE,
        )
    )

    assert result.disposition is DerivativeDisposition.REQUIRES_OWNER_ADMISSION
    assert result.owner_admission is OwnerAdmissionRoute.RETAINED_SOURCE
    assert result.archive_authority is False


def test_derivative_doctor_is_read_only() -> None:
    source_lookup = FakeSourceLookup()
    recipe_lookup = FakeRecipeLookup()
    candidate = _candidate()

    result = DerivativeDispositionDoctor(source_lookup, recipe_lookup).diagnose(candidate)

    assert result.candidate is candidate
    assert source_lookup.calls == [(candidate.source_identity, candidate.source_generation)]
    assert recipe_lookup.calls == [candidate.recipe]
    assert not hasattr(result, "receipt")
    assert not hasattr(result, "delete")
    assert not hasattr(result, "reclassify")
