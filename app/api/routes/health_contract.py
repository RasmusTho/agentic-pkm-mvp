from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.health_contract import DEFAULT_CONTRACT

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


READY_STATES = {"running", "catch_up", "degraded"}


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    snapshot = DEFAULT_CONTRACT.evaluate()
    if snapshot["state"] not in READY_STATES:
        raise HTTPException(
            status_code=503,
            detail={"state": snapshot["state"], "reason": snapshot["reason"]},
        )
    return {"state": snapshot["state"], "reason": snapshot["reason"]}


@router.get("/status")
async def health_status() -> dict[str, Any]:
    return DEFAULT_CONTRACT.evaluate()


__all__ = ["router"]
