"""Read-only projection/query over ContextBundle receipts (#1565).

``app/receipts/bundle_receipts.py`` produces ``BundleReceipt`` trace objects for
bundle creation, consumption, and stale/expired reuse, but there was no surface
to query them. This module adds a typed, read-only projection that exposes a
bundle's provenance, exclusions, and authority posture across its lifecycle
events so they are auditable.

Following the receipt/trace/audit distinction in
``docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`` and the promotion
receipt query-model decision (#1489): consumers depend on a stable read/query
contract, not on a storage shape. This is a non-durable trace view — it never
materialises a durable knowledge store, never promotes bundle contents into
memory/knowledge, introduces no new event family, and performs no DB access.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from app.context_bundles.schema import ExcludedItem, IncludedItem
from app.receipts.bundle_receipts import BundleEventType, BundleReceipt


class BundleReceiptProjectionRow(BaseModel):
    """A read-only projected view of one bundle receipt.

    ``trace_only`` and ``promoted_to_memory`` make the posture explicit: this is
    a trace view, not durable knowledge, and it never promotes bundle contents.
    """

    bundle_id: str
    event: BundleEventType
    recorded_at: datetime
    consumer: Optional[str] = None
    stale_reason: Optional[str] = None
    included_items: list[IncludedItem] = Field(default_factory=list)
    excluded_items: list[ExcludedItem] = Field(default_factory=list)
    may_answer: bool = False
    may_orient: bool = False
    may_resurface: bool = False
    may_propose: bool = False
    may_write: bool = False
    trace_only: bool = True
    promoted_to_memory: bool = False


def project_receipt(receipt: BundleReceipt) -> BundleReceiptProjectionRow:
    """Project a single ``BundleReceipt`` into a read-only row.

    Provenance (via included items), exclusions, and authority posture are
    preserved verbatim; nothing is upgraded or promoted.
    """
    return BundleReceiptProjectionRow(
        bundle_id=receipt.bundle_id,
        event=receipt.event,
        recorded_at=receipt.recorded_at,
        consumer=receipt.consumer,
        stale_reason=receipt.stale_reason,
        included_items=[item.model_copy(deep=True) for item in receipt.included_items],
        excluded_items=[item.model_copy(deep=True) for item in receipt.excluded_items],
        may_answer=receipt.may_answer,
        may_orient=receipt.may_orient,
        may_resurface=receipt.may_resurface,
        may_propose=receipt.may_propose,
        may_write=receipt.may_write,
    )


class BundleReceiptProjection:
    """Read-only query surface over recorded bundle receipts.

    Receipts are ingested via :meth:`record` and queried via :meth:`for_bundle`
    and :meth:`events_for`. The projection holds only in-memory trace receipts;
    it is not a durable receipt store and exposes no write/promote capability.
    """

    def __init__(self, receipts: Iterable[BundleReceipt] | None = None) -> None:
        self._receipts: list[BundleReceipt] = list(receipts or [])

    def record(self, receipt: BundleReceipt) -> None:
        """Ingest a trace receipt into the read-only projection."""
        self._receipts.append(receipt)

    def for_bundle(self, bundle_id: str) -> list[BundleReceiptProjectionRow]:
        """Return projected rows for one bundle, ordered by recorded time."""
        rows = [
            project_receipt(receipt)
            for receipt in self._receipts
            if receipt.bundle_id == bundle_id
        ]
        rows.sort(key=lambda row: row.recorded_at)
        return rows

    def events_for(self, bundle_id: str) -> list[BundleEventType]:
        """Return the ordered lifecycle event kinds recorded for one bundle."""
        return [row.event for row in self.for_bundle(bundle_id)]


__all__ = [
    "BundleReceiptProjectionRow",
    "BundleReceiptProjection",
    "project_receipt",
]
