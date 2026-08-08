"""Read-only devUI composition API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.routes.cockpit import read_registry as read_cockpit_registry
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.config import load_paths as load_builderops_paths
from app.builderops.devui_composition import compose_owner_snapshot


router = APIRouter(prefix="/devui", tags=["devui"])


def _read_ckm_capabilities() -> Any:
    paths = load_builderops_paths()
    return CkmQueryService(paths.db_path).list_capabilities()


@router.get("/composition")
async def composition() -> dict[str, Any]:
    """Rebuild the unified read envelope without caching or mutation."""

    return compose_owner_snapshot(
        cockpit_reader=read_cockpit_registry,
        ckm_reader=_read_ckm_capabilities,
    )


__all__ = ["router"]
