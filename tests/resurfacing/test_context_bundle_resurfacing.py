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
from app.resurfacing.bundle_consumer import (
    BundleAuthorityViolation,
    ResurfacingBundleFrame,
    WhyNowSignal,
    build_resurfacing_bundle_frame,
)


_NOW = datetime(2026, 5, 15, 10, 0, 0, tzinfo=timezone.utc)


def _bundle(
    *,
    included: list[IncludedItem] | None = None,
    excluded: list[ExcludedItem] | None = None,
    authority: AuthorityFlags | None = None,
    expiry: ExpiryPosture | None = None,
) -> ContextBundle:
    return ContextBundle(
        id="cb_resurface_001",
        created_at=_NOW,
        trigger=BundleTrigger(type="resurfacing"),
        intended_use=["resurface"],
        scope=BundleScope(),
        included=included or [],
        excluded=excluded or [],
        authority=authority or AuthorityFlags(may_answer=True, may_resurface=True),
        expiry=expiry or ExpiryPosture(),
    )


def _item(artifact_id: str, reason: str, source_role: str | None = None) -> IncludedItem:
    return IncludedItem(
        artifact_id=artifact_id,
        reason=reason,
        source_role=source_role,
        provenance=ItemProvenance(origin="vault note"),
    )


def test_resurfacing_bundle_surfaces_stale_expiry_state():
    # Stale bundles must be marked stale — callers must not reuse old evidence
    # as if it were current. Naive timestamps are assumed UTC.
    stale_expiry = ExpiryPosture(
        stale_after=_NOW - timedelta(hours=2),
        reason="resurfacing snapshot expired",
    )
    bundle = _bundle(included=[_item("art_stale", "old note")], expiry=stale_expiry)
    frame = build_resurfacing_bundle_frame(bundle, why_now="stale context detected", now=_NOW)
    assert frame.stale is True
    assert frame.stale_reason == "resurfacing snapshot expired"

    # Naive stale_after is treated as UTC — must not raise TypeError.
    naive_expiry = ExpiryPosture(
        stale_after=datetime(2026, 5, 15, 9, 0, 0),  # no tzinfo, 1h before _NOW
        reason="naive expiry",
    )
    naive_bundle = _bundle(included=[_item("art_naive", "old note")], expiry=naive_expiry)
    naive_frame = build_resurfacing_bundle_frame(
        naive_bundle, why_now="naive expiry test", now=_NOW
    )
    assert naive_frame.stale is True

    # Not-yet-stale bundles must not be flagged stale.
    fresh_expiry = ExpiryPosture(
        stale_after=_NOW + timedelta(hours=1),
        reason="fresh",
    )
    fresh_bundle = _bundle(included=[_item("art_fresh", "recent note")], expiry=fresh_expiry)
    fresh_frame = build_resurfacing_bundle_frame(
        fresh_bundle, why_now="still current", now=_NOW
    )
    assert fresh_frame.stale is False


def test_resurfacing_records_context_bundle():
    bundle = _bundle(included=[_item("art_a", "recently updated in vault")])

    frame = build_resurfacing_bundle_frame(bundle, why_now="dependency gap detected", now=_NOW)

    assert isinstance(frame, ResurfacingBundleFrame)
    assert frame.bundle_id == bundle.id
    # The frame must derive surfaced items from the bundle, not opaque internals.
    assert any(s.artifact_id == "art_a" for s in frame.surfaced_items)


def test_resurfacing_bundle_includes_why_now_explanation():
    bundle = _bundle(included=[_item("art_b", "related note updated recently")])

    # WhyNowSignal anchors the explanation to a named provenance signal so the
    # "why now" decision is auditable, not just an opaque semantic score.
    signal = WhyNowSignal(
        rationale="three related notes updated in last 24h",
        signal_name="watcher_run_24h",
    )
    frame = build_resurfacing_bundle_frame(bundle, why_now=signal, now=_NOW)

    # "Why now" rationale is explicit and the signal_name anchors it to provenance.
    assert "24h" in frame.why_now
    assert frame.why_now_signal_name == "watcher_run_24h"
    # Provenance of the surfaced items is preserved for auditing.
    item = next(s for s in frame.surfaced_items if s.artifact_id == "art_b")
    assert item.provenance is not None
    assert item.provenance.origin == "vault note"


def test_resurfacing_bundle_does_not_collapse_relatedness_into_priority_or_authority():
    bundle = _bundle(
        included=[
            _item("art_c", "semantically related to active project"),
            _item("art_d", "high-priority unresolved thread", source_role="priority_signal"),
        ]
    )

    frame = build_resurfacing_bundle_frame(bundle, why_now="semantic shift detected", now=_NOW)

    # relatedness, priority, and authority are distinct fields on the frame —
    # the consumer cannot conflate them.
    assert hasattr(frame, "relatedness_signals")
    assert hasattr(frame, "priority_signals")
    # Authority remains a suggestion posture — no write flag escalated.
    assert frame.suggestion_only is True
    assert frame.may_write is False
    # Items classified as priority_signal appear in priority_signals, not relatedness.
    priority_ids = {s.artifact_id for s in frame.priority_signals}
    relatedness_ids = {s.artifact_id for s in frame.relatedness_signals}
    assert "art_d" in priority_ids
    assert "art_c" in relatedness_ids
    assert priority_ids.isdisjoint(relatedness_ids)


def test_resurfacing_bundle_remains_suggestion_only():
    # Normal bundle: suggestion_only=True, no write authority.
    bundle = _bundle(included=[_item("art_e", "relevant now")])
    frame = build_resurfacing_bundle_frame(bundle, why_now="context shift", now=_NOW)
    assert frame.suggestion_only is True
    assert frame.may_write is False

    # Bundles with may_write=True are rejected — resurfacing must not
    # launder write authority from a bundle.
    write_bundle = _bundle(
        included=[_item("art_f", "relevant now")],
        authority=AuthorityFlags(may_resurface=True, may_write=True),
    )
    with pytest.raises(BundleAuthorityViolation):
        build_resurfacing_bundle_frame(write_bundle, why_now="context shift", now=_NOW)

    # Bundles without may_resurface are rejected — resurfacing must not
    # silently consume bundles not authorized for resurfacing.
    no_resurface_bundle = _bundle(
        included=[_item("art_g", "relevant now")],
        authority=AuthorityFlags(may_answer=True, may_resurface=False),
    )
    with pytest.raises(BundleAuthorityViolation):
        build_resurfacing_bundle_frame(no_resurface_bundle, why_now="context shift", now=_NOW)
