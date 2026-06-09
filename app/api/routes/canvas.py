"""Canvas Chat session API routes.

POST   /api/canvas/sessions                  — open session, return session_id
POST   /api/canvas/sessions/{id}/edits       — apply body edit
POST   /api/canvas/sessions/{id}/governance  — submit governance action
DELETE /api/canvas/sessions/{id}/edits/last  — undo last body edit
DELETE /api/canvas/sessions/{id}             — close session

Gated by CANVAS_ENABLED env var (must be "1" or truthy to enable; default off).
All session state is in-memory for the lifetime of the API process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.routes.artifacts import _content_hash
from app.services.artifact_identity import resolve_note_artifact_identity
from app.chat.canvas_writer import CanvasWriter, GovernanceBearingMutationError, _split_frontmatter
from app.chat.coauthoring_cognition import CoAuthoringCognition, CoAuthoringUnavailableError
from app.chat.governance_router import GovernanceActionType, GovernanceRouter
from app.chat.intent_classifier import IntentClass, IntentClassifierCognition
from app.chat.session_log import SessionLog, SessionLogWriter
from app.config.paths import resolve_vault_root
from app.reasoning.facade import ReasoningFacade, get_reasoning_facade
from app.orientation.leave_point_cursor import capture_leave_point_cursor
from app.panel.canvas_pipeline import CanvasPanelPipeline
from app.panel.confirmation import _proposal_store as _panel_proposal_store

router = APIRouter(prefix="/canvas", tags=["canvas"])

# In-memory session registry — process lifetime only.
_sessions: dict[str, SessionLog] = {}


@dataclass(frozen=True)
class _AppliedBodyEdit:
    edit_id: str
    body_before: str
    body_after: str
    change_summary: str


_edit_history: dict[str, list[_AppliedBodyEdit]] = {}
_undone_history: dict[str, list[_AppliedBodyEdit]] = {}


def _canvas_enabled() -> bool:
    return os.getenv("CANVAS_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


def _require_canvas() -> None:
    if not _canvas_enabled():
        raise HTTPException(status_code=403, detail="Canvas surface is disabled (CANVAS_ENABLED=0)")


def _get_vault_root() -> Path:
    return resolve_vault_root().expanduser().resolve()


def _coauthor_facade_factory() -> ReasoningFacade:
    """Reasoning facade used by the co-authoring cognition.

    Indirected through a module-level function so tests can substitute a
    deterministic stub without a live LLM provider.
    """
    return get_reasoning_facade()


def _intent_classifier_facade_factory() -> ReasoningFacade:
    """Reasoning facade used by the intent classifier cognition.

    Indirected through a module-level function (mirroring
    ``_coauthor_facade_factory``) so tests can substitute a deterministic stub
    without a live LLM provider.
    """
    return get_reasoning_facade()


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
    content_hash: str | None = None


class EditResponse(BaseModel):
    session_id: str
    ok: bool


class CoAuthorRequest(BaseModel):
    intent: str
    change_summary: str | None = None


class CoAuthorResponse(BaseModel):
    session_id: str
    applied_body: str
    change_summary: str
    generated: bool


class ExploratoryNoEditResponse(BaseModel):
    """Read-only response for an exploratory intent.

    Exploratory intent does not itself authorize durable mutation
    (HYBRID_CHAT_INTEGRATION_SCHEMA :: Intent Classes): no body is generated,
    nothing is written, and the note is left unchanged.
    """

    status: Literal["exploratory_no_edit"] = "exploratory_no_edit"
    session_id: str
    detail: str = (
        "Exploratory intent — read-only; no edit generated and the note body "
        "was left unchanged."
    )


class UndoResponse(BaseModel):
    session_id: str
    ok: bool
    undo_id: str
    original_edit_id: str


class GovernanceRequest(BaseModel):
    action_type: str
    payload: dict[str, Any] = {}


class GovernanceHandoffRef(BaseModel):
    """Structured reference returned when a canvas intent is routed to the Panel.

    Surfaces the staged Panel intent so the UI can correlate the canvas
    co-authoring intent with the Panel proposal it produced. The note is never
    mutated on this path — execution stays in the gated Panel pipeline.
    """

    status: Literal["routed_to_panel"] = "routed_to_panel"
    intent_id: str
    action_type: str
    detail: str = (
        "Governance-bearing — routed to the gated Panel pipeline; "
        "note body left unchanged."
    )


class GovernanceResponse(BaseModel):
    intent_id: str
    session_id: str
    artifact_id: str
    action_type: str
    status: Literal["routed_to_panel"] = "routed_to_panel"


class CloseResponse(BaseModel):
    session_id: str
    log_path: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _validate_note_path(note_path_str: str, vault_root: Path) -> Path:
    """Validate and resolve note path to be within vault_root.

    Rejects absolute paths; only relative paths are accepted.
    """
    if not note_path_str:
        raise ValueError("note_path cannot be empty")
    if Path(note_path_str).is_absolute():
        raise ValueError("note_path must be relative to vault_root")
    candidate = (vault_root / note_path_str).resolve()
    try:
        candidate.relative_to(vault_root)
    except ValueError:
        raise ValueError("note_path escapes vault_root")
    return candidate


def _note_body(note_path: Path) -> str:
    content = note_path.read_text(encoding="utf-8")
    _, body = _split_frontmatter(content)
    return body


def _runtime_channel() -> str:
    raw = (
        os.getenv("PKM_ENVIRONMENT")
        or os.getenv("CHANNEL")
        or os.getenv("PKM_CHANNEL")
        or ""
    ).strip().lower()
    return raw if raw in {"dev", "test", "prod"} else "unknown"


def _runtime_vault_id(vault_root: Path) -> str:
    try:
        from app.settings.runtime import get_settings_bundle

        bundle = get_settings_bundle()
        configured = getattr(getattr(getattr(bundle, "instance", None), "vault", None), "name", None)
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
    except Exception:
        pass
    return vault_root.name or "default"


def _capture_leave_point_for_session(
    session: SessionLog,
    *,
    source_kind: Literal["artifact_activation", "canvas_session", "session_end"],
    capture_reason: Literal["artifact_focus", "artifact_interaction", "session_end"],
) -> None:
    vault_root = _get_vault_root()
    try:
        safe_note_path = str(session.note_path.relative_to(vault_root))
        identity = resolve_note_artifact_identity(
            artifact_path=session.note_path,
            vault_root=vault_root,
            safe_note_path=safe_note_path,
            body=session.note_path.read_text(encoding="utf-8"),
            heal_missing_uuid=False,
        )
        if identity.artifact_id is None:
            return
        capture_leave_point_cursor(
            vault_id=_runtime_vault_id(vault_root),
            channel=_runtime_channel(),
            artifact_uuid=identity.artifact_id,
            source_kind=source_kind,
            source_ref_id=safe_note_path,
            capture_reason=capture_reason,
            last_session_id=session.session_id,
            content_hash_at_capture=_content_hash(session.note_path.read_text(encoding="utf-8")),
        )
    except Exception:
        return


@router.post("/sessions", response_model=OpenSessionResponse)
def open_session(req: OpenSessionRequest) -> OpenSessionResponse:
    _require_canvas()
    vault_root = _get_vault_root()
    try:
        note_path = _validate_note_path(req.note_path, vault_root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_writer = SessionLogWriter(vault_root=vault_root)
    session = log_writer.open_session(note_path, req.label)
    _sessions[session.session_id] = session
    _edit_history[session.session_id] = []
    _undone_history[session.session_id] = []
    _capture_leave_point_for_session(
        session,
        source_kind="artifact_activation",
        capture_reason="artifact_focus",
    )
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
    if req.content_hash is not None:
        current_hash = _content_hash(session.note_path.read_text(encoding="utf-8"))
        if current_hash != req.content_hash:
            raise HTTPException(status_code=409, detail="content_hash mismatch")
    body_before = _note_body(session.note_path)
    vault_root = _get_vault_root()
    log_writer = SessionLogWriter(vault_root=vault_root)
    writer = CanvasWriter(vault_root=vault_root, log_writer=log_writer)
    try:
        writer.apply_edit(session, req.new_body, req.change_summary)
    except GovernanceBearingMutationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    body_after = _note_body(session.note_path)
    _edit_history.setdefault(session_id, []).append(
        _AppliedBodyEdit(
            edit_id=str(uuid4()),
            body_before=body_before,
            body_after=body_after,
            change_summary=req.change_summary,
        )
    )
    _capture_leave_point_for_session(
        session,
        source_kind="canvas_session",
        capture_reason="artifact_interaction",
    )
    return EditResponse(session_id=session_id, ok=True)


def _route_governance_bearing(
    session: SessionLog,
    vault_root: Path,
    *,
    action_type: GovernanceActionType = GovernanceActionType.FRONTMATTER_UPDATE,
) -> GovernanceHandoffRef:
    """Route a governance-bearing co-authoring intent to the Panel pipeline.

    Used when the classified *intent* is governance-bearing (passing the
    classified ``action_type``) or when the generated body carries frontmatter
    — the body-frontmatter defense-in-depth backstop, which keeps the default
    ``FRONTMATTER_UPDATE``. The note is never mutated here; an intent is
    queued through ``GovernanceRouter`` so the gated Panel admission path owns
    execution.

    Returns a :class:`GovernanceHandoffRef` carrying the staged Panel
    ``intent_id`` and ``action_type`` so the caller can surface a structured
    handoff reference (a 409 with this body). Raises ``HTTPException(409)``
    only when the note artifact identity is unresolved and no Panel proposal
    could be staged.
    """
    log_writer = SessionLogWriter(vault_root=vault_root)
    safe_note_path = str(session.note_path.relative_to(vault_root))
    identity = resolve_note_artifact_identity(
        artifact_path=session.note_path,
        vault_root=vault_root,
        safe_note_path=safe_note_path,
    )
    if identity.artifact_id is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Co-authoring generation is governance-bearing — routed to the "
                "gated governance pipeline; note body left unchanged."
            ),
        )
    pipeline = CanvasPanelPipeline(
        proposal_store=_panel_proposal_store,
        artifact_id=identity.artifact_id,
        note_path=safe_note_path,
    )
    gov = GovernanceRouter(panel_pipeline=pipeline, session_log_writer=log_writer)
    pending = gov.request_governance_action(session, action_type, {})
    return GovernanceHandoffRef(
        intent_id=pending.intent_id,
        action_type=pending.action_type.value,
    )


def _handoff_response(ref: GovernanceHandoffRef) -> JSONResponse:
    """Render a governance handoff reference as a structured 409 body."""
    return JSONResponse(status_code=409, content=ref.model_dump())


@router.post("/sessions/{session_id}/coauthor", response_model=CoAuthorResponse)
def coauthor(session_id: str, req: CoAuthorRequest) -> CoAuthorResponse | JSONResponse:
    _require_canvas()
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    vault_root = _get_vault_root()
    current_body = _note_body(session.note_path)

    # Classify the *intent* first — before and independent of body generation
    # (ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR). A confident governance-bearing
    # intent routes to the gated Panel pipeline with the classified action
    # type; a confident exploratory intent is read-only. A degraded classifier
    # (classified=False) falls through to the existing generate path so an
    # unavailable backend never fabricates a routing.
    classifier = IntentClassifierCognition(
        facade_factory=_intent_classifier_facade_factory
    )
    classification = classifier.classify(intent=req.intent, current_body=current_body)
    if classification.classified:
        if classification.intent_class is IntentClass.GOVERNANCE_BEARING:
            # No body is generated or applied on the governance path.
            return _handoff_response(
                _route_governance_bearing(
                    session,
                    vault_root,
                    action_type=classification.action_type
                    or GovernanceActionType.FRONTMATTER_UPDATE,
                )
            )
        if classification.intent_class is IntentClass.EXPLORATORY:
            # Non-mutating: no generation, no write; note body unchanged.
            return JSONResponse(
                status_code=200,
                content=ExploratoryNoEditResponse(session_id=session_id).model_dump(),
            )

    cognition = CoAuthoringCognition(facade_factory=_coauthor_facade_factory)
    try:
        generated = cognition.generate_body(
            intent=req.intent,
            current_body=current_body,
        )
    except GovernanceBearingMutationError:
        # Generation produced a frontmatter/governance-bearing body: do not
        # apply in place; route through the gated pipeline and return a
        # structured handoff reference (409).
        return _handoff_response(_route_governance_bearing(session, vault_root))
    except CoAuthoringUnavailableError as exc:
        # No edit-capable provider produced a usable body (mock/degraded
        # backend or failed run). Leave the note unchanged; do not write
        # diagnostic text into the body.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    change_summary = req.change_summary or f"co-authored: {req.intent.strip()}"
    body_before = current_body
    log_writer = SessionLogWriter(vault_root=vault_root)
    writer = CanvasWriter(vault_root=vault_root, log_writer=log_writer)
    # Record the user's intent as provenance in the session log.
    log_writer.append_turn(session, user_prompt=req.intent, change_summary=change_summary)
    try:
        writer.apply_edit(session, generated.body, change_summary)
    except GovernanceBearingMutationError:
        # Defense in depth: the writer caught a governance-bearing body the
        # cognition let through. Route it rather than applying in place.
        return _handoff_response(_route_governance_bearing(session, vault_root))

    body_after = _note_body(session.note_path)
    _edit_history.setdefault(session_id, []).append(
        _AppliedBodyEdit(
            edit_id=str(uuid4()),
            body_before=body_before,
            body_after=body_after,
            change_summary=change_summary,
        )
    )
    _capture_leave_point_for_session(
        session,
        source_kind="canvas_session",
        capture_reason="artifact_interaction",
    )
    return CoAuthorResponse(
        session_id=session_id,
        applied_body=body_after,
        change_summary=change_summary,
        generated=generated.generated,
    )


@router.delete("/sessions/{session_id}/edits/last", response_model=UndoResponse)
def undo_last_edit(session_id: str) -> UndoResponse:
    _require_canvas()
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    edits = _edit_history.setdefault(session_id, [])
    if not edits:
        raise HTTPException(status_code=409, detail="No undoable Canvas body edit")

    latest = edits[-1]
    current_body = _note_body(session.note_path)
    if current_body != latest.body_after:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot undo last Canvas body edit: note body has diverged since "
                "the assistant edit was applied"
            ),
        )

    vault_root = _get_vault_root()
    log_writer = SessionLogWriter(vault_root=vault_root)
    writer = CanvasWriter(vault_root=vault_root, log_writer=log_writer)
    undo_id = str(uuid4())
    try:
        writer.apply_edit(
            session,
            latest.body_before,
            f"[undo:{undo_id}] reverted edit:{latest.edit_id}",
        )
    except GovernanceBearingMutationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    edits.pop()
    _undone_history.setdefault(session_id, []).append(latest)
    return UndoResponse(
        session_id=session_id,
        ok=True,
        undo_id=undo_id,
        original_edit_id=latest.edit_id,
    )


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
    safe_note_path = str(session.note_path.relative_to(vault_root))
    identity = resolve_note_artifact_identity(
        artifact_path=session.note_path,
        vault_root=vault_root,
        safe_note_path=safe_note_path,
    )
    if identity.artifact_id is None:
        raise HTTPException(status_code=409, detail="artifact identity unresolved")
    artifact_id = identity.artifact_id
    pipeline = CanvasPanelPipeline(
        proposal_store=_panel_proposal_store,
        artifact_id=artifact_id,
        note_path=safe_note_path,
    )
    gov = GovernanceRouter(panel_pipeline=pipeline, session_log_writer=log_writer)
    pending = gov.request_governance_action(session, action_type, req.payload)
    return GovernanceResponse(
        intent_id=pending.intent_id,
        session_id=pending.session_id,
        artifact_id=artifact_id,
        action_type=pending.action_type.value,
    )


@router.delete("/sessions/{session_id}", response_model=CloseResponse)
def close_session(session_id: str, total_summary: str = "session closed") -> CloseResponse:
    _require_canvas()
    session = _sessions.pop(session_id, None)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    _edit_history.pop(session_id, None)
    _undone_history.pop(session_id, None)
    vault_root = _get_vault_root()
    log_writer = SessionLogWriter(vault_root=vault_root)
    log_writer.close_session(session, total_summary)
    _capture_leave_point_for_session(
        session,
        source_kind="session_end",
        capture_reason="session_end",
    )
    return CloseResponse(session_id=session_id, log_path=str(session.log_path))


__all__ = ["router"]
