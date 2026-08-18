from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.models import BuilderOpsValidationError
from app.builderops.promotion_gateway import BuilderOpsPromotionError, BuilderOpsPromotionGateway
from app.builderops.store import SqliteBuilderOpsStore


def _actor() -> dict[str, str]:
    return {"actor_type": "agent", "id": "test-agent"}


def _source_refs() -> list[dict[str, str]]:
    return [
        {
            "ref_type": "github_issue",
            "ref": "#4984",
            "authority_surface": "github",
        }
    ]


def _working_artifact_fields(record_id: str = "work_4984_001") -> dict[str, object]:
    return {
        "id": record_id,
        "summary": "Working artifact for admission-contract validation",
        "body": "A bounded Builder Vault research draft.",
        "source_refs": _source_refs(),
        "created_by": _actor(),
        "authority_standing": "non_normative",
        "derivation_role": "derived",
        "durability_posture": "rebuildable",
        "working_lifecycle_stage": "synthesize",
        "promotion_posture": "not_promoted",
        "location_context": "builder_vault",
        "provenance": {
            "source_refs": _source_refs(),
            "derived_from": _source_refs(),
            "transformation": "Compare source contract with existing BuilderOps envelope.",
            "actor_or_process": "test-agent",
            "observed_at": "2026-08-18T00:00:00Z",
            "source_versions_or_watermarks": ["issue-4984@2026-08-18"],
            "review_or_decision_ref": "unknown",
            "promotion_ref": "unknown",
            "supersedes_refs": ["unknown"],
            "receipt_refs": ["unknown"],
            "limitations": ["Not authority outside BuilderOps."],
        },
        "receipt_refs": [],
    }


@pytest.fixture
def store(tmp_path: Path) -> SqliteBuilderOpsStore:
    result = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    result.initialize()
    return result


def test_working_artifact_round_trip_preserves_classification_and_provenance(
    store: SqliteBuilderOpsStore,
) -> None:
    created = store.create_working_artifact(**_working_artifact_fields())

    read_back = store.get_record(created["id"])

    assert read_back is not None
    for field in (
        "authority_standing",
        "derivation_role",
        "durability_posture",
        "working_lifecycle_stage",
        "promotion_posture",
        "location_context",
        "provenance",
    ):
        assert read_back[field] == created[field]
    assert read_back["authority_standing"] == "non_normative"
    assert read_back["provenance"]["review_or_decision_ref"] == "unknown"


def test_working_artifact_uses_existing_builderops_store(
    store: SqliteBuilderOpsStore,
) -> None:
    created = store.create_working_artifact(**_working_artifact_fields())

    assert store.list_records("BuilderVaultWorkingArtifact") == [created]
    assert store.get_record(created["id"]) == created


def test_working_artifact_promotion_requires_explicit_target_and_receipt(
    store: SqliteBuilderOpsStore,
) -> None:
    artifact = store.create_working_artifact(**_working_artifact_fields())
    intent = store.create_promotion_intent(
        id="prom_4984_001",
        summary="Propose the working artifact for owner-doc writeback",
        source_refs=[
            {
                "ref_type": "builderops_object",
                "ref": artifact["id"],
                "authority_surface": "builderops",
            }
        ],
        target_authority_surface="owner_doc_writeback_proposal",
        target_action="propose",
        target_ref="docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md",
        target_authority_class="decision",
        intended_output="A reviewed owner-document proposal.",
        receipt_refs=[],
    )
    gateway = BuilderOpsPromotionGateway(store)
    lease = store.acquire_lease(intent["id"], actor=_actor())

    with pytest.raises(BuilderOpsPromotionError, match="accepted before promoted"):
        gateway.transition_intent(
            intent["id"],
            decision="promoted",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="promote-before-review",
            rationale="Must not promote without review.",
        )

    accepted = gateway.transition_intent(
        intent["id"],
        decision="accepted",
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key="accept-working-artifact-proposal",
        rationale="The explicit target and review outcome are recorded.",
    )
    assert accepted["receipt"]["event_type"] == "state_transition"

    with pytest.raises(BuilderOpsPromotionError, match="requires result_refs"):
        gateway.transition_intent(
            intent["id"],
            decision="promoted",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="promote-without-receipt-evidence",
            rationale="A target receipt/equivalent is required.",
        )

    promoted = gateway.transition_intent(
        intent["id"],
        decision="promoted",
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key="promote-with-target-receipt",
        rationale="Target authority evidence is explicit.",
        result_refs=[
            {
                "ref_type": "github_pr",
                "ref": "#5000",
                "authority_surface": "github",
            }
        ],
    )
    assert promoted["record"]["promotion_status"] == "promoted"
    assert promoted["receipt"]["result_refs"][0]["ref"] == "#5000"


def test_working_artifact_terminal_transition_preserves_lineage(
    store: SqliteBuilderOpsStore,
) -> None:
    artifact = store.create_working_artifact(**_working_artifact_fields())
    lease = store.acquire_lease(artifact["id"], actor=_actor())

    with pytest.raises(BuilderOpsValidationError, match="requires successor_refs"):
        store.transition_record_state(
            artifact["id"],
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="retire-without-lineage",
            source_refs=_source_refs(),
            summary="Retire working artifact",
            action="retire",
            receipt_body="Must retain terminal provenance.",
            lifecycle_state="archived",
        )

    retired = store.transition_record_state(
        artifact["id"],
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key="retire-with-lineage",
        source_refs=_source_refs(),
        summary="Retire working artifact",
        action="retire",
        receipt_body="Retired with a governed outcome reference.",
        lifecycle_state="archived",
        successor_refs=[
            {
                "ref_type": "promotion_intent",
                "ref": "prom_4984_001",
                "authority_surface": "builderops",
            }
        ],
    )

    assert retired["record"]["source_refs"] == _source_refs()
    assert retired["record"]["successor_refs"][0]["ref"] == "prom_4984_001"
    assert retired["receipt"]["source_refs"] == _source_refs()
    assert retired["receipt"]["id"] in retired["record"]["receipt_refs"]

    for disposition, lifecycle_state, promotion_status in (
        ("supersede", "superseded", None),
        ("discard", "discarded", None),
        ("reject-promotion", None, "rejected"),
    ):
        candidate = store.create_working_artifact(
            **_working_artifact_fields(f"work_4984_{disposition}")
        )
        candidate_lease = store.acquire_lease(candidate["id"], actor=_actor())
        result = store.transition_record_state(
            candidate["id"],
            actor=_actor(),
            lease_id=candidate_lease["lease_id"],
            idempotency_key=f"{disposition}-with-lineage",
            source_refs=_source_refs(),
            summary=f"{disposition} working artifact",
            action=disposition,
            receipt_body="Terminal outcome preserves source lineage and receipt evidence.",
            lifecycle_state=lifecycle_state,
            promotion_status=promotion_status,
            successor_refs=[
                {
                    "ref_type": "promotion_intent",
                    "ref": "prom_4984_001",
                    "authority_surface": "builderops",
                }
            ],
        )
        assert result["record"]["successor_refs"][0]["ref"] == "prom_4984_001"
        assert result["receipt"]["source_refs"] == _source_refs()
