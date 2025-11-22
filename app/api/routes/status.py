from __future__ import annotations

from fastapi import APIRouter

from app.observability.status_model import SystemStatus
from app.observability.status_service import get_system_status

router = APIRouter()


@router.get("/status", response_model=SystemStatus)
async def status() -> SystemStatus:
    return get_system_status()


__all__ = ["router"]
