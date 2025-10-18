from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_api_key
from app.schemas.ingest import IngestRequest, IngestResponse

router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_payload(payload: IngestRequest) -> IngestResponse:
    """
    Prototype handler for ingest workflow.

    This will be expanded to parse source content, create frontmatter, and index chunks.
    For now it raises 501 Not Implemented to make the contract explicit.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Ingest pipeline not implemented yet",
    )
