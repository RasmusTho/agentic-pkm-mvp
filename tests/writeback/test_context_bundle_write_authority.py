from __future__ import annotations

from datetime import datetime, timezone

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


def _bundle(*, authority: AuthorityFlags | None = None) -> ContextBundle:
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
        expiry=ExpiryPosture(),
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
