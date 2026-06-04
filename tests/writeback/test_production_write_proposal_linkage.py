"""Production write-proposal bundle linkage tests (#1564).

Bundle evidence may back a governed write proposal but must never become write
authority: WriteGuard runs independently and remains authoritative, and the
propose / stage / apply / log states stay distinct.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExpiryPosture,
)
from app.write_guard import WriteGuard, WritesBlockedError
from app.writeback.production_proposal import (
    apply_proposal,
    log_proposal,
    propose_write_from_bundle,
    stage_proposal,
)


def _propose_scoped_bundle() -> ContextBundle:
    return ContextBundle(
        id="cb-prop-1",
        created_at=datetime.now(tz=timezone.utc),
        trigger=BundleTrigger(type="action"),
        intended_use=["answer", "propose"],
        scope=BundleScope(),
        included=[],
        excluded=[],
        authority=AuthorityFlags(may_answer=True, may_propose=True, may_write=False),
        expiry=ExpiryPosture(),
    )


def test_proposal_carries_bundle_reference():
    bundle = _propose_scoped_bundle()
    rec = propose_write_from_bundle(
        bundle, affected_artifacts=["vault/note.md"], proposal_basis="bundle evidence"
    )
    # The stable bundle reference is carried through the proposal.
    assert rec.bundle_id == bundle.id
    assert rec.proposal.bundle_id == bundle.id
    assert rec.proposal.may_propose is True
    assert rec.proposal.may_write is False


def test_linkage_does_not_bypass_write_guard():
    bundle = _propose_scoped_bundle()
    rec = propose_write_from_bundle(
        bundle, affected_artifacts=["vault/note.md"], proposal_basis="bundle evidence"
    )
    rec = stage_proposal(rec)

    # A guard in a write-blocked state must block apply — bundle linkage cannot
    # bypass the governed write boundary.
    blocked_guard = WriteGuard(snapshot_fn=lambda: {"state": "safe_mode", "reason": "degraded"})
    with pytest.raises(WritesBlockedError):
        apply_proposal(rec, write_guard=blocked_guard)

    # apply was refused: state did not advance past staged.
    assert rec.state == "staged"
    assert rec.proposal.may_write is False


def test_propose_stage_apply_log_distinct():
    bundle = _propose_scoped_bundle()
    rec = propose_write_from_bundle(
        bundle, affected_artifacts=["vault/note.md"], proposal_basis="bundle evidence"
    )
    assert rec.state == "proposed"

    rec = stage_proposal(rec)
    assert rec.state == "staged"

    healthy_guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy"})
    rec = apply_proposal(rec, write_guard=healthy_guard)
    assert rec.state == "applied"

    rec = log_proposal(rec)
    assert rec.state == "logged"

    # All four lifecycle states are distinct and recorded in order.
    assert rec.log == ["proposed", "staged", "applied", "logged"]
    assert len(set(rec.log)) == 4
