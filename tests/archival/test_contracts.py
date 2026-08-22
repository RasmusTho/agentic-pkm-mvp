"""Acceptance tests for GAF-01's provider-free archival contract."""

from __future__ import annotations

import pytest

from app.archival.contracts import (
    AccessAuthority,
    ArchivalReceipt,
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    DerivationClass,
    DoctorFinding,
    DurabilityClass,
    Generation,
    Liveness,
    LivenessState,
    OpaqueReference,
    OwnerAuthority,
    PolicyProfile,
    ProvenanceRef,
    RepresentationReservation,
    RepresentationRef,
    TransitionStage,
    VerificationResult,
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


def test_typed_opaque_references_preserve_owner_tokens_without_lexical_path_inference() -> None:
    raw_ref = OpaqueReference("heimraw", "123e4567-e89b-12d3-a456-426614174000")
    grant_ref = OpaqueReference("grant", "karakeep.source.ingestion")
    extensionless_ref = OpaqueReference("owner", "Archive")
    dot_bearing_ref = OpaqueReference("owner", "Archive.md")

    assert ArtifactIdentity(OwnerAuthority.HKA, raw_ref).owner_native_id is raw_ref
    assert RepresentationRef("heimdal", raw_ref).opaque_id is raw_ref
    assert AccessAuthority(OwnerAuthority.GOV, grant_ref).grant_ref is grant_ref
    assert RepresentationRef("owner", extensionless_ref).opaque_id is extensionless_ref
    assert RepresentationRef("owner", dot_bearing_ref).opaque_id is dot_bearing_ref


def test_raw_strings_cannot_cross_archival_authority_boundaries() -> None:
    artifact = ArtifactIdentity(OwnerAuthority.HKA, OpaqueReference("hka", "note-42"))
    generation = Generation(1)
    liveness = Liveness(LivenessState.ACTIVE, OpaqueReference("live", "note-42"))
    representation = RepresentationRef("heimdal", OpaqueReference("heimraw", "object-42"))

    constructors = (
        lambda: ArtifactIdentity(OwnerAuthority.HKA, "Archive.md"),
        lambda: RepresentationRef("heimdal", "Archive.md"),
        lambda: AccessAuthority(OwnerAuthority.GOV, "Archive.md"),
        lambda: ProvenanceRef("origin", "Archive.md"),
        lambda: Liveness(LivenessState.ACTIVE, "Archive.md"),
        lambda: RepresentationReservation(artifact, representation, generation, "Archive.md"),
        lambda: VerificationResult(representation, generation, True, "Archive.md"),
        lambda: ArchivalReceipt(
            "Archive.md",
            artifact,
            generation,
            TransitionStage.ACTIVE,
            PolicyProfile.HKA_RECOVERY,
            liveness,
            (),
            (),
        ),
        lambda: DoctorFinding("missing", artifact, representation, liveness, "Archive.md"),
    )

    for constructor in constructors:
        with pytest.raises(ValueError, match="typed opaque reference"):
            constructor()


def test_nested_reference_collections_require_contract_types() -> None:
    artifact = ArtifactIdentity(OwnerAuthority.HKA, OpaqueReference("hka", "note-42"))
    generation = Generation(1)
    liveness = Liveness(LivenessState.ACTIVE, OpaqueReference("live", "note-42"))

    with pytest.raises(ValueError, match="provenance_refs"):
        ArtifactDescriptor(
            identity=artifact,
            artifact_class=ArtifactClass.HUMAN,
            derivation=DerivationClass.SOURCE,
            durability=DurabilityClass.DURABLE,
            owner=OwnerAuthority.HKA,
            generation=generation,
            provenance_refs=("Archive.md",),
            policy_profile=PolicyProfile.HKA_RECOVERY,
        )

    receipt_fields = {
        "receipt_ref": OpaqueReference("receipt", "receipt-42"),
        "artifact": artifact,
        "generation": generation,
        "stage": TransitionStage.ACTIVE,
        "policy_profile": PolicyProfile.HKA_RECOVERY,
        "liveness": liveness,
    }
    with pytest.raises(ValueError, match="provenance_refs"):
        ArchivalReceipt(**receipt_fields, provenance_refs=("Archive.md",), representation_refs=())
    with pytest.raises(ValueError, match="representation_refs"):
        ArchivalReceipt(**receipt_fields, provenance_refs=(), representation_refs=("Archive.md",))


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
