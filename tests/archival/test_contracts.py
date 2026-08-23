"""Acceptance tests for GAF-01's provider-free archival contract."""

from __future__ import annotations

from types import SimpleNamespace

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
    Representation,
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
        ("typed opaque reference", lambda: ArtifactIdentity(OwnerAuthority.HKA, "Archive.md")),
        ("typed opaque reference", lambda: RepresentationRef("heimdal", "Archive.md")),
        ("typed opaque reference", lambda: AccessAuthority(OwnerAuthority.GOV, "Archive.md")),
        ("typed opaque reference", lambda: ProvenanceRef("origin", "Archive.md")),
        ("typed opaque reference", lambda: Liveness(LivenessState.ACTIVE, "Archive.md")),
        (
            "ref",
            lambda: Representation(
                artifact,
                "Archive.md",
                generation,
                TransitionStage.ACTIVE,
                liveness,
            ),
        ),
        (
            "target",
            lambda: RepresentationReservation(
                artifact,
                "Archive.md",
                generation,
                OpaqueReference("reservation", "reservation-42"),
            ),
        ),
        (
            "typed opaque reference",
            lambda: RepresentationReservation(artifact, representation, generation, "Archive.md"),
        ),
        (
            "representation",
            lambda: VerificationResult(
                "Archive.md",
                generation,
                True,
                OpaqueReference("verify", "verify-42"),
            ),
        ),
        (
            "typed opaque reference",
            lambda: VerificationResult(representation, generation, True, "Archive.md"),
        ),
        (
            "typed opaque reference",
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
        ),
        (
            "artifact",
            lambda: ArchivalReceipt(
                OpaqueReference("receipt", "receipt-42"),
                "Archive.md",
                generation,
                TransitionStage.ACTIVE,
                PolicyProfile.HKA_RECOVERY,
                liveness,
                (),
                (),
            ),
        ),
        (
            "liveness",
            lambda: ArchivalReceipt(
                OpaqueReference("receipt", "receipt-42"),
                artifact,
                generation,
                TransitionStage.ACTIVE,
                PolicyProfile.HKA_RECOVERY,
                "Archive.md",
                (),
                (),
            ),
        ),
        (
            "artifact",
            lambda: DoctorFinding(
                "missing",
                "Archive.md",
                representation,
                liveness,
                OpaqueReference("doctor", "finding-42"),
            ),
        ),
        (
            "representation",
            lambda: DoctorFinding(
                "missing",
                artifact,
                "Archive.md",
                liveness,
                OpaqueReference("doctor", "finding-42"),
            ),
        ),
        (
            "liveness",
            lambda: DoctorFinding(
                "missing",
                artifact,
                representation,
                "Archive.md",
                OpaqueReference("doctor", "finding-42"),
            ),
        ),
        (
            "typed opaque reference",
            lambda: DoctorFinding("missing", artifact, representation, liveness, "Archive.md"),
        ),
    )

    for expected_error, constructor in constructors:
        with pytest.raises(ValueError, match=expected_error):
            constructor()


def test_composed_authority_fields_require_contract_types() -> None:
    opaque_ref = OpaqueReference("owner", "object-42")
    artifact = ArtifactIdentity(OwnerAuthority.HKA, opaque_ref)
    generation = Generation(1)
    liveness = Liveness(LivenessState.ACTIVE, OpaqueReference("live", "object-42"))
    representation = RepresentationRef("heimdal", OpaqueReference("heimraw", "object-42"))
    provenance = ProvenanceRef("origin", OpaqueReference("source", "object-42"))
    duck_owner = SimpleNamespace(value=OwnerAuthority.HKA.value)
    duck_artifact = SimpleNamespace(
        owner=OwnerAuthority.HKA,
        owner_native_id=opaque_ref,
        owner_namespace=None,
    )
    duck_generation = SimpleNamespace(value=1)
    duck_liveness = SimpleNamespace(
        state=LivenessState.ACTIVE,
        evidence_ref=OpaqueReference("live", "object-42"),
    )
    duck_representation = SimpleNamespace(
        adapter="heimdal",
        opaque_id=OpaqueReference("heimraw", "object-42"),
    )
    descriptor_fields = {
        "identity": artifact,
        "artifact_class": ArtifactClass.HUMAN,
        "derivation": DerivationClass.SOURCE,
        "durability": DurabilityClass.DURABLE,
        "owner": OwnerAuthority.HKA,
        "generation": generation,
        "provenance_refs": (provenance,),
        "policy_profile": PolicyProfile.HKA_RECOVERY,
    }
    receipt_fields = {
        "receipt_ref": OpaqueReference("receipt", "receipt-42"),
        "artifact": artifact,
        "generation": generation,
        "stage": TransitionStage.ACTIVE,
        "policy_profile": PolicyProfile.HKA_RECOVERY,
        "liveness": liveness,
        "provenance_refs": (provenance,),
        "representation_refs": (representation,),
    }

    invalid_constructors = (
        ("owner", lambda: ArtifactIdentity(duck_owner, opaque_ref)),
        ("issuer", lambda: AccessAuthority(duck_owner, opaque_ref)),
        (
            "identity",
            lambda: ArtifactDescriptor(**{**descriptor_fields, "identity": duck_artifact}),
        ),
        (
            "artifact_class",
            lambda: ArtifactDescriptor(
                **{
                    **descriptor_fields,
                    "artifact_class": SimpleNamespace(value=ArtifactClass.HUMAN.value),
                }
            ),
        ),
        (
            "derivation",
            lambda: ArtifactDescriptor(
                **{
                    **descriptor_fields,
                    "derivation": SimpleNamespace(value=DerivationClass.SOURCE.value),
                }
            ),
        ),
        (
            "durability",
            lambda: ArtifactDescriptor(
                **{
                    **descriptor_fields,
                    "durability": SimpleNamespace(value=DurabilityClass.DURABLE.value),
                }
            ),
        ),
        (
            "owner",
            lambda: ArtifactDescriptor(**{**descriptor_fields, "owner": duck_owner}),
        ),
        (
            "generation",
            lambda: ArtifactDescriptor(**{**descriptor_fields, "generation": duck_generation}),
        ),
        (
            "policy_profile",
            lambda: ArtifactDescriptor(
                **{
                    **descriptor_fields,
                    "policy_profile": SimpleNamespace(value=PolicyProfile.HKA_RECOVERY.value),
                }
            ),
        ),
        (
            "state",
            lambda: Liveness(
                SimpleNamespace(value=LivenessState.ACTIVE.value),
                OpaqueReference("live", "object-42"),
            ),
        ),
        (
            "artifact",
            lambda: Representation(
                duck_artifact,
                representation,
                generation,
                TransitionStage.ACTIVE,
                liveness,
            ),
        ),
        (
            "ref",
            lambda: Representation(
                artifact,
                duck_representation,
                generation,
                TransitionStage.ACTIVE,
                liveness,
            ),
        ),
        (
            "generation",
            lambda: Representation(
                artifact,
                representation,
                duck_generation,
                TransitionStage.ACTIVE,
                liveness,
            ),
        ),
        (
            "stage",
            lambda: Representation(
                artifact,
                representation,
                generation,
                SimpleNamespace(value=TransitionStage.ACTIVE.value),
                liveness,
            ),
        ),
        (
            "liveness",
            lambda: Representation(
                artifact,
                representation,
                generation,
                TransitionStage.ACTIVE,
                duck_liveness,
            ),
        ),
        (
            "artifact",
            lambda: RepresentationReservation(
                duck_artifact,
                representation,
                generation,
                OpaqueReference("reservation", "reservation-42"),
            ),
        ),
        (
            "target",
            lambda: RepresentationReservation(
                artifact,
                duck_representation,
                generation,
                OpaqueReference("reservation", "reservation-42"),
            ),
        ),
        (
            "generation",
            lambda: RepresentationReservation(
                artifact,
                representation,
                duck_generation,
                OpaqueReference("reservation", "reservation-42"),
            ),
        ),
        (
            "representation",
            lambda: VerificationResult(
                duck_representation,
                generation,
                True,
                OpaqueReference("verify", "verify-42"),
            ),
        ),
        (
            "generation",
            lambda: VerificationResult(
                representation,
                duck_generation,
                True,
                OpaqueReference("verify", "verify-42"),
            ),
        ),
        (
            "artifact",
            lambda: ArchivalReceipt(**{**receipt_fields, "artifact": duck_artifact}),
        ),
        (
            "generation",
            lambda: ArchivalReceipt(**{**receipt_fields, "generation": duck_generation}),
        ),
        (
            "stage",
            lambda: ArchivalReceipt(
                **{
                    **receipt_fields,
                    "stage": SimpleNamespace(value=TransitionStage.ACTIVE.value),
                }
            ),
        ),
        (
            "policy_profile",
            lambda: ArchivalReceipt(
                **{
                    **receipt_fields,
                    "policy_profile": SimpleNamespace(value=PolicyProfile.HKA_RECOVERY.value),
                }
            ),
        ),
        (
            "liveness",
            lambda: ArchivalReceipt(**{**receipt_fields, "liveness": duck_liveness}),
        ),
        (
            "artifact",
            lambda: DoctorFinding(
                "missing",
                duck_artifact,
                representation,
                liveness,
                OpaqueReference("doctor", "finding-42"),
            ),
        ),
        (
            "representation",
            lambda: DoctorFinding(
                "missing",
                artifact,
                duck_representation,
                liveness,
                OpaqueReference("doctor", "finding-42"),
            ),
        ),
        (
            "liveness",
            lambda: DoctorFinding(
                "missing",
                artifact,
                representation,
                duck_liveness,
                OpaqueReference("doctor", "finding-42"),
            ),
        ),
    )

    for field_name, constructor in invalid_constructors:
        with pytest.raises(ValueError, match=field_name):
            constructor()

    finding = DoctorFinding(
        "missing",
        None,
        None,
        liveness,
        OpaqueReference("doctor", "finding-42"),
    )
    assert finding.artifact is None
    assert finding.representation is None


def test_generation_requires_non_boolean_non_negative_integer() -> None:
    class IntegerSubclass(int):
        pass

    for invalid_value in (True, False, -1, 1.0, "1", IntegerSubclass(1)):
        with pytest.raises(ValueError, match="non-negative integer"):
            Generation(invalid_value)

    assert Generation(0).value == 0
    assert Generation(1).value == 1


def test_boolean_contract_fields_require_exact_bool_values() -> None:
    artifact = ArtifactIdentity(OwnerAuthority.HKA, OpaqueReference("hka", "note-42"))
    generation = Generation(1)
    liveness = Liveness(LivenessState.ACTIVE, OpaqueReference("live", "note-42"))
    representation = RepresentationRef("heimdal", OpaqueReference("heimraw", "object-42"))
    receipt_fields = {
        "receipt_ref": OpaqueReference("receipt", "receipt-42"),
        "artifact": artifact,
        "generation": generation,
        "stage": TransitionStage.ACTIVE,
        "policy_profile": PolicyProfile.HKA_RECOVERY,
        "liveness": liveness,
        "provenance_refs": (),
        "representation_refs": (),
    }

    for invalid_value in (0, 1, "true", None):
        with pytest.raises(ValueError, match="verified"):
            VerificationResult(
                representation,
                generation,
                invalid_value,
                OpaqueReference("verify", "verify-42"),
            )
        with pytest.raises(ValueError, match="redacted"):
            ArchivalReceipt(**receipt_fields, redacted=invalid_value)

    assert not VerificationResult(
        representation,
        generation,
        False,
        OpaqueReference("verify", "verify-42"),
    ).verified
    with pytest.raises(ValueError, match="must be redacted"):
        ArchivalReceipt(**receipt_fields, redacted=False)


def test_artifact_descriptor_owner_matches_identity_owner() -> None:
    artifact = ArtifactIdentity(OwnerAuthority.HKA, OpaqueReference("hka", "note-42"))

    with pytest.raises(ValueError, match="owner must match"):
        ArtifactDescriptor(
            identity=artifact,
            artifact_class=ArtifactClass.HUMAN,
            derivation=DerivationClass.SOURCE,
            durability=DurabilityClass.DURABLE,
            owner=OwnerAuthority.GOV,
            generation=Generation(1),
            provenance_refs=(ProvenanceRef("origin", OpaqueReference("hka", "human-note")),),
            policy_profile=PolicyProfile.HKA_RECOVERY,
        )


def test_nested_reference_collections_require_contract_types() -> None:
    artifact = ArtifactIdentity(OwnerAuthority.HKA, OpaqueReference("hka", "note-42"))
    generation = Generation(1)
    liveness = Liveness(LivenessState.ACTIVE, OpaqueReference("live", "note-42"))

    provenance = ProvenanceRef("origin", OpaqueReference("hka", "human-note"))
    representation = RepresentationRef("heimdal", OpaqueReference("heimraw", "object-42"))
    descriptor_fields = {
        "identity": artifact,
        "artifact_class": ArtifactClass.HUMAN,
        "derivation": DerivationClass.SOURCE,
        "durability": DurabilityClass.DURABLE,
        "owner": OwnerAuthority.HKA,
        "generation": generation,
        "policy_profile": PolicyProfile.HKA_RECOVERY,
    }

    for invalid_refs in ([], [provenance], (), (provenance, "Archive.md")):
        with pytest.raises(ValueError, match="provenance_refs"):
            ArtifactDescriptor(**descriptor_fields, provenance_refs=invalid_refs)

    receipt_fields = {
        "receipt_ref": OpaqueReference("receipt", "receipt-42"),
        "artifact": artifact,
        "generation": generation,
        "stage": TransitionStage.ACTIVE,
        "policy_profile": PolicyProfile.HKA_RECOVERY,
        "liveness": liveness,
    }
    for invalid_refs in ([provenance], (provenance, "Archive.md")):
        with pytest.raises(ValueError, match="provenance_refs"):
            ArchivalReceipt(
                **receipt_fields,
                provenance_refs=invalid_refs,
                representation_refs=(),
            )
    for invalid_refs in ([representation], (representation, "Archive.md")):
        with pytest.raises(ValueError, match="representation_refs"):
            ArchivalReceipt(
                **receipt_fields,
                provenance_refs=(),
                representation_refs=invalid_refs,
            )


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


def test_class_adapter_identities_preserve_namespace() -> None:
    identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("adapter-native", "object-42"),
        owner_namespace="retained-source",
    )

    assert identity.owner is OwnerAuthority.CLASS_ADAPTER
    assert identity.owner_namespace == "retained-source"


def test_class_adapter_namespace_collision_is_rejected() -> None:
    heimdal_identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("adapter-native", "object-42"),
        owner_namespace="heimdal",
    )
    retained_source_identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("adapter-native", "object-42"),
        owner_namespace="retained-source",
    )

    assert heimdal_identity == ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("adapter-native", "object-42"),
        owner_namespace="heimdal",
    )
    assert heimdal_identity != retained_source_identity


def test_namespace_survives_reservation_and_receipt_identity() -> None:
    identity = ArtifactIdentity(
        OwnerAuthority.CLASS_ADAPTER,
        OpaqueReference("adapter-native", "object-42"),
        owner_namespace="retained-source",
    )
    generation = Generation(1)
    reservation = RepresentationReservation(
        identity,
        RepresentationRef("archive", OpaqueReference("archive", "object-42")),
        generation,
        OpaqueReference("reservation", "reservation-42"),
    )
    receipt = ArchivalReceipt(
        OpaqueReference("receipt", "receipt-42"),
        identity,
        generation,
        TransitionStage.ACTIVE,
        PolicyProfile.RETAINED_SOURCE,
        Liveness(LivenessState.ACTIVE, OpaqueReference("liveness", "object-42")),
        (),
        (),
    )

    assert reservation.artifact.owner_namespace == "retained-source"
    assert receipt.artifact.owner_namespace == "retained-source"
    assert reservation.artifact == receipt.artifact == identity


def test_policy_profiles_keep_class_specific_terminal_outcomes() -> None:
    outcomes = {profile: profile.terminal_outcome for profile in PolicyProfile}

    assert len(set(outcomes.values())) == len(PolicyProfile)
    assert PolicyProfile.RAW_EVIDENCE.allows_erase_or_revoke
    assert not PolicyProfile.RETAINED_SOURCE.allows_erase_or_revoke
    assert not PolicyProfile.HKA_RECOVERY.allows_erase_or_revoke
    assert PolicyProfile.REBUILDABLE_DERIVATIVE.allows_discard_when_rebuildable
