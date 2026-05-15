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
from app.receipts.bundle_receipts import (
    BundleReceipt,
    record_consumption_receipt,
    record_creation_receipt,
    record_stale_receipt,
)


_NOW = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


def _bundle() -> ContextBundle:
    return ContextBundle(
        id="cb_receipt_001",
        created_at=_NOW,
        trigger=BundleTrigger(type="retrieval"),
        intended_use=["answer", "orient"],
        scope=BundleScope(),
        included=[
            IncludedItem(
                artifact_id="art_x",
                reason="primary evidence",
                provenance=ItemProvenance(origin="vault note"),
            )
        ],
        excluded=[
            ExcludedItem(
                artifact_id="art_y",
                reason="trust state below threshold",
                provenance=ItemProvenance(origin="vault note"),
            )
        ],
        authority=AuthorityFlags(may_answer=True, may_orient=True),
        expiry=ExpiryPosture(),
    )


def test_context_bundle_receipt_records_sources():
    bundle = _bundle()

    receipt = record_creation_receipt(bundle, recorded_at=_NOW)

    assert isinstance(receipt, BundleReceipt)
    assert receipt.bundle_id == bundle.id
    assert receipt.event == "created"
    # Receipt records which items were included so the creation is inspectable.
    assert any(i.artifact_id == "art_x" for i in receipt.included_items)

    # Downstream use path — orientation consumption — also produces a receipt.
    consume_receipt = record_consumption_receipt(bundle, consumer="orientation", recorded_at=_NOW)
    assert consume_receipt.bundle_id == bundle.id
    assert consume_receipt.event == "consumed"
    assert consume_receipt.consumer == "orientation"


def test_context_bundle_receipt_preserves_exclusions_and_authority():
    bundle = _bundle()

    receipt = record_creation_receipt(bundle, recorded_at=_NOW)

    # Excluded items and their reasons are in the receipt — not dropped silently.
    assert any(ex.artifact_id == "art_y" for ex in receipt.excluded_items)
    assert receipt.excluded_items[0].reason == "trust state below threshold"
    # Authority posture is recorded on the receipt for later audit.
    assert receipt.may_answer is True
    assert receipt.may_write is False
    # Provenance of included items survives into the receipt.
    item = next(i for i in receipt.included_items if i.artifact_id == "art_x")
    assert item.provenance is not None
    assert item.provenance.origin == "vault note"


def test_context_bundle_receipts_distinguish_creation_consumption_and_expiry():
    bundle = _bundle()

    creation = record_creation_receipt(bundle, recorded_at=_NOW)
    consumption = record_consumption_receipt(bundle, consumer="resurfacing", recorded_at=_NOW)
    stale = record_stale_receipt(bundle, stale_reason="snapshot expired", recorded_at=_NOW)

    # Each event type is distinct — not collapsed into a single opaque log entry.
    assert creation.event == "created"
    assert consumption.event == "consumed"
    assert stale.event == "stale_or_expired"
    assert stale.stale_reason == "snapshot expired"

    events = {creation.event, consumption.event, stale.event}
    assert len(events) == 3


def test_context_bundle_receipt_does_not_promote_to_memory():
    bundle = _bundle()

    receipt = record_creation_receipt(bundle, recorded_at=_NOW)

    # Receipt must not expose a path to memory, knowledge, or writeback promotion.
    assert not hasattr(receipt, "promotes_to_memory")
    assert not hasattr(receipt, "knowledge_entry")
    assert not hasattr(receipt, "write_result")
    # Authority flags on the receipt must still not carry may_write=True.
    assert receipt.may_write is False


def test_receipt_items_are_isolated_from_bundle_mutations():
    # Receipt must snapshot included/excluded items at record time — mutations
    # to the bundle after recording must not affect the already-recorded receipt.
    bundle = _bundle()
    receipt = record_creation_receipt(bundle, recorded_at=_NOW)

    original_reason = receipt.included_items[0].reason
    # Mutate the bundle's included item in-place.
    bundle.included[0].reason = "mutated after recording"

    # Receipt item is unaffected — deep copy, not a shared reference.
    assert receipt.included_items[0].reason == original_reason
