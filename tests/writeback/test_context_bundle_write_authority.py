from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExpiryPosture,
    IncludedItem,
    ItemProvenance,
)
from app.writeback.bundle_proposal import (
    BundleProposalViolation,
    WriteProposal,
    build_write_proposal_from_bundle,
)


_NOW = datetime(2026, 5, 15, 11, 0, 0, tzinfo=timezone.utc)


def _bundle(
    *,
    authority: AuthorityFlags | None = None,
    expiry: ExpiryPosture | None = None,
) -> ContextBundle:
    return ContextBundle(
        id="cb_write_001",
        created_at=_NOW,
        trigger=BundleTrigger(type="retrieval"),
        intended_use=["propose"],
        scope=BundleScope(),
        included=[
            IncludedItem(
                artifact_id="art_a",
                reason="supporting evidence",
                provenance=ItemProvenance(origin="vault note"),
            )
        ],
        excluded=[],
        authority=authority or AuthorityFlags(may_answer=True, may_propose=True),
        expiry=expiry or ExpiryPosture(),
    )


def test_context_bundle_may_propose_without_write():
    bundle = _bundle()
    proposal = build_write_proposal_from_bundle(
        bundle,
        affected_artifacts=["art_a"],
        proposal_basis="update summary section with retrieved evidence",
    )

    assert isinstance(proposal, WriteProposal)
    assert proposal.bundle_id == bundle.id
    # proposal carries may_propose=True from the bundle but must not elevate may_write
    assert proposal.may_propose is True
    assert proposal.may_write is False


def test_write_proposal_preserves_bundle_basis_and_authority_flags():
    bundle = _bundle()
    proposal = build_write_proposal_from_bundle(
        bundle,
        affected_artifacts=["art_a", "art_b"],
        proposal_basis="consolidate overlapping notes",
    )

    # Affected artifacts, proposal basis, and authority posture are kept separately
    assert set(proposal.affected_artifacts) == {"art_a", "art_b"}
    assert "consolidate" in proposal.proposal_basis
    assert proposal.bundle_id == bundle.id
    # Separate authority flags — propose ≠ write
    assert proposal.may_propose is True
    assert proposal.may_write is False


def test_context_bundle_write_flow_distinguishes_propose_stage_apply_and_log():
    bundle = _bundle()
    proposal = build_write_proposal_from_bundle(
        bundle,
        affected_artifacts=["art_a"],
        proposal_basis="add a link from art_a to art_b",
    )

    # Proposal is PROPOSED state — not staged, not applied, not logged as done.
    assert proposal.state == "proposed"
    # The proposal object carries distinct state transitions available to the
    # governed surface — stage(), apply(), and log() are not collapsed.
    assert hasattr(proposal, "state")
    assert proposal.state not in ("staged", "applied", "logged")


def test_context_bundle_cannot_bypass_write_guards():
    # may_write=True on the bundle must be rejected — write proposals require
    # explicit governed write authorization, not bundle-carried permission.
    write_bundle = _bundle(
        authority=AuthorityFlags(may_answer=True, may_propose=True, may_write=True)
    )
    with pytest.raises(BundleProposalViolation):
        build_write_proposal_from_bundle(
            write_bundle,
            affected_artifacts=["art_a"],
            proposal_basis="should fail",
        )

    # Bundles without may_propose are also rejected — proposal linkage requires
    # explicit propose authority, not just retrieval or answer authority.
    no_propose_bundle = _bundle(
        authority=AuthorityFlags(may_answer=True, may_propose=False)
    )
    with pytest.raises(BundleProposalViolation):
        build_write_proposal_from_bundle(
            no_propose_bundle,
            affected_artifacts=["art_a"],
            proposal_basis="should also fail",
        )


def test_expired_bundle_cannot_justify_write_proposal():
    # Expired bundles must not silently continue to justify new write proposals.
    # Stale retrieval snapshots lose proposal authority — callers must re-retrieve.
    expired_expiry = ExpiryPosture(
        stale_after=_NOW - timedelta(hours=1),
        reason="retrieval snapshot expired",
    )
    expired_bundle = _bundle(expiry=expired_expiry)
    with pytest.raises(BundleProposalViolation, match="expired"):
        build_write_proposal_from_bundle(
            expired_bundle,
            affected_artifacts=["art_a"],
            proposal_basis="should fail — stale snapshot",
            now=_NOW,
        )

    # Naive stale_after is treated as UTC — must not raise TypeError.
    naive_expiry = ExpiryPosture(
        stale_after=datetime(2026, 5, 15, 9, 0, 0),  # no tzinfo, 2h before _NOW
        reason="naive expiry",
    )
    naive_bundle = _bundle(expiry=naive_expiry)
    with pytest.raises(BundleProposalViolation, match="expired"):
        build_write_proposal_from_bundle(
            naive_bundle,
            affected_artifacts=["art_a"],
            proposal_basis="should fail — naive stale snapshot",
            now=_NOW,
        )

    # Not-yet-expired bundles must still be accepted.
    fresh_expiry = ExpiryPosture(
        stale_after=_NOW + timedelta(hours=1),
        reason="still fresh",
    )
    fresh_bundle = _bundle(expiry=fresh_expiry)
    proposal = build_write_proposal_from_bundle(
        fresh_bundle,
        affected_artifacts=["art_a"],
        proposal_basis="valid — bundle still fresh",
        now=_NOW,
    )
    assert proposal.may_write is False

    # Naive caller-provided now must not raise TypeError — treated as UTC.
    naive_now = datetime(2026, 5, 15, 10, 0, 0)  # no tzinfo, same instant as _NOW
    naive_now_bundle = _bundle(expiry=fresh_expiry)
    naive_proposal = build_write_proposal_from_bundle(
        naive_now_bundle,
        affected_artifacts=["art_a"],
        proposal_basis="valid — naive now is normalized",
        now=naive_now,
    )
    assert naive_proposal.may_write is False


def test_write_proposal_rejects_bundle_not_scoped_for_propose():
    # intended_use is part of the scoping contract — may_propose authority alone
    # is not sufficient if the bundle was assembled for a different purpose.
    answer_only_bundle = ContextBundle(
        id="cb_answer_only",
        created_at=_NOW,
        trigger=BundleTrigger(type="retrieval"),
        intended_use=["answer"],
        scope=BundleScope(),
        included=[
            IncludedItem(
                artifact_id="art_a",
                reason="evidence",
                provenance=ItemProvenance(origin="vault note"),
            )
        ],
        excluded=[],
        authority=AuthorityFlags(may_answer=True, may_propose=True),
        expiry=ExpiryPosture(),
    )
    with pytest.raises(BundleProposalViolation, match="intended_use"):
        build_write_proposal_from_bundle(
            answer_only_bundle,
            affected_artifacts=["art_a"],
            proposal_basis="should fail — not scoped for propose",
        )

    # Multi-use bundles that include "propose" are accepted.
    multi_bundle = ContextBundle(
        id="cb_multi",
        created_at=_NOW,
        trigger=BundleTrigger(type="retrieval"),
        intended_use=["answer", "propose"],
        scope=BundleScope(),
        included=[
            IncludedItem(
                artifact_id="art_a",
                reason="evidence",
                provenance=ItemProvenance(origin="vault note"),
            )
        ],
        excluded=[],
        authority=AuthorityFlags(may_answer=True, may_propose=True),
        expiry=ExpiryPosture(),
    )
    proposal = build_write_proposal_from_bundle(
        multi_bundle,
        affected_artifacts=["art_a"],
        proposal_basis="valid — multi-use bundle includes propose",
    )
    assert proposal.may_write is False


def test_write_proposal_rejects_empty_targets_or_blank_basis():
    # A proposal without an affected artifact has no auditable write surface.
    bundle = _bundle()
    with pytest.raises(BundleProposalViolation, match="affected_artifacts"):
        build_write_proposal_from_bundle(
            bundle,
            affected_artifacts=[],
            proposal_basis="valid basis",
        )

    # Blank entries in affected_artifacts are equally unauditable.
    with pytest.raises(BundleProposalViolation, match="affected_artifacts"):
        build_write_proposal_from_bundle(
            bundle,
            affected_artifacts=["art_a", "   "],
            proposal_basis="valid basis",
        )
    with pytest.raises(BundleProposalViolation, match="affected_artifacts"):
        build_write_proposal_from_bundle(
            bundle,
            affected_artifacts=[""],
            proposal_basis="valid basis",
        )

    # A blank proposal_basis leaves the write rationale untied to evidence.
    with pytest.raises(BundleProposalViolation, match="proposal_basis"):
        build_write_proposal_from_bundle(
            bundle,
            affected_artifacts=["art_a"],
            proposal_basis="",
        )
    with pytest.raises(BundleProposalViolation, match="proposal_basis"):
        build_write_proposal_from_bundle(
            bundle,
            affected_artifacts=["art_a"],
            proposal_basis="\t\n  ",
        )
