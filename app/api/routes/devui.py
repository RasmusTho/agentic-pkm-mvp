"""Read-only devUI composition API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.routes.cockpit import read_registry as read_cockpit_registry
from app.auth import (
    SUBJECT_TRUSTED_LOOPBACK,
    api_key_header,
    resolve_auth_subject,
)
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.config import load_paths as load_builderops_paths
from app.builderops.devui_composition import compose_owner_snapshot


_LOCAL_ONLY_DETAIL = "devUI composition is available only to a local caller"


def _require_local_caller(
    request: Request,
    api_key: str | None = Depends(api_key_header),
) -> None:
    """Keep CKM's single-operator-local audience narrower than API auth."""

    try:
        subject = resolve_auth_subject(request, api_key)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_LOCAL_ONLY_DETAIL,
        ) from None
    if subject != SUBJECT_TRUSTED_LOOPBACK:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_LOCAL_ONLY_DETAIL,
        )


router = APIRouter(
    prefix="/devui",
    tags=["devui"],
    dependencies=[Depends(_require_local_caller)],
)


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
