from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_api_key
from app.schemas.ingest import IngestRequest, IngestResponse
from app.search.service import ingest_object
from app.settings import settings

router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_api_key)],
)


@router.post("", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_payload(payload: IngestRequest) -> IngestResponse:
    try:
        object_id, dims = ingest_object(
            object_id=payload.id,
            kind=payload.kind,
            source_ref=payload.source_ref,
            payload=payload.payload,
            text=payload.text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return IngestResponse(object_id=object_id, dimensions=dims, model=settings.embed_model)
