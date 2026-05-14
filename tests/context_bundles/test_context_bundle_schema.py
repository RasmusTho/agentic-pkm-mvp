from __future__ import annotations

from datetime import datetime, timezone

from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExcludedItem,
    ExpiryPosture,
    IncludedItem,
    ItemProvenance,
)


def _minimal_bundle(**overrides) -> ContextBundle:
    defaults = dict(
        id="cb_test_001",
        created_at=datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc),
        trigger=BundleTrigger(type="retrieval"),
        intended_use=["answer"],
        scope=BundleScope(),
        authority=AuthorityFlags(),
        expiry=ExpiryPosture(),
    )
    defaults.update(overrides)
    return ContextBundle(**defaults)


def test_minimal_context_bundle_schema():
    bundle = _minimal_bundle()
    assert bundle.id == "cb_test_001"
    assert bundle.created_at is not None
    assert bundle.trigger is not None
    assert bundle.intended_use is not None
    assert bundle.scope is not None
    assert bundle.included is not None
    assert bundle.excluded is not None
    assert bundle.authority is not None
    assert bundle.expiry is not None
    assert bundle.receipts is not None


def test_context_bundle_items_preserve_reason_and_provenance():
    item = IncludedItem(
        artifact_id="art_123",
        reason="direct evidence",
        trust_state="reviewed",
        provenance=ItemProvenance(origin="vault note", transformed_by="retrieval"),
    )
    excluded = ExcludedItem(
        artifact_id="art_999",
        reason="out of scope for active sphere",
        trust_state="unreviewed",
        provenance=ItemProvenance(origin="vault note", transformed_by="retrieval"),
    )
    bundle = _minimal_bundle(included=[item], excluded=[excluded])

    assert bundle.included[0].reason == "direct evidence"
    assert bundle.included[0].trust_state == "reviewed"
    assert bundle.included[0].provenance.origin == "vault note"
    assert bundle.excluded[0].reason == "out of scope for active sphere"
    assert bundle.excluded[0].trust_state == "unreviewed"
    assert bundle.excluded[0].provenance.origin == "vault note"


def test_context_bundle_authority_flags_are_distinct():
    authority = AuthorityFlags(
        may_answer=True,
        may_orient=True,
        may_resurface=True,
        may_propose=True,
        may_write=False,
    )
    bundle = _minimal_bundle(authority=authority)

    flags = bundle.authority
    assert flags.may_answer is True
    assert flags.may_write is False
    assert hasattr(flags, "may_answer")
    assert hasattr(flags, "may_orient")
    assert hasattr(flags, "may_resurface")
    assert hasattr(flags, "may_propose")
    assert hasattr(flags, "may_write")
    # answer and write are independent — can differ
    assert flags.may_answer != flags.may_write


def test_context_bundle_schema_carries_expiry_posture():
    expiry = ExpiryPosture(
        stale_after=datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc),
        reason="selection tied to a transient retrieval snapshot",
    )
    bundle = _minimal_bundle(expiry=expiry)

    assert bundle.expiry.stale_after is not None
    assert bundle.expiry.reason is not None
    assert "snapshot" in bundle.expiry.reason
