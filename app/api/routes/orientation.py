from __future__ import annotations

from fastapi import APIRouter

from app.orientation.runtime import OrientationFrame, build_orientation_frame

router = APIRouter()


@router.get("/orientation", response_model=OrientationFrame)
async def orientation() -> OrientationFrame:
    return build_orientation_frame()


__all__ = ["router", "OrientationFrame"]
