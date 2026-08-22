"""Read-only devUI composition API."""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.routes.cockpit import read_registry as read_cockpit_registry
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.config import load_paths as load_builderops_paths
from app.builderops.devui_composition import compose_owner_snapshot
from app.builderops.devui_focus import FocusContractError, compose_focus_view
from app.builderops.devui_focus_inputs import FocusInputError, read_focus_inputs
from app.builderops.devui_overview import compose_overview_view
from app.builderops.devui_overview_inputs import derive_overview_inputs


_LOCAL_ONLY_DETAIL = "devUI composition is available only to a local caller"
_FORWARDED_IDENTITY_HEADERS = frozenset(
    {
        "cf-connecting-ip",
        "forwarded",
        "true-client-ip",
        "via",
        "x-client-ip",
        "x-envoy-external-address",
        "x-original-forwarded-for",
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


def _has_local_host_header(request: Request) -> bool:
    value = request.headers.get("host", "").strip().lower()
    if value == "testserver" and request.client is not None:
        return request.client.host == "testclient"
    if value.startswith("["):
        closing = value.find("]")
        hostname = value[1:closing] if closing > 0 else ""
    else:
        hostname = value.rsplit(":", 1)[0] if value.count(":") == 1 else value
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _require_local_caller(
    request: Request,
) -> None:
    """Admit only a direct loopback peer with no forwarded identity."""

    if (
        not _is_immediate_loopback(request)
        or not _has_local_host_header(request)
        or _has_forwarded_identity(request)
    ):
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


@router.get("/overview")
async def overview() -> dict[str, Any]:
    """Compose one admitted, stateless Overview projection from one read."""

    composition = compose_owner_snapshot(
        cockpit_reader=read_cockpit_registry,
        ckm_reader=_read_ckm_capabilities,
    )
    work_provider = composition.get("providers", {}).get("work")
    candidates = derive_overview_inputs(work_provider=work_provider)
    return compose_overview_view(composition=composition, candidates=candidates)


@router.get("/focus")
async def focus(subject: str) -> dict[str, Any]:
    """Compose one admitted, stateless Focus read without joining root payloads."""

    try:
        return compose_focus_view(**read_focus_inputs(subject))
    except (FocusInputError, FocusContractError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="devUI Focus subject is unavailable or unsupported",
        ) from exc


__all__ = ["router"]
