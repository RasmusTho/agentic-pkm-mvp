"""Read-only artifact note endpoint.

GET /api/artifacts/note?note_path=<path>[&artifact_id=<id>]

Returns a vault note's metadata and body without mutating it.
Rejects path traversal and paths outside the configured vault root.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.request_active_context import (
    current_scoped_route_read,
    route_read_vault_root_or_selection_required,
    scoped_note_path_owned_by_binding,
    scoped_route_read,
)
from app.text.helpers import content_hash, extract_title

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactNoteResponse(BaseModel):
    artifact_id: str
    note_path: str
    title: str
    body: str
    content_hash: str


# Private module-level aliases preserved for any same-module callers;
# cross-module consumers must import from app.text.helpers directly.
_extract_title = extract_title
_content_hash = content_hash


def _resolve_and_validate(
    note_path_raw: str,
    vault_root: Path,
) -> Path:
    """Resolve note path and reject traversal, absolute paths, or outside-vault paths.

    Only vault-relative paths are accepted. Absolute paths are rejected before any
    path construction occurs. The containment check uses os.path.realpath + startswith,
    which is the CodeQL-recognized sanitizer pattern for py/path-injection.
    """
    candidate = Path(note_path_raw)

    if candidate.is_absolute():
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_path", "note_path": note_path_raw, "reason": "absolute_path_not_allowed"},
        )

    # Reject explicit traversal components before any resolution
    if ".." in candidate.parts:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_path", "note_path": note_path_raw, "reason": "path_traversal"},
        )

    # os.path.realpath + startswith is the CodeQL-recognized path traversal sanitizer.
    vault_abs = os.path.realpath(str(vault_root))
    resolved_str = os.path.realpath(os.path.join(vault_abs, str(candidate)))
    vault_prefix = vault_abs + os.sep

    if not resolved_str.startswith(vault_prefix):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_path", "note_path": note_path_raw, "reason": "outside_vault"},
        )

    return Path(resolved_str)


@router.get("/note", response_model=ArtifactNoteResponse)
@scoped_route_read
def read_artifact_note(
    note_path: str = Query(..., description="Vault-relative path to the note (absolute paths are rejected)"),
    artifact_id: Optional[str] = Query(None, description="Artifact UUID; echoed back in response"),
) -> ArtifactNoteResponse | JSONResponse:
    # MVR-05B3: a carrier-bearing request reads its own bound binding; only a
    # carrier-free request resolves the legacy process selection.
    vault_root = route_read_vault_root_or_selection_required(
        requested_note_path=note_path,
    )
    if isinstance(vault_root, JSONResponse):
        return vault_root

    resolved = _resolve_and_validate(note_path, vault_root)

    scoped = current_scoped_route_read()
    if scoped is not None and not scoped_note_path_owned_by_binding(scoped, resolved):
        # A note owned by an initialized nested child vault is not served through
        # the parent binding: not-found, as if the child subtree did not exist.
        raise HTTPException(
            status_code=404,
            detail={"error": "note_not_found", "note_path": note_path},
        )

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(
            status_code=404,
            detail={"error": "note_not_found", "note_path": note_path},
        )

    body = resolved.read_text(encoding="utf-8")
    title = _extract_title(body, fallback=resolved.stem)

    return ArtifactNoteResponse(
        artifact_id=artifact_id or "",
        note_path=str(resolved),
        title=title,
        body=body,
        content_hash=_content_hash(body),
    )
