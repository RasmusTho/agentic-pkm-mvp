"""Read-side Companion UI workspace aggregate endpoint."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import yaml

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.api.routes.artifacts import _content_hash, read_artifact_note
from app.config.paths import resolve_vault_root
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

router = APIRouter(prefix="/companion", tags=["companion"])


class ArtifactState(BaseModel):
    artifact_id: str
    note_path: str
    title: str
    body: str
    content_hash: str


class RuntimeState(BaseModel):
    environment_label: str
    api_base_url_label: str
    trace_id: str


class CanvasState(BaseModel):
    session_id: str | None
    session_state: str | None
    user_present: bool
    can_edit_body: bool
    recovery_needed: bool
    session_log_path: str | None
    session_persistence: str = "in_memory"


class PanelState(BaseModel):
    state: str
    proposal_count: int
    receipt_count: int
    latest_receipt_outcome: str | None
    blocked_reason: str | None
    no_match_reason: str | None


class SuggestionsState(BaseModel):
    current_suggestion_state: str | None = None
    server_declared_classification: str | None = None
    pending_receipts: list[dict[str, str]] = Field(default_factory=list)


class GuardState(BaseModel):
    canvas_enabled: bool
    writeguard_status: str
    degraded: bool


class WorkspaceStateResponse(BaseModel):
    artifact: ArtifactState
    runtime: RuntimeState
    canvas: CanvasState
    panel: PanelState
    suggestions: SuggestionsState
    guards: GuardState


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _safe_environment_label() -> str:
    raw = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    if raw in {"dev", "test", "prod"}:
        return raw
    return "unknown"


def _safe_api_label() -> str:
    return (os.getenv("COMPANION_API_BASE_URL_LABEL") or "local-dev").strip() or "local-dev"


def _validate_workspace_note_path(note_path_raw: str) -> str:
    candidate = PurePosixPath(note_path_raw)
    if (
        not note_path_raw
        or note_path_raw.startswith("/")
        or ".." in candidate.parts
        or candidate.as_posix() in {"", "."}
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_note_path",
                "message": "note_path must be a relative runtime note path",
                "trace_id": uuid4().hex,
            },
        )
    return candidate.as_posix()


def _frontmatter_artifact_id(body: str) -> str | None:
    if not body.startswith("---\n"):
        return None
    _, remainder = body.split("---\n", 1)
    if "\n---" not in remainder:
        return None
    frontmatter_raw, _ = remainder.split("\n---", 1)
    try:
        loaded = yaml.safe_load(frontmatter_raw) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(loaded, dict):
        return None
    value = loaded.get("uuid") or loaded.get("id")
    if value is None:
        return None
    artifact_id = str(value).strip()
    return artifact_id or None


def _vault_relative(path: Path, vault_root: Path) -> str | None:
    try:
        return path.relative_to(vault_root).as_posix()
    except ValueError:
        return None


def _active_canvas_session(safe_note_path: str, vault_root: Path) -> object | None:
    for session in canvas_module._sessions.values():
        session_note_path = _vault_relative(Path(session.note_path), vault_root)
        if session_note_path == safe_note_path:
            return session
    return None


def _canvas_state(safe_note_path: str, vault_root: Path, canvas_enabled: bool) -> CanvasState:
    session = _active_canvas_session(safe_note_path, vault_root)
    if session is None:
        return CanvasState(
            session_id=None,
            session_state=None,
            user_present=False,
            can_edit_body=False,
            recovery_needed=False,
            session_log_path=None,
        )

    log_path = _vault_relative(Path(session.log_path), vault_root)
    return CanvasState(
        session_id=session.session_id,
        session_state="active",
        user_present=canvas_enabled,
        can_edit_body=canvas_enabled,
        recovery_needed=False,
        session_log_path=log_path,
    )


def _proposal_count_for_artifact(artifact_id: str) -> int:
    proposals = getattr(confirm_module._proposal_store, "_proposals", {})
    return sum(1 for proposal in proposals.values() if proposal.artifact_id == artifact_id)


def _panel_state(artifact_id: str) -> PanelState:
    proposal_count = _proposal_count_for_artifact(artifact_id)
    cache = getattr(confirm_module._idempotency_store, "_cache", {})
    relevant = [resp for resp in cache.values() if resp.artifact_id == artifact_id]
    latest = relevant[-1] if relevant else None
    blocked_reason = None
    latest_outcome = None
    if latest is not None:
        latest_outcome = latest.outcome
        if latest.block_reason is not None:
            blocked_reason = latest.block_reason.message
    if blocked_reason:
        state = "blocked"
    elif proposal_count:
        state = "proposals-staged"
    elif latest_outcome == "success":
        state = "receipt-displayed"
    else:
        state = "idle"
    return PanelState(
        state=state,
        proposal_count=proposal_count,
        receipt_count=len(relevant),
        latest_receipt_outcome=latest_outcome,
        blocked_reason=blocked_reason,
        no_match_reason=None,
    )


def _writeguard_status() -> str:
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("companion.workspace.read")
    except WritesBlockedError:
        return "blocked"
    except Exception:
        return "unknown"
    return "ok"


@router.get("/workspace", response_model=WorkspaceStateResponse)
def read_companion_workspace(
    note_path: str = Query(..., description="Runtime-relative note path"),
) -> WorkspaceStateResponse:
    trace_id = uuid4().hex
    safe_note_path = _validate_workspace_note_path(note_path)
    vault_root = resolve_vault_root()
    try:
        artifact = read_artifact_note(note_path=safe_note_path, artifact_id="")
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "note_not_found",
                    "message": "No note exists for the requested note_path",
                    "note_path": safe_note_path,
                    "trace_id": trace_id,
                },
            ) from exc
        raise

    body = artifact.body
    artifact_id = _frontmatter_artifact_id(body) or _content_hash(safe_note_path)
    canvas_enabled = _truthy_env("CANVAS_ENABLED")
    writeguard_status = _writeguard_status()

    return WorkspaceStateResponse(
        artifact=ArtifactState(
            artifact_id=artifact_id,
            note_path=safe_note_path,
            title=artifact.title,
            body=body,
            content_hash=artifact.content_hash,
        ),
        runtime=RuntimeState(
            environment_label=_safe_environment_label(),
            api_base_url_label=_safe_api_label(),
            trace_id=trace_id,
        ),
        canvas=_canvas_state(safe_note_path, vault_root, canvas_enabled),
        panel=_panel_state(artifact_id),
        suggestions=SuggestionsState(),
        guards=GuardState(
            canvas_enabled=canvas_enabled,
            writeguard_status=writeguard_status,
            degraded=not canvas_enabled or writeguard_status == "unknown",
        ),
    )


__all__ = ["router"]
