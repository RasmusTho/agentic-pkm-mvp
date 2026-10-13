from typing import Any

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from app.api.compatibility_mutation import reject_scoped_vault_mutation
from app.auth import api_key_header, resolve_auth_subject
from app.heimdal.screen_capture import ingest_screen_bundle
from app.heimdal.screen_control import screen_control_status
from app.settings.models import SCREEN_CONTROL_KEYS
from app.vault.manager import get_vault_manager
from app.vault.settings_service import SettingsService, SettingsWriteError

router = APIRouter(prefix="/api/heimdal/screen", tags=["heimdal"])


def _control_actor(request: Request, api_key: str | None = Depends(api_key_header)) -> str:
    return resolve_auth_subject(request, api_key)


class ScreenControlWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: Any


@router.get("/control", dependencies=[Depends(_control_actor)])
def read_screen_control(
    app_id: str | None = None, scopes: list[str] = Query(default=[]),
) -> dict[str, Any]:
    return screen_control_status(get_vault_manager().context, app_id=app_id, scopes=scopes)


@router.put("/control", dependencies=[Depends(reject_scoped_vault_mutation)])
def write_screen_control(
    change: ScreenControlWrite, actor: str = Depends(_control_actor),
) -> dict[str, Any]:
    if change.key not in SCREEN_CONTROL_KEYS:
        raise HTTPException(status_code=422, detail="unknown screen control")
    manager = get_vault_manager()
    context = manager.context
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
