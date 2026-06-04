"""Read-only bundle receipt projection tests (#1565).

The projection is a typed, read-only query/view over the bundle receipts
produced by ``app/receipts/bundle_receipts.py``. It preserves provenance,
exclusions, and authority posture, and never promotes bundle contents into
memory or knowledge. No new event family is introduced.
"""
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
from app.receipts.bundle_receipt_projection import BundleReceiptProjection
from app.receipts.bundle_receipts import (
    record_consumption_receipt,
    record_creation_receipt,
)


def _bundle() -> ContextBundle:
    return ContextBundle(
        id="cb-proj-1",
        created_at=datetime.now(tz=timezone.utc),
        trigger=BundleTrigger(type="retrieval"),
        intended_use=["answer", "orient"],
        scope=BundleScope(),
        included=[
            IncludedItem(
                artifact_id="art-1",
                reason="evidence",
                provenance=ItemProvenance(origin="retrieval"),
            )
        ],
        excluded=[ExcludedItem(artifact_id="art-x", reason="out of scope")],
        authority=AuthorityFlags(may_answer=True, may_orient=True, may_write=False),
        expiry=ExpiryPosture(),
    )


def test_projection_exposes_creation_and_consumption():
    bundle = _bundle()
    proj = BundleReceiptProjection()
    proj.record(record_creation_receipt(bundle))
    proj.record(record_consumption_receipt(bundle, consumer="orientation"))

    rows = proj.for_bundle("cb-proj-1")
    events = [row.event for row in rows]
    assert "created" in events
    assert "consumed" in events

    created = next(row for row in rows if row.event == "created")
    assert created.included_items[0].provenance is not None
    assert created.included_items[0].provenance.origin == "retrieval"

    consumed = next(row for row in rows if row.event == "consumed")
    assert consumed.consumer == "orientation"


def test_projection_preserves_exclusions_and_authority():
    bundle = _bundle()
    proj = BundleReceiptProjection()
    proj.record(record_creation_receipt(bundle))

    row = proj.for_bundle("cb-proj-1")[0]
    assert [e.artifact_id for e in row.excluded_items] == ["art-x"]
    assert row.may_answer is True
    assert row.may_orient is True
    assert row.may_write is False


def test_projection_does_not_promote_to_memory():
    bundle = _bundle()
    proj = BundleReceiptProjection()
    proj.record(record_creation_receipt(bundle))

    rows = proj.for_bundle("cb-proj-1")
    # The projection is an explicit read-only trace view, never durable knowledge.
    assert rows
    assert all(row.trace_only is True for row in rows)
    assert all(row.promoted_to_memory is False for row in rows)
    # It exposes no promotion/write capability.
    assert not hasattr(proj, "promote")
    assert not hasattr(proj, "promote_to_memory")
