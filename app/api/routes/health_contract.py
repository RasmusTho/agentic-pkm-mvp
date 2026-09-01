from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.health_contract import DEFAULT_CONTRACT

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


READY_STATES = {"running", "catch_up", "degraded"}


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    snapshot = await run_in_threadpool(DEFAULT_CONTRACT.evaluate)
    product_readiness = snapshot.get("product_readiness") or {}
    if snapshot["state"] not in READY_STATES or product_readiness.get("ready") is False:
        reason = (
            snapshot.get("reason")
            if product_readiness.get("ready") is not False
            else f"product replay refused: {product_readiness.get('reason', 'verification incomplete')}"
        )
        raise HTTPException(
            status_code=503,
            detail={
                "state": snapshot["state"],
                "reason": reason,
                "class": snapshot.get("bootstrap_state") or "active",
            },
        )
    return {
        "state": snapshot["state"],
        "reason": snapshot.get("bootstrap_reason") or snapshot["reason"],
        "class": snapshot.get("bootstrap_state") or "active",
    }


@router.get("/status")
async def health_status() -> dict[str, Any]:
    return await run_in_threadpool(DEFAULT_CONTRACT.evaluate)


__all__ = ["router"]
