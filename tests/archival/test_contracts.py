from app.archival import (
    ArtifactClass,
    ArtifactDescriptor,
    ArtifactIdentity,
    AuthorityOwner,
    Durability,
    PolicyProfile,
    Provenance,
    Receipt,
    RepresentationDescriptor,
    RepresentationRef,
    Liveness,
    TransitionStage,
)


def _artifact(
    artifact_class: ArtifactClass = ArtifactClass.RAW_SOURCE,
    policy: PolicyProfile = PolicyProfile.RAW_EVIDENCE,
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        identity=ArtifactIdentity("artifact-001"),
        artifact_class=artifact_class,
        durability=Durability.DURABLE,
        owner=AuthorityOwner.SOURCE_ADAPTER,
        policy=policy,
        generation=1,
        provenance=Provenance(("capture-001",), "heimdal", "2026-08-22T20:00:00Z"),
    )


def test_artifact_classification_preserves_authority_and_durability_axes():
    artifact = _artifact(ArtifactClass.HUMAN_ARTIFACT, PolicyProfile.HKA_RECOVERY)

    assert artifact.artifact_class is ArtifactClass.HUMAN_ARTIFACT
    assert artifact.durability is Durability.DURABLE
    assert artifact.owner is AuthorityOwner.SOURCE_ADAPTER
    assert artifact.policy is PolicyProfile.HKA_RECOVERY
    assert artifact.generation == 1
    assert artifact.provenance.origin == "heimdal"


def test_location_cannot_mint_identity_or_access_authority():
    for constructor, label in ((ArtifactIdentity, "artifact"), (RepresentationRef, "representation")):
        for location in ("/tmp/raw.bin", "file://archive/raw.bin", "volume\\raw.bin"):
            try:
                constructor(location)
            except ValueError as exc:
                assert label in str(exc)
            else:
                raise AssertionError(f"{label} location was accepted as authority")

    receipt = Receipt(
        "archive.verified",
        ArtifactIdentity("artifact-001"),
        RepresentationRef("repr-001"),
        1,
        TransitionStage.VERIFIED,
        Liveness.ACTIVE,
    )
    assert not hasattr(receipt, "path")


def test_policy_profiles_keep_class_specific_terminal_outcomes():
    assert "erased" in PolicyProfile.RAW_EVIDENCE.terminal_outcomes
    assert "recovered" in PolicyProfile.HKA_RECOVERY.terminal_outcomes
    assert "discarded" in PolicyProfile.REBUILDABLE_DERIVATIVE.terminal_outcomes
    assert all("unavailable" not in profile.terminal_outcomes for profile in PolicyProfile)
    assert "erased" not in PolicyProfile.HKA_RECOVERY.terminal_outcomes
    assert "erased" not in PolicyProfile.REBUILDABLE_DERIVATIVE.terminal_outcomes


def test_receipts_cannot_claim_contradictory_stage_and_liveness():
    try:
        Receipt(
            "archive.erased",
            ArtifactIdentity("artifact-001"),
            None,
            1,
            TransitionStage.ERASED,
            Liveness.ACTIVE,
        )
    except ValueError as exc:
        assert "incompatible" in str(exc)
    else:
        raise AssertionError("erased receipt accepted active liveness")


def test_content_identity_is_not_a_path_or_uri():
    for value in ("/tmp/raw.bin", "file://archive/raw.bin", "archive\\raw.bin"):
        try:
            RepresentationDescriptor(
                RepresentationRef("repr-001"),
                ArtifactIdentity("artifact-001"),
                1,
                value,
                "audio/wav",
                True,
            )
        except ValueError as exc:
            assert "content identity" in str(exc)
        else:
            raise AssertionError("location accepted as content identity")


def test_representation_is_opaque_and_generation_bound():
    representation = RepresentationDescriptor(
        reference=RepresentationRef("repr-001"),
        artifact=ArtifactIdentity("artifact-001"),
        generation=1,
        content_identity="sha256:abc",
        format="audio/wav",
        encrypted=True,
    )

    assert representation.reference.value == "repr-001"
    assert representation.artifact.value == "artifact-001"
    assert representation.encrypted is True
