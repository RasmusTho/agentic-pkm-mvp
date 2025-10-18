from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from uuid import uuid4

from app.ingest.chunker import ChunkConfig, chunk_text
from app.ingest.frontmatter import FrontmatterData, render_frontmatter
from app.ingest.staging import PendingChunk, stage_chunks
from app.ingest.vault import ensure_vault_file
from app.schemas.ingest import ChunkResult, IngestResponse
from app.settings import settings

logger = logging.getLogger(__name__)


def ingest_text(
    body_text: str,
    origin: str,
    title_hint: str | None = None,
    *,
    tags: list[str] | None = None,
    trust: str = "provisional",
) -> IngestResponse:
    if not body_text or not body_text.strip():
        raise ValueError("Body text is empty")

    title = (title_hint or body_text.splitlines()[0] or "Untitled").strip()[:120] or "Untitled"
    vault_root = Path(settings.vault_dir)
    inbox_root = vault_root / settings.inbox_subdir

    frontmatter = render_frontmatter(
        FrontmatterData(
            title=title,
            origin=origin,
            created=date.today(),
            tags=tags or [],
            trust=trust,
            source_ref=origin,
        )
    )

    file_path = ensure_vault_file(inbox_root, title, body_text, frontmatter)
    relative_path = Path(settings.inbox_subdir) / file_path

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
                trust=trust,
            )
        )

    stage_chunks(pending, ChunkConfig())
    logger.info(
        "ingest.staged",
        extra={
            "path": str(relative_path),
            "tags": tags or [],
            "chunks": len(chunk_results),
            "trust": trust,
        },
    )

    return IngestResponse(
        ok=True,
        title=title,
        path=str(relative_path),
        tags=tags or [],
        trust=trust,
        chunks=chunk_results,
    )
