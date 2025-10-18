from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_api_key
from app.ingest.service import ingest_text
from app.schemas.ingest import IngestRequest, IngestResponse, SourceType

router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_api_key)],
)

logger = logging.getLogger(__name__)


def _extract_text(payload: IngestRequest) -> tuple[str, str, str]:
    source = payload.source
    if source.type == SourceType.text:
        if not source.text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Missing inline text"
            )
        raw = source.text
        stripped = raw.strip()
        if not stripped:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Inline text is empty"
            )
        candidate_title = payload.notes or stripped.splitlines()[0]
        candidate_title = " ".join(candidate_title.split())[:120]
        title = candidate_title or "Untitled"
        return raw, "inline", title
    if source.type == SourceType.file:
        if not source.path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing file path",
            )
        file_path = Path(source.path).expanduser()
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found",
            )
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is empty",
            )
        return content, str(file_path), file_path.stem
    if source.type == SourceType.url:
        if not source.url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing url",
            )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="URL ingestion not implemented",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported source type",
    )


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_payload(payload: IngestRequest) -> IngestResponse:
    body_text, origin, inferred_title = _extract_text(payload)
    return ingest_text(
        body_text,
        origin,
        inferred_title,
        tags=payload.tags,
        trust="provisional",
    )
