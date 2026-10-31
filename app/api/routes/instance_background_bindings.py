"""Authenticated Companion API for the staged MVR-06A background-binding intent.

One of the two production surfaces for durable background intent; the other is the
headless ``python -m app.instance.runtime background-binding-*`` CLI. Both go through
:class:`~app.instance.background_authority.BackgroundIntentAdminService`.

MVR-06A posture: list/inspect are read-only; every intent-changing command answers
``409 capability_not_ready`` without touching durable state, because the legacy picker
bridge remains the authoritative single-watcher owner until the MVR-06B supervisor
handoff. Responses carry binding ids, modes, and revisions only -- never a content-root
path or any other raw binding payload.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_loopback_or_api_key
from app.instance.background_authority import (
    BackgroundIntentAdminService,
    BackgroundIntentNotReadyError,
)
from app.instance.runtime import open_background_intent_admin_service
from app.instance.vault_registry import RegistryError

router = APIRouter(prefix="/instance", tags=["instance"])


class BackgroundBindingRequest(BaseModel):
    vault_binding_id: str = Field(min_length=1)


def _registry_path() -> Path:
    value = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail="instance registry is not bound on this process",
        )
    return Path(value).expanduser().resolve(strict=False)


def get_background_intent_service() -> BackgroundIntentAdminService:
    return open_background_intent_admin_service(_registry_path())


def _not_ready(exc: BackgroundIntentNotReadyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": BackgroundIntentNotReadyError.error_code, "message": str(exc)},
    )


@router.get(
    "/background-bindings",
    dependencies=[Depends(require_loopback_or_api_key)],
)
def list_background_bindings(
    service: BackgroundIntentAdminService = Depends(get_background_intent_service),
) -> dict[str, Any]:
    try:
        return service.list()
    except RegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/background-bindings/{vault_binding_id}",
    dependencies=[Depends(require_loopback_or_api_key)],
)
def inspect_background_binding(
    vault_binding_id: str,
    service: BackgroundIntentAdminService = Depends(get_background_intent_service),
) -> dict[str, Any]:
    try:
        return service.inspect(vault_binding_id)
    except RegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/background-bindings",
    dependencies=[Depends(require_loopback_or_api_key)],
)
def add_background_binding(
    payload: BackgroundBindingRequest,
    service: BackgroundIntentAdminService = Depends(get_background_intent_service),
) -> dict[str, Any]:
    try:
        return service.add(payload.vault_binding_id)
    except BackgroundIntentNotReadyError as exc:
        raise _not_ready(exc) from exc


@router.delete(
    "/background-bindings/{vault_binding_id}",
    dependencies=[Depends(require_loopback_or_api_key)],
)
def remove_background_binding(
    vault_binding_id: str,
    service: BackgroundIntentAdminService = Depends(get_background_intent_service),
) -> dict[str, Any]:
    try:
        return service.remove(vault_binding_id)
    except BackgroundIntentNotReadyError as exc:
        raise _not_ready(exc) from exc


__all__ = ["get_background_intent_service", "router"]
