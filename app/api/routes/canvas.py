"""Canvas Chat session API routes.

POST   /api/canvas/sessions                  — open session, return session_id
POST   /api/canvas/sessions/{id}/edits       — apply body edit
POST   /api/canvas/sessions/{id}/governance  — submit governance action
DELETE /api/canvas/sessions/{id}             — close session

Gated by CANVAS_ENABLED env var (must be "1" or truthy to enable; default off).
All session state is in-memory for the lifetime of the API process.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.chat.canvas_writer import CanvasWriter, GovernanceBearingMutationError
from app.chat.governance_router import GovernanceActionType, GovernanceRouter
from app.chat.session_log import SessionLog, SessionLogWriter
from app.config.paths import resolve_vault_root

router = APIRouter(prefix="/canvas", tags=["canvas"])

# In-memory session registry — process lifetime only.
_sessions: dict[str, SessionLog] = {}


def _canvas_enabled() -> bool:
    return os.getenv("CANVAS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _require_canvas() -> None:
    if not _canvas_enabled():
        raise HTTPException(status_code=403, detail="Canvas surface is disabled (CANVAS_ENABLED=0)")


def _get_vault_root() -> Path:
    return resolve_vault_root().expanduser().resolve()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class OpenSessionRequest(BaseModel):
    note_path: str
    label: str = "canvas-session"


class OpenSessionResponse(BaseModel):
    session_id: str
    note_path: str
    log_path: str


class EditRequest(BaseModel):
    new_body: str
    change_summary: str


class EditResponse(BaseModel):
    session_id: str
    ok: bool


class GovernanceRequest(BaseModel):
    action_type: str
    payload: dict[str, Any] = {}


class GovernanceResponse(BaseModel):
    intent_id: str
    session_id: str


class CloseResponse(BaseModel):
    session_id: str
    log_path: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/sessions", response_model=OpenSessionResponse)
def open_session(req: OpenSessionRequest) -> OpenSessionResponse:
    _require_canvas()
    vault_root = _get_vault_root()
    log_writer = SessionLogWriter(vault_root=vault_root)
    note_path = Path(req.note_path).expanduser()
    if not note_path.is_absolute():
        note_path = vault_root / note_path
    note_path = note_path.resolve()
    session = log_writer.open_session(note_path, req.label)
    _sessions[session.session_id] = session
    return OpenSessionResponse(
        session_id=session.session_id,
        note_path=str(session.note_path),
        log_path=str(session.log_path),
    )


@router.post("/sessions/{session_id}/edits", response_model=EditResponse)
def apply_edit(session_id: str, req: EditRequest) -> EditResponse:
    _require_canvas()
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    vault_root = _get_vault_root()
    log_writer = SessionLogWriter(vault_root=vault_root)
    writer = CanvasWriter(vault_root=vault_root, log_writer=log_writer)
    try:
        writer.apply_edit(session, req.new_body, req.change_summary)
    except GovernanceBearingMutationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return EditResponse(session_id=session_id, ok=True)


@router.post("/sessions/{session_id}/governance", response_model=GovernanceResponse)
def governance_action(session_id: str, req: GovernanceRequest) -> GovernanceResponse:
    _require_canvas()
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    try:
        action_type = GovernanceActionType(req.action_type)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown action_type: {req.action_type!r}")
    vault_root = _get_vault_root()
    log_writer = SessionLogWriter(vault_root=vault_root)

    class _NullPipeline:
        def submit_intent(self, action_type: str, payload: dict, session_id: str) -> str:
            import uuid
            return str(uuid.uuid4())

    gov = GovernanceRouter(panel_pipeline=_NullPipeline(), session_log_writer=log_writer)
    pending = gov.request_governance_action(session, action_type, req.payload)
    return GovernanceResponse(intent_id=pending.intent_id, session_id=pending.session_id)


@router.delete("/sessions/{session_id}", response_model=CloseResponse)
def close_session(session_id: str, total_summary: str = "session closed") -> CloseResponse:
    _require_canvas()
    session = _sessions.pop(session_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    vault_root = _get_vault_root()
    log_writer = SessionLogWriter(vault_root=vault_root)
    log_writer.close_session(session, total_summary)
    return CloseResponse(session_id=session_id, log_path=str(session.log_path))


__all__ = ["router"]
