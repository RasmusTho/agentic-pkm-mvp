"""Authenticated Companion API for the MVR-02 explicit instance default vault.

This router is one of the two production producers named by MVR-02 (#3856); the
other is the headless ``python -m app.instance.runtime default-vault-*`` CLI.
Both go through :class:`~app.instance.default_vault.InstanceDefaultVaultService`,
so they converge on the same locked registry state and the same redacted receipt.

Responses carry binding identity, provenance, and the registry revision only —
never a content-root path or any other raw binding payload.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_loopback_or_api_key
from app.instance.default_vault import (
    InstanceDefaultVaultService,
    VaultSelectionError,
)
from app.instance.runtime import open_default_vault_service
from app.instance.vault_registry import (
    RegistryDefaultConflict,
    RegistryError,
)

router = APIRouter(prefix="/instance", tags=["instance"])


class DefaultVaultResponse(BaseModel):
    vault_binding_id: str | None = None
    previous_vault_binding_id: str | None = None
    provenance: str | None = None
    registry_revision: int
    changed: bool = False


class DefaultVaultSetRequest(BaseModel):
    vault_binding_id: str = Field(min_length=1)


def _registry_path() -> Path:
    value = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
    if not value:
        # No registry binding is a configuration state, not a vault to guess at.
        raise HTTPException(
            status_code=503,
            detail="instance registry is not bound on this process",
        )
    return Path(value).expanduser().resolve(strict=False)


def get_default_vault_service() -> InstanceDefaultVaultService:
    # The sealed storage-mutation capability is handed over by the sanctioned
    # instance-runtime factory; this route never touches the seal itself.
    return open_default_vault_service(_registry_path())


def _fail(exc: RegistryError) -> HTTPException:
    if isinstance(exc, RegistryDefaultConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, VaultSelectionError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/default-vault",
    response_model=DefaultVaultResponse,
    dependencies=[Depends(require_loopback_or_api_key)],
)
def read_default_vault(
    service: InstanceDefaultVaultService = Depends(get_default_vault_service),
) -> DefaultVaultResponse:
    try:
        receipt = service.get()
    except RegistryError as exc:
        raise _fail(exc) from exc
    return DefaultVaultResponse(**receipt.as_dict())


@router.put(
    "/default-vault",
    response_model=DefaultVaultResponse,
    dependencies=[Depends(require_loopback_or_api_key)],
)
def set_default_vault(
    payload: DefaultVaultSetRequest,
    service: InstanceDefaultVaultService = Depends(get_default_vault_service),
) -> DefaultVaultResponse:
    try:
        receipt = service.set(payload.vault_binding_id)
    except RegistryError as exc:
        raise _fail(exc) from exc
    return DefaultVaultResponse(**receipt.as_dict())


@router.delete(
    "/default-vault",
    response_model=DefaultVaultResponse,
    dependencies=[Depends(require_loopback_or_api_key)],
)
def clear_default_vault(
    service: InstanceDefaultVaultService = Depends(get_default_vault_service),
) -> DefaultVaultResponse:
    try:
        receipt = service.clear()
    except RegistryError as exc:
        raise _fail(exc) from exc
    return DefaultVaultResponse(**receipt.as_dict())


__all__ = ["get_default_vault_service", "router"]
