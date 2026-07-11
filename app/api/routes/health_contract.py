from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.health_contract import DEFAULT_CONTRACT

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


READY_STATES = {"running", "catch_up", "degraded"}


async def _evaluate_contract() -> dict[str, Any]:
    # DEFAULT_CONTRACT.evaluate() performs blocking I/O (a live DB ping among
    # other checks). This is the same blocking-inline-in-async-def bug class
    # as /api/health (2026-07-11 prod outage): /readyz is the actual
    # container healthcheck target, so keeping it off the event loop matters
    # even more than /api/health itself. Offload to a worker thread.
    return await asyncio.to_thread(DEFAULT_CONTRACT.evaluate)


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    snapshot = await _evaluate_contract()
    if snapshot["state"] not in READY_STATES:
        raise HTTPException(
            status_code=503,
            detail={
                "state": snapshot["state"],
                "reason": snapshot["reason"],
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
    return await _evaluate_contract()


__all__ = ["router"]
