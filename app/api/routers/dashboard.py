from __future__ import annotations
from fastapi import APIRouter

router = APIRouter()

@router.get("/dashboard/ping")
def dashboard_ping() -> dict:
    return {"ok": True}
