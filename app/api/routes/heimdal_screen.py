from typing import Any

from fastapi import APIRouter, HTTPException

from app.heimdal.screen_capture import ingest_screen_bundle

router = APIRouter(prefix="/api/heimdal/screen", tags=["heimdal"])


@router.post("/capture")
def capture_screen_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Host ingress endpoint; SCREEN-01's production consent/sensor call site."""
    try:
        ack = ingest_screen_bundle(bundle)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ack.__dict__
