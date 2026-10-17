from typing import Any

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.api.compatibility_mutation import (
    reject_scoped_vault_mutation,
    require_compatibility_write_root,
    seal_vault_mutation,
)
from app.api.request_active_context import (
    refuse_carrier_until_binding_aware,
    route_read_vault_root_or_selection_required,
)
from app.api.routes.vault_resolution import compatibility_vault_root_or_selection_required
from app.auth import api_key_header, resolve_auth_subject
from app.heimdal.screen_capture import ingest_screen_bundle
from app.heimdal.screen_control import screen_control_status
from app.settings.models import SCREEN_CONTROL_KEYS
from app.vault.manager import VaultManager
from app.vault.settings_service import SettingsService, SettingsWriteError

# MVR-05B3: the vault-bound Heimdal ingress carries the pre-05C mutation seal.
router = APIRouter(
    prefix="/api/heimdal/screen",
    tags=["heimdal"],
    dependencies=[Depends(seal_vault_mutation)],
)


def _control_actor(request: Request, api_key: str | None = Depends(api_key_header)) -> str:
    return resolve_auth_subject(request, api_key)


class ScreenControlWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: Any


@router.get(
    "/control",
    response_model=None,
    dependencies=[Depends(_control_actor), Depends(refuse_carrier_until_binding_aware)],
)
def read_screen_control(
    app_id: str | None = None, scopes: list[str] = Query(default=[]),
) -> dict[str, Any] | JSONResponse:
    vault_root = route_read_vault_root_or_selection_required()
    if isinstance(vault_root, JSONResponse):
        return vault_root
    context = VaultManager().validate_vault(vault_root, heal_identity=False)
    return screen_control_status(context, app_id=app_id, scopes=scopes)


@router.put(
    "/control",
    response_model=None,
    dependencies=[Depends(reject_scoped_vault_mutation)],
)
def write_screen_control(
    change: ScreenControlWrite,
    request: Request,
    api_key: str | None = Depends(api_key_header),
) -> dict[str, Any] | JSONResponse:
    actor = resolve_auth_subject(request, api_key)
    if change.key not in SCREEN_CONTROL_KEYS:
        raise HTTPException(status_code=422, detail="unknown screen control")
    vault_root = compatibility_vault_root_or_selection_required(require_initialized=True)
    if isinstance(vault_root, JSONResponse):
        return vault_root
    require_compatibility_write_root(request, vault_root)
    manager = VaultManager()
    context = manager.validate_vault(vault_root, heal_identity=False)
    permissions = manager.permissions_for_context(context)
    if not permissions.allow_writes_to_vault or not permissions.allow_shared_settings_edits:
        raise HTTPException(status_code=403, detail="screen control writes require shared-settings authority")
    try:
        _, receipt = SettingsService().update_setting(
            context, change.key, change.value, surface="api", actor=actor,
        )
    except SettingsWriteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        **screen_control_status(context),
        "receipt": {**asdict(receipt), "receipt_type": receipt.receipt_type} if receipt else None,
    }


@router.post("/capture")
def capture_screen_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Host ingress endpoint; SCREEN-01's production consent/sensor call site."""
    try:
        ack = ingest_screen_bundle(bundle)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ack.__dict__
