from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.compatibility_mutation import seal_vault_mutation
from app.heimdal.screen_capture import ingest_screen_bundle

# MVR-05B3: the vault-bound Heimdal ingress carries the pre-05C mutation seal.
router = APIRouter(
    prefix="/api/heimdal/screen",
    tags=["heimdal"],
    dependencies=[Depends(seal_vault_mutation)],
)


@router.post("/capture")
def capture_screen_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Host ingress endpoint; SCREEN-01's production consent/sensor call site."""
    try:
        ack = ingest_screen_bundle(bundle)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ack.__dict__
