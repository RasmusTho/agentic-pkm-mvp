from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.context_bundles.runtime_registry import get_emitted_bundle
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
    """Resolve an emitted orientation-scoped bundle for the given id.

    This route consumes bundles emitted earlier in this process. It must not
    synthesize a construction envelope when the requested emitted bundle is
    missing, because that would hide addressability failures from operators.
    """
    bundle = get_emitted_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"context bundle {bundle_id!r} was not emitted in this runtime process; "
                "emit it before orientation consumption"
            ),
        )
    return bundle


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
