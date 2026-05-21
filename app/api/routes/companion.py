"""Read-side Companion UI workspace aggregate endpoint."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.api.routes.artifacts import _content_hash, _extract_title
from app.config.paths import resolve_vault_root
from app.orientation.runtime import build_orientation_frame
from app.services.artifact_identity import resolve_note_artifact_identity
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

router = APIRouter(prefix="/companion", tags=["companion"])


class ArtifactState(BaseModel):
    artifact_id: str | None
    artifact_kind: str = "human_note"
    note_path: str
    title: str
    body: str
    content_hash: str
    identity_source: str = "unknown"
    identity_state: str = "unknown"
    companion_of: str | None = None
    owns_identity: bool = True


class RuntimeState(BaseModel):
    environment_label: str
    api_base_url_label: str
    trace_id: str
    reorient: dict[str, list[dict[str, str | bool]]] = Field(default_factory=dict)


class CanvasState(BaseModel):
    session_id: str | None
    session_state: str | None
    user_present: bool
    can_edit_body: bool
    recovery_needed: bool
    session_log_path: str | None
    undo_available: bool = False
    applied_edit_count: int = 0
    undone_edit_count: int = 0
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


def _find_workspace_note(vault_root: Path, safe_note_path: str) -> Path | None:
    for candidate in vault_root.rglob("*"):
        if not candidate.is_file():
            continue
        if _vault_relative(candidate, vault_root) == safe_note_path:
            return candidate
    return None


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
    applied_edits = getattr(canvas_module, "_edit_history", {}).get(session.session_id, [])
    undone_edits = getattr(canvas_module, "_undone_history", {}).get(session.session_id, [])
    undo_available = _undo_available_for_session(session=session, applied_edits=applied_edits)
    return CanvasState(
        session_id=session.session_id,
        session_state="active",
        user_present=canvas_enabled,
        can_edit_body=canvas_enabled,
        recovery_needed=False,
        session_log_path=log_path,
        undo_available=undo_available,
        applied_edit_count=len(applied_edits),
        undone_edit_count=len(undone_edits),
    )


def _undo_available_for_session(*, session: object, applied_edits: list[object]) -> bool:
    if not applied_edits:
        return False
    latest = applied_edits[-1]
    try:
        current_body = canvas_module._note_body(Path(session.note_path))
    except Exception:
        return False
    return current_body == getattr(latest, "body_after", None)


def _proposal_count_for_artifact(artifact_id: str | None) -> int:
    if artifact_id is None:
        return 0
    proposals = getattr(confirm_module._proposal_store, "_proposals", {})
    return sum(1 for proposal in proposals.values() if proposal.artifact_id == artifact_id)


def _panel_state(artifact_id: str | None) -> PanelState:
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


def _reorient_state() -> dict[str, list[dict[str, str | bool]]]:
    def item(
        label: str,
        *,
        source_link: str = "runtime:orientation",
        panel_handoff: bool = False,
    ) -> dict[str, str | bool]:
        return {
            "label": label,
            "source_link": source_link,
            "panel_handoff": panel_handoff,
        }

    try:
        frame = build_orientation_frame()
    except Exception:
        return {
            "facts": [],
            "inferences": [],
            "candidates": [],
            "stale_context": [
                item(
                    "Orientation runtime unavailable; Reorient metadata is degraded.",
                    source_link="runtime:orientation#unavailable",
                )
            ],
            "recent_deltas": [],
            "open_loops": [],
        }

    open_loops = [
        item(loop, panel_handoff=not loop.startswith("No unresolved"))
        for loop in frame.explanation.open_items
    ]
    candidates = [
        item(intent, panel_handoff=True)
        for intent in frame.mutation_intents
    ]
    if not candidates:
        candidates = [
            item(
                "No direct action candidate is staged by the orientation runtime.",
                panel_handoff=False,
            )
        ]
    return {
        "facts": [
            item(frame.explanation.leave_point),
        ],
        "inferences": [
            item(frame.frame),
        ],
        "candidates": candidates,
        "stale_context": [
            item(
                "No stale context marker is present in the current orientation runtime snapshot.",
            )
        ],
        "recent_deltas": [
            item(frame.explanation.notable_change),
        ],
        "open_loops": open_loops,
    }


@router.get("/workspace", response_model=WorkspaceStateResponse)
def read_companion_workspace(
    note_path: str = Query(..., description="Runtime-relative note path"),
) -> WorkspaceStateResponse:
    trace_id = uuid4().hex
    safe_note_path = _validate_workspace_note_path(note_path)
    vault_root = resolve_vault_root()
    artifact_path = _find_workspace_note(vault_root, safe_note_path)
    if artifact_path is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "note_not_found",
                "message": "No note exists for the requested note_path",
                "note_path": safe_note_path,
                "trace_id": trace_id,
            },
        )

    body = artifact_path.read_text(encoding="utf-8")
    identity = resolve_note_artifact_identity(
        artifact_path=artifact_path,
        vault_root=vault_root,
        safe_note_path=safe_note_path,
        body=body,
    )
    if identity.identity_state == "healed":
        body = artifact_path.read_text(encoding="utf-8")
    canvas_enabled = _truthy_env("CANVAS_ENABLED")
    writeguard_status = _writeguard_status()

    return WorkspaceStateResponse(
        artifact=ArtifactState(
            artifact_id=identity.artifact_id,
            artifact_kind=identity.artifact_kind,
            note_path=safe_note_path,
            title=_extract_title(body, fallback=artifact_path.stem),
            body=body,
            content_hash=_content_hash(body),
            identity_source=identity.identity_source,
            identity_state=identity.identity_state,
            companion_of=identity.companion_of,
            owns_identity=identity.owns_identity,
        ),
        runtime=RuntimeState(
            environment_label=_safe_environment_label(),
            api_base_url_label=_safe_api_label(),
            trace_id=trace_id,
            reorient=_reorient_state(),
        ),
        canvas=_canvas_state(safe_note_path, vault_root, canvas_enabled),
        panel=_panel_state(identity.artifact_id),
        suggestions=SuggestionsState(),
        guards=GuardState(
            canvas_enabled=canvas_enabled,
            writeguard_status=writeguard_status,
            degraded=not canvas_enabled or writeguard_status == "unknown",
        ),
    )


__all__ = ["router"]
