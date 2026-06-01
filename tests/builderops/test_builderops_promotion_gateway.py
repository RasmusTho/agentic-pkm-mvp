from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.promotion_gateway import (
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
) -> None:
    intent = _create_intent(store)

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


def test_disallowed_target_rejected(
    store: SqliteBuilderOpsStore,
    gateway: BuilderOpsPromotionGateway,
) -> None:
    intent = _create_intent(
        store,
        intent_id="prom_bad_target",
        target_surface="product_runtime_truth",
        target_ref="runtime",
    )

    with pytest.raises(BuilderOpsPromotionError, match="unsupported promotion target"):
        gateway.render_proposal(intent["id"])
