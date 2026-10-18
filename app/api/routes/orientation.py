from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.request_active_context import current_scoped_route_read, scoped_route_read
from app.context_bundles.runtime_registry import get_emitted_bundle
from app.context_bundles.schema import ContextBundle
from app.orientation.bundle_consumer import (
    BundleAuthorityViolation,
    OrientationBundleFrame,
    build_orientation_frame_from_bundle,
)
from app.observability.status_service import get_orientation_signals
from app.orientation.runtime import OrientationFrame, build_orientation_frame

router = APIRouter()


@router.get("/orientation", response_model=OrientationFrame)
@scoped_route_read
def orientation() -> OrientationFrame:
    """The orientation frame; a scoped read computes it from its binding's signals."""
    scoped = current_scoped_route_read()
    if scoped is None:
        return build_orientation_frame()
    if scoped.vault_binding_id is None:
        # A zero-binding selection has no binding whose work could orient it.
        raise HTTPException(status_code=409, detail="active_context_binding_required")
    return build_orientation_frame(
        signals=get_orientation_signals(vault_binding_id=scoped.vault_binding_id)
    )


def _visible_emitted_bundle(bundle_id: str) -> ContextBundle | None:
    """The emitted bundle this request may see (MVR-05B4c5).

    A scoped read sees only its binding's own emission (a zero-binding selection
    sees none); a carrier-free read keeps the legacy view.
    """
    scoped = current_scoped_route_read()
    if scoped is None:
        return get_emitted_bundle(bundle_id)
    if scoped.vault_binding_id is None:
        return None
    return get_emitted_bundle(bundle_id, vault_binding_id=scoped.vault_binding_id)


def _orientation_bundle_source(bundle_id: str) -> ContextBundle:
    """Resolve an emitted orientation-scoped bundle for the given id.

    This route consumes bundles emitted earlier in this process. It must not
    synthesize a construction envelope when the requested emitted bundle is
    missing, because that would hide addressability failures from operators.
    """
    bundle = _visible_emitted_bundle(bundle_id)
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
@scoped_route_read
def orientation_from_bundle(bundle_id: str) -> OrientationBundleFrame:
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
