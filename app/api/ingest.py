from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_api_key
from app.ingest.chunker import ChunkConfig, chunk_text
from app.ingest.frontmatter import FrontmatterData, render_frontmatter
from app.ingest.staging import PendingChunk, stage_chunks
from app.ingest.vault import ensure_vault_file
from app.schemas.ingest import ChunkResult, IngestRequest, IngestResponse, SourceType
from app.settings import settings

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
    title = inferred_title or "Untitled"
    vault_root = Path(settings.vault_dir)

    fm = render_frontmatter(
        FrontmatterData(
            title=title,
            origin=origin,
            created=date.today(),
            tags=payload.tags,
            trust="provisional",
            source_ref=origin,
        )
    )

    relative_path = ensure_vault_file(vault_root, title, body_text, fm)

    chunk_strings = chunk_text(body_text)
    chunk_results: list[ChunkResult] = []
    pending: list[PendingChunk] = []
    for text in chunk_strings:
        chunk_id = str(uuid4())
        size = len(text.split())
        chunk_results.append(ChunkResult(id=chunk_id, text=text, size=size))
        pending.append(
            PendingChunk(
                id=chunk_id,
                text=text,
                size=size,
                doc_path=str(relative_path),
                trust="provisional",
            )
        )

    stage_chunks(pending, ChunkConfig())
    logger.info(
        "ingest.staged",
        extra={
            "path": str(relative_path),
            "tags": payload.tags,
            "chunks": len(chunk_results),
            "trust": "provisional",
        },
    )

    return IngestResponse(
        ok=True,
        title=title,
        path=str(relative_path),
        tags=payload.tags,
        trust="provisional",
        chunks=chunk_results,
    )
