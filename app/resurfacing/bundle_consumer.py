"""Consume a ContextBundle from resurfacing (CONTEXT-BUNDLES-04).

Resurfacing reads a bundle to support "why now" suggestions. The frame keeps
relatedness signals, priority signals, and why-now provenance distinct so the
decision is auditable rather than opaque. It must not launder bundle authority
into write permission — resurfacing is suggestion-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.context_bundles.schema import ContextBundle, IncludedItem, ItemProvenance


class BundleAuthorityViolation(Exception):
    """Raised when a bundle carries prohibited authority for resurfacing."""


class SurfacedItem(BaseModel):
    artifact_id: str
    reason: str
    provenance: Optional[ItemProvenance] = None
    source_role: Optional[str] = None
    trust_state: Optional[str] = None


class ResurfacingBundleFrame(BaseModel):
    bundle_id: str
    why_now: str
    surfaced_items: list[SurfacedItem] = Field(default_factory=list)
    relatedness_signals: list[SurfacedItem] = Field(default_factory=list)
    priority_signals: list[SurfacedItem] = Field(default_factory=list)
    stale: bool = False
    stale_reason: Optional[str] = None
    suggestion_only: bool = True
    may_write: bool = False


_PRIORITY_ROLES = {"priority_signal", "priority", "urgent", "unresolved"}


def _surfaced(item: IncludedItem) -> SurfacedItem:
    return SurfacedItem(
        artifact_id=item.artifact_id,
        reason=item.reason,
        provenance=item.provenance,
        source_role=item.source_role,
        trust_state=item.trust_state,
    )


def _is_priority(item: IncludedItem) -> bool:
    if item.source_role and item.source_role in _PRIORITY_ROLES:
        return True
    reason = (item.reason or "").lower()
    return any(kw in reason for kw in ("priority", "urgent", "unresolved", "high-priority"))


def build_resurfacing_bundle_frame(
    bundle: ContextBundle,
    *,
    why_now: str,
    now: datetime | None = None,
) -> ResurfacingBundleFrame:
    """Project a ContextBundle into a resurfacing suggestion frame.

    Requires ``may_resurface=True`` and rejects ``may_write=True`` — resurfacing
    is a suggestion-only surface that must not upgrade bundle authority.
    ``why_now`` is the caller-supplied, human-readable rationale anchored to a
    recorded signal rather than an opaque internal score.
    """
    if not bundle.authority.may_resurface:
        raise BundleAuthorityViolation(
            f"bundle {bundle.id} does not carry may_resurface=True; "
            "cannot consume for resurfacing without explicit resurfacing authority"
        )
    if bundle.authority.may_write:
        raise BundleAuthorityViolation(
            f"bundle {bundle.id} carries may_write=True; resurfacing is suggestion-only"
        )

    now = now or datetime.now(tz=timezone.utc)
    stale = False
    stale_reason: Optional[str] = None
    if bundle.expiry and bundle.expiry.stale_after is not None:
        stale_after = bundle.expiry.stale_after
        if stale_after.tzinfo is None:
            stale_after = stale_after.replace(tzinfo=timezone.utc)
        if now >= stale_after:
            stale = True
            stale_reason = bundle.expiry.reason

    surfaced: list[SurfacedItem] = []
    relatedness: list[SurfacedItem] = []
    priority: list[SurfacedItem] = []

    for item in bundle.included:
        seg = _surfaced(item)
        surfaced.append(seg)
        if _is_priority(item):
            priority.append(seg)
        else:
            relatedness.append(seg)

    return ResurfacingBundleFrame(
        bundle_id=bundle.id,
        why_now=why_now,
        surfaced_items=surfaced,
        relatedness_signals=relatedness,
        priority_signals=priority,
        stale=stale,
        stale_reason=stale_reason,
        suggestion_only=True,
        may_write=False,
    )


__all__ = [
    "BundleAuthorityViolation",
    "ResurfacingBundleFrame",
    "SurfacedItem",
    "build_resurfacing_bundle_frame",
]
