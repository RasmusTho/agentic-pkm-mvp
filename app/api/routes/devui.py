"""Read-only devUI composition API."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.routes.cockpit import read_registry as read_cockpit_registry
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.config import load_paths as load_builderops_paths
from app.builderops.devui_composition import compose_owner_snapshot


_LOCAL_ONLY_DETAIL = "devUI composition is available only to a local caller"
_FORWARDED_IDENTITY_HEADERS = frozenset(
    {
        "cf-connecting-ip",
        "forwarded",
        "true-client-ip",
        "x-client-ip",
        "x-real-ip",
    }
)


def _has_forwarded_identity(request: Request) -> bool:
    return any(
        name.startswith("x-forwarded-") or name in _FORWARDED_IDENTITY_HEADERS
        for name in request.headers
    )


def _is_immediate_loopback(request: Request) -> bool:
    host = request.client.host if request.client is not None else None
    if host in {"localhost", "testclient"}:
        return True
    if not host:
        return False
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _require_local_caller(
    request: Request,
) -> None:
    """Admit only a direct loopback peer with no forwarded identity."""

    if not _is_immediate_loopback(request) or _has_forwarded_identity(request):
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
