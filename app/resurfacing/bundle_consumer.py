"""Consume a ContextBundle from resurfacing (CONTEXT-BUNDLES-04).

Resurfacing reads a bundle to support "why now" suggestions. The frame keeps
relatedness signals, priority signals, and why-now provenance distinct so the
decision is auditable rather than opaque. It must not launder bundle authority
into write permission — resurfacing is suggestion-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.context_bundles.schema import (
    ContextBundle,
    ExcludedItem,
    IncludedItem,
    ItemProvenance,
)


class BundleAuthorityViolation(Exception):
    """Raised when a bundle carries prohibited authority for resurfacing."""


class WhyNowSignal(BaseModel):
    """Provenance-backed rationale for a resurfacing event.

    ``rationale`` is the human-readable explanation; ``signal_name`` anchors it
    to a specific recorded signal (e.g. "dependency_gap", "watcher_run_24h")
    so the "why now" is auditable rather than opaque semantic relatedness.
    Both fields must be non-empty after whitespace stripping — blank values
    leave no auditable anchor.
    """

    rationale: str
    signal_name: str

    @field_validator("rationale", "signal_name")
    @classmethod
    def _must_be_non_blank(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(
                f"{info.field_name} must be a non-empty string — "
                "blank why-now anchors leave the surfacing decision unauditable"
            )
        return v


class SurfacedItem(BaseModel):
    artifact_id: str
    reason: str
    provenance: Optional[ItemProvenance] = None
    source_role: Optional[str] = None
    trust_state: Optional[str] = None


class ResurfacingBundleFrame(BaseModel):
    bundle_id: str
    why_now: str
    why_now_signal_name: str
    surfaced_items: list[SurfacedItem] = Field(default_factory=list)
    relatedness_signals: list[SurfacedItem] = Field(default_factory=list)
    priority_signals: list[SurfacedItem] = Field(default_factory=list)
    exclusions: list[ExcludedItem] = Field(default_factory=list)
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
    # Priority is classified solely by the structured `source_role` field —
    # substring matching on the free-text `reason` is unreliable (it would
    # classify "not urgent" or "low priority" as priority).
    return bool(item.source_role and item.source_role in _PRIORITY_ROLES)


def build_resurfacing_bundle_frame(
    bundle: ContextBundle,
    *,
    why_now: WhyNowSignal,
    now: datetime | None = None,
) -> ResurfacingBundleFrame:
    """Project a ContextBundle into a resurfacing suggestion frame.

    Requires ``may_resurface=True`` and rejects ``may_write=True`` — resurfacing
    is a suggestion-only surface that must not upgrade bundle authority.

    ``why_now`` must be a ``WhyNowSignal`` — ``signal_name`` anchors the
    rationale to a specific recorded signal so the surfacing decision is
    auditable rather than opaque semantic relatedness.
    """
    if not isinstance(why_now, WhyNowSignal):
        raise TypeError(
            "why_now must be a WhyNowSignal — plain strings are not accepted "
            "because they leave no provenance anchor for the surfacing decision"
        )
    why_now_rationale = why_now.rationale
    why_now_signal_name = why_now.signal_name

    if not bundle.authority.may_resurface:
        raise BundleAuthorityViolation(
            f"bundle {bundle.id} does not carry may_resurface=True; "
            "cannot consume for resurfacing without explicit resurfacing authority"
        )
    if bundle.authority.may_write:
        raise BundleAuthorityViolation(
            f"bundle {bundle.id} carries may_write=True; resurfacing is suggestion-only"
        )
    if "resurface" not in bundle.intended_use:
        raise BundleAuthorityViolation(
            f"bundle {bundle.id} intended_use={bundle.intended_use!r} does not include 'resurface'; "
            "bundle was not scoped for resurfacing consumption"
        )

    now = now or datetime.now(tz=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
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
        why_now=why_now_rationale,
        why_now_signal_name=why_now_signal_name,
        surfaced_items=surfaced,
        relatedness_signals=relatedness,
        priority_signals=priority,
        exclusions=list(bundle.excluded),
        stale=stale,
        stale_reason=stale_reason,
        suggestion_only=True,
        may_write=False,
    )


__all__ = [
    "BundleAuthorityViolation",
    "ResurfacingBundleFrame",
    "SurfacedItem",
    "WhyNowSignal",
    "build_resurfacing_bundle_frame",
]
