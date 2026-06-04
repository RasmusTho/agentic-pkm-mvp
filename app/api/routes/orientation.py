from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.context_bundles.construction import build_inspectable_bundle
from app.context_bundles.schema import ContextBundle
from app.orientation.bundle_consumer import (
    BundleAuthorityViolation,
    OrientationBundleFrame,
    build_orientation_frame_from_bundle,
)
from app.orientation.runtime import OrientationFrame, build_orientation_frame

router = APIRouter()


@router.get("/orientation", response_model=OrientationFrame)
async def orientation() -> OrientationFrame:
    return build_orientation_frame()


def _orientation_bundle_source(bundle_id: str) -> ContextBundle:
    """Resolve an orientation-scoped, inspectable bundle for the given id.

    The construction envelope is scoped for ``orient`` and carries
    ``may_write=false``; mis-scoped bundles are rejected by the consumer.
    """
    return build_inspectable_bundle(bundle_id)


@router.get("/orientation/bundle/{bundle_id}", response_model=OrientationBundleFrame)
async def orientation_from_bundle(bundle_id: str) -> OrientationBundleFrame:
    """Consume a ContextBundle into a read-only orientation frame.

    Provenance and exclusions are preserved; authority gating is enforced by
    ``build_orientation_frame_from_bundle`` (rejects bundles not scoped for
    ``orient`` or carrying ``may_write=true``). No authority upgrade.
    """
    bundle = _orientation_bundle_source(bundle_id)
    try:
        return build_orientation_frame_from_bundle(bundle)
    except BundleAuthorityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router", "OrientationFrame"]
