from __future__ import annotations

from fastapi import APIRouter

from app.source_understanding import (
    SourceUnderstandingPacket,
    SourceUnderstandingRequest,
    build_source_understanding_packet,
)

router = APIRouter(prefix="/source-understanding", tags=["source-understanding"])


@router.post("/p0", response_model=SourceUnderstandingPacket)
async def source_understanding_p0(
    request: SourceUnderstandingRequest,
) -> SourceUnderstandingPacket:
    return build_source_understanding_packet(request)


__all__ = ["router"]
