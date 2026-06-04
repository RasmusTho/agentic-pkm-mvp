"""Read-only Context Bundle construction route (#1560).

Exposes the first production surface for Context Bundles: a GET route that
returns an inspectable ``ContextBundle`` envelope sourced from the typed-contract
building blocks. No vault mutation, no real-retrieval dependency (that lands in
#1562). Authority flags are surfaced verbatim; ``may_write`` is never upgraded
here.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.context_bundles.construction import build_inspectable_bundle
from app.context_bundles.schema import ContextBundle

router = APIRouter()


@router.get("/context-bundles/{bundle_id}", response_model=ContextBundle)
async def get_context_bundle(bundle_id: str) -> ContextBundle:
    """Return an inspectable, read-only ``ContextBundle`` envelope."""
    return build_inspectable_bundle(bundle_id)


__all__ = ["router"]
