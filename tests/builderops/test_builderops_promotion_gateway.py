from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.models import (
    PROMOTION_TARGET_ALIASES,
    PROMOTION_TARGET_SURFACES,
    BuilderOpsValidationError,
    canonicalize_promotion_target_surface,
    normalize_record,
)
from app.builderops.promotion_gateway import (
    TARGET_ALIASES,
    TARGET_SPECS,
    BuilderOpsPromotionError,
    BuilderOpsPromotionGateway,
)
from app.builderops.store import SqliteBuilderOpsStore


def _actor(actor_id: str = "codex") -> dict[str, str]:
    return {"actor_type": "agent", "id": actor_id}


def _source_refs() -> list[dict[str, str]]:
    return [
        {"ref_type": "github_issue", "ref": "#1498", "authority_surface": "github"},
        {"ref_type": "github_issue", "ref": "#1504", "authority_surface": "github"},
        {
            "ref_type": "builderops_object",
            "ref": "lrn_gateway_001",
            "authority_surface": "builderops",
        },
    ]


@pytest.fixture()
def store(tmp_path: Path) -> SqliteBuilderOpsStore:
    s = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    s.initialize()
    return s


@pytest.fixture()
def gateway(store: SqliteBuilderOpsStore) -> BuilderOpsPromotionGateway:
    return BuilderOpsPromotionGateway(store)


def _create_intent(
    store: SqliteBuilderOpsStore,
    *,
    intent_id: str = "prom_gateway_001",
    target_surface: str = "github_issue",
    target_ref: str = "pending",
) -> dict[str, object]:
    return store.create_promotion_intent(
        id=intent_id,
        summary="Open follow-up issue from BuilderOps signal",
        target_authority_surface=target_surface,
        target_action="create",
        target_ref=target_ref,
        target_authority_class="operational",
        intended_output="Create a bounded follow-up issue with Verify targets.",
        source_refs=_source_refs(),
        created_by=_actor(),
    )


def test_github_issue_dry_run_preserves_source_refs_and_receipt(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = _create_intent(store)
    now_values = iter(["2026-06-02T12:00:00Z", "2026-06-02T12:01:00Z"])
    monkeypatch.setattr(
        "app.builderops.promotion_gateway.utc_now",
        lambda: next(now_values),
    )

    result = gateway.dry_run_promotion(
        intent["id"],
        actor=_actor(),
        idempotency_key="dry-run:github-issue",
    )

    proposal = result["proposal"]
    receipt = result["receipt"]
    assert proposal["proposal_kind"] == "github_issue_draft"
    assert proposal["would_mutate_authority"] is False
    assert "Parent: #1498" in proposal["body"]
    assert "## Source Anchors" in proposal["body"]
    assert "source_refs" in proposal["body"]
    assert "#1504" in proposal["body"]
    assert proposal["source_refs"] == intent["source_refs"]

    assert receipt["object_type"] == "BuilderOpsReceipt"
    assert receipt["event_type"] == "promotion_dry_run"
    assert receipt["occurred_at"] == "2026-06-02T12:00:00Z"
    assert receipt["target_refs"] == [
        {
            "ref_type": "builderops_object",
            "ref": intent["id"],
            "authority_surface": "builderops",
        }
    ]
    assert receipt["promotion_proposal"]["body"] == proposal["body"]
    assert store.get_record(receipt["id"]) == receipt

    duplicate = gateway.dry_run_promotion(
        intent["id"],
        actor=_actor(),
        idempotency_key="dry-run:github-issue",
    )
    assert duplicate["receipt"] == receipt
    assert duplicate["receipt"]["occurred_at"] == "2026-06-02T12:00:00Z"
    assert len(store.list_records("BuilderOpsReceipt")) == 1


def test_promotion_intent_gateway_state_transitions(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    intent = _create_intent(store)

    with pytest.raises(BuilderOpsPromotionError, match="accepted before promoted"):
        gateway.transition_intent(
            intent["id"],
            decision="promoted",
            actor=_actor(),
            lease_id="missing",
            idempotency_key="transition:bad-promote",
            rationale="Cannot promote before acceptance.",
        )

    lease = store.acquire_lease(intent["id"], actor=_actor())
    accepted = gateway.transition_intent(
        intent["id"],
        decision="accepted",
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key="transition:accepted",
        rationale="Accepted as BuilderOps material for explicit promotion.",
    )
    assert accepted["record"]["lifecycle_state"] == "accepted"
    assert accepted["record"]["promotion_status"] == "promotion_pending"
    assert accepted["receipt"]["promotion_decision"] == "accepted"

    duplicate_accept = gateway.transition_intent(
        intent["id"],
        decision="accepted",
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key="transition:accepted",
        rationale="Accepted as BuilderOps material for explicit promotion.",
    )
    assert duplicate_accept == accepted

    with pytest.raises(BuilderOpsPromotionError, match="requires result_refs"):
        gateway.transition_intent(
            intent["id"],
            decision="promoted",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="transition:promoted-without-result",
            rationale="Promoted transitions need a target receipt.",
        )

    with pytest.raises(BuilderOpsValidationError, match="result_refs entries require"):
        gateway.transition_intent(
            intent["id"],
            decision="promoted",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="transition:promoted-malformed-result",
            rationale="Malformed promotion result ref.",
            result_refs=[{"foo": "bar"}],
        )

    promoted = gateway.transition_intent(
        intent["id"],
        decision="promoted",
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key="transition:promoted",
        rationale="Recorded explicit GitHub Issue promotion result.",
        result_refs=[
            {
                "ref_type": "github_issue",
                "ref": "#2000",
                "authority_surface": "github",
            }
        ],
    )
    assert promoted["record"]["lifecycle_state"] == "promoted"
    assert promoted["record"]["promotion_status"] == "promoted"
    assert promoted["receipt"]["result_refs"] == [
        {
            "ref_type": "github_issue",
            "ref": "#2000",
            "authority_surface": "github",
        }
    ]

    with pytest.raises(BuilderOpsPromotionError, match="already terminal"):
        gateway.transition_intent(
            intent["id"],
            decision="discarded",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="transition:discard-after-promote",
            rationale="Cannot discard after promotion.",
        )


def test_reject_and_discard_create_traceable_receipts(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    rejected_intent = _create_intent(store, intent_id="prom_reject_001")
    rejected_lease = store.acquire_lease(rejected_intent["id"], actor=_actor())
    rejected = gateway.transition_intent(
        rejected_intent["id"],
        decision="rejected",
        actor=_actor(),
        lease_id=rejected_lease["lease_id"],
        idempotency_key="transition:rejected",
        rationale="Review declined this promotion target.",
    )
    assert rejected["record"]["lifecycle_state"] == "discarded"
    assert rejected["record"]["promotion_status"] == "rejected"
    assert rejected["receipt"]["promotion_rationale"] == "Review declined this promotion target."

    discarded_intent = _create_intent(store, intent_id="prom_discard_001")
    discarded_lease = store.acquire_lease(discarded_intent["id"], actor=_actor())
    discarded = gateway.transition_intent(
        discarded_intent["id"],
        decision="discarded",
        actor=_actor(),
        lease_id=discarded_lease["lease_id"],
        idempotency_key="transition:discarded",
        rationale="Signal was obsolete after current repo review.",
    )
    assert discarded["record"]["lifecycle_state"] == "discarded"
    assert discarded["record"]["promotion_status"] == "discarded"
    assert discarded["receipt"]["receipt_body"] == "Signal was obsolete after current repo review."
    assert discarded["receipt"]["promotion_decision"] == "discarded"


def test_repo_doc_and_adr_promotions_are_proposal_only(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    adr_intent = _create_intent(
        store,
        intent_id="prom_adr_001",
        target_surface="adr",
        target_ref="docs/adr/ADR-0010-builderops-vault-authority-boundary.md",
    )
    proposal = gateway.render_proposal(adr_intent["id"])

    assert proposal["proposal_kind"] == "adr_doc_writeback_proposal"
    assert proposal["would_mutate_authority"] is False
    assert proposal["requires_pr"] is True
    assert "normal PR workflow" in proposal["body"]
    assert "## Source Anchors" in proposal["body"]


def test_working_artifact_promotion_stays_proposal_only(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    artifact = store.create_working_artifact(
        id="work_proposal_only_001",
        summary="Builder working artifact remains non-normative",
        body="A bounded artifact that may only produce a proposal.",
        source_refs=[
            {
                "ref_type": "github_issue",
                "ref": "#5013",
                "authority_surface": "github",
            }
        ],
        created_by=_actor(),
        authority_standing="non_normative",
        derivation_role="derived",
        durability_posture="ephemeral",
        working_lifecycle_stage="propose",
        promotion_posture="proposed",
        location_context="builder_vault",
        provenance={
            "source_refs": [
                {
                    "ref_type": "github_issue",
                    "ref": "#5013",
                    "authority_surface": "github",
                }
            ],
            "derived_from": [
                {
                    "ref_type": "github_issue",
                    "ref": "#5013",
                    "authority_surface": "github",
                }
            ],
            "transformation": "Prepare a proposal through the promotion gateway.",
            "actor_or_process": "test-agent",
            "observed_at": "2026-08-22T00:00:00Z",
            "source_versions_or_watermarks": ["issue-5013@2026-08-22"],
            "review_or_decision_ref": "unknown",
            "promotion_ref": "unknown",
            "supersedes_refs": ["unknown"],
            "receipt_refs": ["unknown"],
            "limitations": ["Cannot mutate target authority."],
        },
        receipt_refs=[],
    )
    intent = _create_intent(
        store,
        intent_id="prom_working_artifact_001",
        target_surface="github_issue",
        target_ref="pending",
    )
    proposal = gateway.render_proposal(intent["id"])

    assert artifact["promotion_status"] == "none"
    assert artifact["promotion_posture"] == "proposed"
    assert proposal["would_mutate_authority"] is False
    assert proposal["target_authority_surface"] == "github_issue"


def test_repo_skill_and_workflow_doc_target_renders_as_writeback_proposal(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    intent = _create_intent(
        store,
        intent_id="prom_skill_workflow_doc_001",
        target_surface="repo_skill_and_workflow_doc",
        target_ref="repo_doc:.codex/skills/verification-and-closure/SKILL.md",
    )

    proposal = gateway.render_proposal(intent["id"])

    assert proposal["proposal_kind"] == "owner_doc_writeback_proposal"
    assert proposal["target_authority_surface"] == "owner_doc_writeback_proposal"
    assert proposal["requires_pr"] is True
    assert "normal PR workflow" in proposal["body"]


def _inject_legacy_intent(
    store: SqliteBuilderOpsStore,
    *,
    intent_id: str,
    target_surface: str,
) -> dict[str, object]:
    """Persist an intent bypassing creation validation.

    Simulates records persisted before issue #4171 added creation-time
    target-surface validation (e.g. `prom_20260727085216_b24bc805` with
    `target_authority_surface=github_issue_set`).
    """
    record = normalize_record({
        "object_type": "PromotionIntent",
        "id": intent_id,
        "summary": "Legacy intent persisted before creation validation",
        "target_authority_surface": "github_issue",
        "target_action": "create",
        "target_ref": "pending",
        "target_authority_class": "operational",
        "intended_output": "Legacy record with an unsupported target surface.",
        "source_refs": _source_refs(),
        "created_by": _actor(),
    })
    record["target_authority_surface"] = target_surface
    with store._connect() as conn:
        store._insert_record_payload(conn, record)
        conn.commit()
    return record


def test_disallowed_target_rejected(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    intent = _inject_legacy_intent(
        store,
        intent_id="prom_bad_target",
        target_surface="product_runtime_truth",
    )

    with pytest.raises(BuilderOpsPromotionError, match="unsupported promotion target"):
        gateway.render_proposal(intent["id"])


def test_creation_and_transition_share_target_registry(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    """Store creation and gateway transition validate against one registry."""
    # The gateway's registry is literally the canonical models registry.
    assert TARGET_ALIASES is PROMOTION_TARGET_ALIASES
    assert set(TARGET_SPECS) == set(PROMOTION_TARGET_SURFACES)
    assert set(PROMOTION_TARGET_ALIASES.values()) == set(PROMOTION_TARGET_SURFACES)
    for canonical in PROMOTION_TARGET_SURFACES:
        assert TARGET_SPECS[canonical].canonical == canonical

    # Every supported alias is accepted at creation and canonicalized
    # identically by the gateway.
    for index, (alias, canonical) in enumerate(sorted(PROMOTION_TARGET_ALIASES.items())):
        intent = _create_intent(
            store,
            intent_id=f"prom_alias_{index:03d}",
            target_surface=alias,
        )
        assert intent["target_authority_surface"] == alias
        proposal = gateway.render_proposal(intent["id"])
        assert proposal["target_authority_surface"] == canonical
        assert canonicalize_promotion_target_surface(alias) == canonical

    # An unsupported surface fails at creation with the same canonical error
    # the gateway raises at transition time.
    with pytest.raises(BuilderOpsValidationError) as creation_error:
        _create_intent(
            store,
            intent_id="prom_registry_bad",
            target_surface="github_issue_set",
        )

    legacy = _inject_legacy_intent(
        store,
        intent_id="prom_registry_legacy",
        target_surface="github_issue_set",
    )
    lease = store.acquire_lease(legacy["id"], actor=_actor())
    with pytest.raises(BuilderOpsPromotionError) as transition_error:
        gateway.transition_intent(
            legacy["id"],
            decision="accepted",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="transition:registry-legacy-accept",
            rationale="Unsupported targets must not be accepted.",
        )
    assert str(creation_error.value) == str(transition_error.value)
    assert "unsupported promotion target_authority_surface: github_issue_set" in str(
        creation_error.value
    )


def test_unsupported_legacy_intent_can_be_discarded_without_effect(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    intent = _inject_legacy_intent(
        store,
        intent_id="prom_legacy_stuck_001",
        target_surface="github_issue_set",
    )
    lease = store.acquire_lease(intent["id"], actor=_actor())

    # No promotion effect is reachable for the unsupported target.
    with pytest.raises(BuilderOpsPromotionError, match="unsupported promotion target"):
        gateway.transition_intent(
            intent["id"],
            decision="accepted",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="transition:legacy-accept",
            rationale="Must not accept an unsupported target.",
        )
    with pytest.raises(BuilderOpsPromotionError, match="unsupported promotion target"):
        gateway.dry_run_promotion(
            intent["id"],
            actor=_actor(),
            idempotency_key="dry-run:legacy",
        )

    # The terminal recovery path works and carries a durable receipt.
    discarded = gateway.transition_intent(
        intent["id"],
        decision="discarded",
        actor=_actor(),
        lease_id=lease["lease_id"],
        idempotency_key="transition:legacy-discard",
        rationale="Terminal recovery: target surface is outside the registry.",
    )
    record = discarded["record"]
    receipt = discarded["receipt"]
    assert record["lifecycle_state"] == "discarded"
    assert record["promotion_status"] == "discarded"
    assert record["target_authority_surface"] == "github_issue_set"
    assert receipt["object_type"] == "BuilderOpsReceipt"
    assert receipt["promotion_decision"] == "discarded"
    assert receipt["promotion_proposal"]["proposal_kind"] == (
        "unsupported_target_terminal_recovery"
    )
    assert receipt["promotion_proposal"]["would_mutate_authority"] is False
    assert store.get_record(receipt["id"]) == receipt
    assert store.get_record(intent["id"])["lifecycle_state"] == "discarded"

    # Recovery is terminal only: the record never becomes promotable.
    with pytest.raises(BuilderOpsPromotionError, match="already terminal"):
        gateway.transition_intent(
            intent["id"],
            decision="accepted",
            actor=_actor(),
            lease_id=lease["lease_id"],
            idempotency_key="transition:legacy-accept-after-discard",
            rationale="Terminal records stay terminal.",
        )
