"""Production resurfacing bundle consumption route (#1563).

Wires ``app/resurfacing/bundle_consumer.py::build_resurfacing_bundle_frame``
into the production resurfacing path. Resurfacing is suggestion-only: the frame
carries an auditable why-now anchored to a named signal, preserves provenance
and exclusions, keeps ``may_write=false``, and rejects bundles not scoped for
``resurface``. No authority upgrade.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.context_bundles.runtime_registry import get_emitted_bundle
from app.context_bundles.schema import ContextBundle
from app.resurfacing.bundle_consumer import (
    BundleAuthorityViolation,
    ResurfacingBundleFrame,
    WhyNowSignal,
    build_resurfacing_bundle_frame,
)

router = APIRouter()


def _resurfacing_bundle_source(bundle_id: str) -> ContextBundle:
    """Resolve an emitted resurface-scoped bundle for the given id.

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
                "emit it before resurfacing consumption"
            ),
        )
    return bundle


@router.get("/resurfacing/bundle/{bundle_id}", response_model=ResurfacingBundleFrame)
async def resurfacing_from_bundle(bundle_id: str) -> ResurfacingBundleFrame:
    """Consume a ContextBundle into a suggestion-only resurfacing frame."""
    bundle = _resurfacing_bundle_source(bundle_id)
    why_now = WhyNowSignal(
        rationale=f"bundle {bundle.id} re-entered view via the resurfacing runtime",
        signal_name="resurfacing_runtime",
    )
    try:
        return build_resurfacing_bundle_frame(bundle, why_now=why_now)
    except BundleAuthorityViolation as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
