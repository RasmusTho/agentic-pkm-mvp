"""Acceptance tests for GAF-01's provider-free archival contract."""

from __future__ import annotations

import pytest

from app.archival.contracts import (
    AccessAuthority,
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    DerivationClass,
    DurabilityClass,
    Generation,
    OpaqueReference,
    OwnerAuthority,
    PolicyProfile,
    ProvenanceRef,
    RepresentationRef,
)


def test_artifact_classification_preserves_authority_and_durability_axes() -> None:
    artifact = ArtifactDescriptor(
        identity=ArtifactIdentity(OwnerAuthority.HKA, OpaqueReference("hka", "note-42")),
        artifact_class=ArtifactClass.HUMAN,
        derivation=DerivationClass.SOURCE,
        durability=DurabilityClass.DURABLE,
        owner=OwnerAuthority.HKA,
        generation=Generation(4),
        provenance_refs=(ProvenanceRef("origin", OpaqueReference("hka", "human-note")),),
        policy_profile=PolicyProfile.HKA_RECOVERY,
    )

    assert set(ArtifactClass) == {
        ArtifactClass.SOURCE,
        ArtifactClass.HUMAN,
        ArtifactClass.DERIVED,
        ArtifactClass.RECEIPT,
    }
    assert artifact.identity.owner is OwnerAuthority.HKA
    assert artifact.derivation is DerivationClass.SOURCE
    assert artifact.durability is DurabilityClass.DURABLE
    assert artifact.generation.value == 4
    assert artifact.provenance_refs == (
        ProvenanceRef("origin", OpaqueReference("hka", "human-note")),
    )


def test_location_cannot_mint_identity_or_access_authority() -> None:
    location_values = (
        "/vault/Notes/Archive.md",
        "vault/Notes/Archive.md",
        r"C:\\vault\\Archive.md",
        "private-archive/object",
        "file:///cold/archive/object",
        "s3://private-archive/read-grant",
        "ssh://archive-host/object",
    )

    for location in location_values:
        with pytest.raises(ValueError, match="typed opaque reference"):
            ArtifactIdentity(OwnerAuthority.HKA, location)
        with pytest.raises(ValueError, match="typed opaque reference"):
            RepresentationRef("heimdal", location)
        with pytest.raises(ValueError, match="typed opaque reference"):
            AccessAuthority(OwnerAuthority.GOV, location)

    with pytest.raises(ValueError, match="location text"):
        OpaqueReference("heimraw", "vault/Notes/Archive.md")


def test_namespaced_opaque_handles_remain_valid_without_string_parsing() -> None:
    raw_ref = OpaqueReference("heimraw", "123e4567-e89b-12d3-a456-426614174000")
    grant_ref = OpaqueReference("grant", "karakeep-source-ingestion")

    assert ArtifactIdentity(OwnerAuthority.HKA, raw_ref).owner_native_id is raw_ref
    assert RepresentationRef("heimdal", raw_ref).opaque_id is raw_ref
    assert AccessAuthority(OwnerAuthority.GOV, grant_ref).grant_ref is grant_ref


def test_class_adapter_identities_require_distinct_owner_namespaces() -> None:
    heimdal_identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("heimdal", "object-42"),
        owner_namespace="heimdal",
    )
    retained_source_identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("retained-source", "object-42"),
        owner_namespace="retained-source",
    )

    assert heimdal_identity != retained_source_identity

    with pytest.raises(ValueError, match="namespace"):
        ArtifactIdentity(OwnerAuthority.CLASS_ADAPTER, OpaqueReference("heimdal", "object-42"))


def test_policy_profiles_keep_class_specific_terminal_outcomes() -> None:
    outcomes = {profile: profile.terminal_outcome for profile in PolicyProfile}

    assert len(set(outcomes.values())) == len(PolicyProfile)
    assert PolicyProfile.RAW_EVIDENCE.allows_erase_or_revoke
    assert not PolicyProfile.RETAINED_SOURCE.allows_erase_or_revoke
    assert not PolicyProfile.HKA_RECOVERY.allows_erase_or_revoke
    assert PolicyProfile.REBUILDABLE_DERIVATIVE.allows_discard_when_rebuildable
