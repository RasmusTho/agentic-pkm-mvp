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
    # `evaluate()` does blocking DB I/O (a live Postgres ping, outbox reads,
    # index diagnostics). The api container healthcheck polls `/readyz` on a
    # short interval, so keep it off the event loop for the same reason as
    # `/api/health` (#3461).
    snapshot = await run_in_threadpool(DEFAULT_CONTRACT.evaluate)
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
    return await run_in_threadpool(DEFAULT_CONTRACT.evaluate)


__all__ = ["router"]
