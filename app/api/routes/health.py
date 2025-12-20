from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.cli.health import run_health

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    return run_health()


__all__ = ["router"]
