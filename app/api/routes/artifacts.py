"""Read-only artifact note endpoint.

GET /api/artifacts/note?note_path=<path>[&artifact_id=<id>]

Returns a vault note's metadata and body without mutating it.
Rejects path traversal and paths outside the configured vault root.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.config.paths import resolve_vault_root

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactNoteResponse(BaseModel):
    artifact_id: str
    note_path: str
    title: str
    body: str
    content_hash: str


def _extract_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _resolve_and_validate(
    note_path_raw: str,
    vault_root: Path,
) -> Path:
    """Resolve note path and reject traversal or outside-vault paths."""
    candidate = Path(note_path_raw)

    # Reject explicit traversal components before any resolution
    if ".." in candidate.parts:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_path", "note_path": note_path_raw, "reason": "path_traversal"},
        )

    if candidate.is_absolute():
        resolved = candidate
    else:
        # lgtm[py/path-injection]
        resolved = (vault_root / candidate).resolve()

    vault_resolved = vault_root.resolve()

    # Reject paths that escape the vault root
    try:
        resolved.relative_to(vault_resolved)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_path", "note_path": note_path_raw, "reason": "outside_vault"},
        )

    return resolved


@router.get("/note", response_model=ArtifactNoteResponse)
def read_artifact_note(
    note_path: str = Query(..., description="Vault-relative or absolute path to the note"),
    artifact_id: Optional[str] = Query(None, description="Artifact UUID; echoed back in response"),
) -> ArtifactNoteResponse:
    vault_root = resolve_vault_root()

    resolved = _resolve_and_validate(note_path, vault_root)

    # lgtm[py/path-injection]
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(
            status_code=404,
            detail={"error": "note_not_found", "note_path": note_path},
        )

    # lgtm[py/path-injection]
    body = resolved.read_text(encoding="utf-8")
    title = _extract_title(body, fallback=resolved.stem)

    return ArtifactNoteResponse(
        artifact_id=artifact_id or "",
        note_path=str(resolved),
        title=title,
        body=body,
        content_hash=_content_hash(body),
    )
