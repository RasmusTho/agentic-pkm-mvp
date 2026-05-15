"""Record inspectable receipts for ContextBundle lifecycle events (CONTEXT-BUNDLES-06).

Bundle receipts explain why a bundle was created and how it was used downstream.
They preserve included items, exclusions, authority posture, and provenance for
later audit without promoting bundle contents into memory or knowledge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.context_bundles.schema import ContextBundle, ExcludedItem, IncludedItem


BundleEventType = Literal["created", "consumed", "stale_or_expired"]


class BundleReceiptItem(BaseModel):
    artifact_id: str
    reason: str
    provenance: Optional[object] = None


class BundleReceiptExcludedItem(BaseModel):
    artifact_id: str
    reason: str
    provenance: Optional[object] = None


class BundleReceipt(BaseModel):
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


def _authority_kwargs(bundle: ContextBundle) -> dict[str, bool]:
    a = bundle.authority
    return dict(
        may_answer=a.may_answer,
        may_orient=a.may_orient,
        may_resurface=a.may_resurface,
        may_propose=a.may_propose,
        may_write=a.may_write,
    )


def record_creation_receipt(
    bundle: ContextBundle,
    *,
    recorded_at: datetime | None = None,
) -> BundleReceipt:
    """Record that a bundle was created, preserving its full inclusion/exclusion state."""
    return BundleReceipt(
        bundle_id=bundle.id,
        event="created",
        recorded_at=recorded_at or datetime.now(tz=timezone.utc),
        included_items=list(bundle.included),
        excluded_items=list(bundle.excluded),
        **_authority_kwargs(bundle),
    )


def record_consumption_receipt(
    bundle: ContextBundle,
    *,
    consumer: str,
    recorded_at: datetime | None = None,
) -> BundleReceipt:
    """Record that a bundle was consumed by a downstream surface (orientation, resurfacing, etc.)."""
    return BundleReceipt(
        bundle_id=bundle.id,
        event="consumed",
        recorded_at=recorded_at or datetime.now(tz=timezone.utc),
        consumer=consumer,
        included_items=list(bundle.included),
        excluded_items=list(bundle.excluded),
        **_authority_kwargs(bundle),
    )


def record_stale_receipt(
    bundle: ContextBundle,
    *,
    stale_reason: str,
    recorded_at: datetime | None = None,
) -> BundleReceipt:
    """Record that a bundle was marked stale or expired for audit trail."""
    return BundleReceipt(
        bundle_id=bundle.id,
        event="stale_or_expired",
        recorded_at=recorded_at or datetime.now(tz=timezone.utc),
        stale_reason=stale_reason,
        included_items=list(bundle.included),
        excluded_items=list(bundle.excluded),
        **_authority_kwargs(bundle),
    )


__all__ = [
    "BundleReceipt",
    "record_creation_receipt",
    "record_consumption_receipt",
    "record_stale_receipt",
]
