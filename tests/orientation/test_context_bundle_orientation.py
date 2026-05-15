from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

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
from app.orientation.bundle_consumer import (
    BundleAuthorityViolation,
    OrientationBundleFrame,
    build_orientation_frame_from_bundle,
)


_NOW = datetime(2026, 5, 15, 9, 0, 0, tzinfo=timezone.utc)


def _bundle(
    *,
    included: list[IncludedItem] | None = None,
    excluded: list[ExcludedItem] | None = None,
    authority: AuthorityFlags | None = None,
    expiry: ExpiryPosture | None = None,
) -> ContextBundle:
    return ContextBundle(
        id="cb_orient_001",
        created_at=_NOW,
        trigger=BundleTrigger(type="orientation"),
        intended_use=["orient"],
        scope=BundleScope(),
        included=included or [],
        excluded=excluded or [],
        authority=authority
        or AuthorityFlags(may_answer=True, may_orient=True),
        expiry=expiry or ExpiryPosture(),
    )


def _fact_item() -> IncludedItem:
    return IncludedItem(
        artifact_id="art_fact",
        reason="direct evidence",
        trust_state="reviewed",
        review_state="confirmed",
        provenance=ItemProvenance(origin="vault note"),
    )


def _inferred_item() -> IncludedItem:
    return IncludedItem(
        artifact_id="art_infer",
        reason="model inference from related notes",
        trust_state="unreviewed",
        provenance=ItemProvenance(origin="agent inference", transformed_by="orientation"),
    )


def _candidate_item() -> IncludedItem:
    return IncludedItem(
        artifact_id="art_cand",
        reason="candidate next action",
        source_role="candidate_action",
        provenance=ItemProvenance(origin="agent proposal"),
    )


def test_orientation_uses_context_bundle():
    bundle = _bundle(included=[_fact_item()])

    frame = build_orientation_frame_from_bundle(bundle, now=_NOW)

    assert isinstance(frame, OrientationBundleFrame)
    assert frame.bundle_id == bundle.id
    # The frame must derive its facts from the bundle, not opaque prompt state.
    assert any(seg.artifact_id == "art_fact" for seg in frame.facts)


def test_orientation_labels_fact_inference_candidate_and_stale_context():
    expiry = ExpiryPosture(
        stale_after=_NOW - timedelta(hours=1),
        reason="snapshot expired",
    )
    bundle = _bundle(
        included=[_fact_item(), _inferred_item(), _candidate_item()],
        expiry=expiry,
    )

    frame = build_orientation_frame_from_bundle(bundle, now=_NOW)

    fact_ids = {s.artifact_id for s in frame.facts}
    inference_ids = {s.artifact_id for s in frame.inferences}
    candidate_ids = {s.artifact_id for s in frame.candidate_actions}

    assert "art_fact" in fact_ids
    assert "art_infer" in inference_ids
    assert "art_cand" in candidate_ids
    # The four buckets are distinct — no leakage between them.
    assert fact_ids.isdisjoint(inference_ids)
    assert fact_ids.isdisjoint(candidate_ids)
    assert inference_ids.isdisjoint(candidate_ids)
    # Stale context is surfaced explicitly, not silently treated as current.
    assert frame.stale is True
    assert frame.stale_reason == "snapshot expired"


def test_orientation_exposes_bundle_provenance_and_exclusions():
    excluded = ExcludedItem(
        artifact_id="art_excluded",
        reason="trust state below threshold",
        trust_state="unreviewed",
        provenance=ItemProvenance(origin="vault note"),
    )
    bundle = _bundle(included=[_fact_item()], excluded=[excluded])

    frame = build_orientation_frame_from_bundle(bundle, now=_NOW)

    # Per-item provenance survives onto the frame so a human can inspect why
    # the orientation frame was assembled.
    fact = next(s for s in frame.facts if s.artifact_id == "art_fact")
    assert fact.provenance is not None
    assert fact.provenance.origin == "vault note"
    # Exclusions are visible on the frame, not dropped silently.
    assert any(ex.artifact_id == "art_excluded" for ex in frame.exclusions)
    assert frame.exclusions[0].reason == "trust state below threshold"


def test_orientation_stale_check_handles_naive_expiry_timestamp():
    # ExpiryPosture allows naive datetimes (no tzinfo). Comparison with an
    # aware `now` must not raise TypeError — naive timestamps are assumed UTC.
    naive_expiry = ExpiryPosture(
        stale_after=datetime(2026, 5, 15, 8, 0, 0),  # no tzinfo
        reason="naive expiry from JSON without offset",
    )
    bundle = _bundle(included=[_fact_item()], expiry=naive_expiry)
    # _NOW is 09:00 UTC, naive stale_after is treated as 08:00 UTC → stale
    frame = build_orientation_frame_from_bundle(bundle, now=_NOW)
    assert frame.stale is True
    assert "naive" in frame.stale_reason


def test_orientation_bundle_remains_non_write_authoritative():
    # Building with may_write=False is fine and frame must remain read-only.
    bundle = _bundle(included=[_fact_item()])
    frame = build_orientation_frame_from_bundle(bundle, now=_NOW)
    assert frame.read_only is True
    assert frame.may_write is False

    # Bundles arriving with may_write=True are rejected — orientation must not
    # silently launder bundle authority into write authorization.
    write_bundle = _bundle(
        included=[_fact_item()],
        authority=AuthorityFlags(may_answer=True, may_orient=True, may_write=True),
    )
    with pytest.raises(BundleAuthorityViolation):
        build_orientation_frame_from_bundle(write_bundle, now=_NOW)

    # Bundles without may_orient are rejected — orientation must not silently
    # upgrade a bundle not authorized for orientation use (e.g. may_answer only).
    no_orient_bundle = _bundle(
        included=[_fact_item()],
        authority=AuthorityFlags(may_answer=True, may_orient=False),
    )
    with pytest.raises(BundleAuthorityViolation):
        build_orientation_frame_from_bundle(no_orient_bundle, now=_NOW)
