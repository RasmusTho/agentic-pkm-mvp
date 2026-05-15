"""Consume a ContextBundle from orientation (CONTEXT-BUNDLES-03).

Orientation reads a bundle to reconstruct situational state. The frame keeps
facts, inferences, candidate actions, and stale context in distinct buckets,
preserves per-item provenance and exclusions for human inspection, and refuses
to launder bundle authority into write authorization.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.context_bundles.schema import (
    ContextBundle,
    ExcludedItem,
    IncludedItem,
    ItemProvenance,
)


class BundleAuthorityViolation(Exception):
    """Raised when a bundle attempts to grant write authority to orientation."""


class OrientationSegment(BaseModel):
    artifact_id: str
    reason: str
    provenance: Optional[ItemProvenance] = None
    trust_state: Optional[str] = None
    review_state: Optional[str] = None


class OrientationBundleFrame(BaseModel):
    bundle_id: str
    facts: list[OrientationSegment] = Field(default_factory=list)
    inferences: list[OrientationSegment] = Field(default_factory=list)
    candidate_actions: list[OrientationSegment] = Field(default_factory=list)
    exclusions: list[ExcludedItem] = Field(default_factory=list)
    stale: bool = False
    stale_reason: Optional[str] = None
    read_only: bool = True
    may_write: bool = False


_CANDIDATE_ROLES = {"candidate_action", "candidate", "proposal"}
_INFERENCE_ORIGINS = {"agent inference", "model inference", "orientation inference"}


def _classify(item: IncludedItem) -> str:
    if item.source_role and item.source_role in _CANDIDATE_ROLES:
        return "candidate"
    reason = (item.reason or "").lower()
    if "candidate" in reason or "proposal" in reason or "next action" in reason:
        return "candidate"
    origin = (item.provenance.origin if item.provenance else "") or ""
    if origin.lower() in _INFERENCE_ORIGINS:
        return "inference"
    if "inference" in reason or "inferred" in reason:
        return "inference"
    return "fact"


def _segment(item: IncludedItem) -> OrientationSegment:
    return OrientationSegment(
        artifact_id=item.artifact_id,
        reason=item.reason,
        provenance=item.provenance,
        trust_state=item.trust_state,
        review_state=item.review_state,
    )


def build_orientation_frame_from_bundle(
    bundle: ContextBundle,
    *,
    now: datetime | None = None,
) -> OrientationBundleFrame:
    """Project a ContextBundle into an orientation frame.

    Refuses to consume a bundle that lacks `may_orient` authority or claims
    `may_write=True` — orientation is a non-write surface and must not silently
    upgrade authority or accept bundles not authorized for orientation use.
    """
    if not bundle.authority.may_orient:
        raise BundleAuthorityViolation(
            f"bundle {bundle.id} does not carry may_orient=True; "
            "cannot consume for orientation without explicit orientation authority"
        )
    if bundle.authority.may_write:
        raise BundleAuthorityViolation(
            f"bundle {bundle.id} carries may_write=True; orientation is non-write"
        )

    facts: list[OrientationSegment] = []
    inferences: list[OrientationSegment] = []
    candidates: list[OrientationSegment] = []

    for item in bundle.included:
        bucket = _classify(item)
        segment = _segment(item)
        if bucket == "candidate":
            candidates.append(segment)
        elif bucket == "inference":
            inferences.append(segment)
        else:
            facts.append(segment)

    now = now or datetime.now(tz=timezone.utc)
    stale = False
    stale_reason: Optional[str] = None
    if bundle.expiry and bundle.expiry.stale_after is not None:
        if now >= bundle.expiry.stale_after:
            stale = True
            stale_reason = bundle.expiry.reason

    return OrientationBundleFrame(
        bundle_id=bundle.id,
        facts=facts,
        inferences=inferences,
        candidate_actions=candidates,
        exclusions=list(bundle.excluded),
        stale=stale,
        stale_reason=stale_reason,
        read_only=True,
        may_write=False,
    )


__all__ = [
    "BundleAuthorityViolation",
    "OrientationBundleFrame",
    "OrientationSegment",
    "build_orientation_frame_from_bundle",
]
