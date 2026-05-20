"""Minimal real-note workspace dev/staging page (#1072).

DEV/STAGING ONLY — this is not a production UI contract.

Provides a thin page model that:
- accepts a NoteLoadIntent (note_path) from the user
- loads GET /api/companion/workspace via the live HTTP client
- renders the payload through the read-only workspace shell
- exposes a secondary Panel/agent rail placeholder

Environment contract:
  The dev page reads from whichever vault is bound to the configured
  runtime API. It does not know or choose the vault directly.
  - dev runtime → dev-bound vault (e.g. Nifelheim)
  - test runtime → test-bound vault (e.g. Bifröst)
  - prod runtime → prod-bound vault (e.g. Midgård)
  Named vault examples are environment binding illustrations only;
  they must not be hardcoded into UI logic.

Network access:
  Bind the dev server to 127.0.0.1 by default.
  Set HOST=0.0.0.0 (or equivalent) only for explicit LAN/Tailscale use.
  Do not expose this page publicly.

This module does NOT:
- read or write vault files directly
- choose or configure the active vault
- implement auth/TLS/reverse proxy
- implement proposal generation or Canvas body-edit
- make decisions based on vault names or environment names
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import uuid4

from companion_ui.canvas_suggestion_flow.suggested_insertion import (
    SuggestedInsertion,
)
from companion_ui.canvas_suggestion_flow.rail_state_machine import (
    CanvasRailStateMachine,
    RAIL_STATES,
)
from companion_ui.canvas_suggestion_flow.suggestion_card import SuggestionCard
from companion_ui.panel.proposal_row import ProposalEvidence, ProposalRow
from companion_ui.panel.render_model import PanelRenderState, render_panel_state
from companion_ui.workspace.real_note_workspace_shell import (
    ArtifactNotePayload,
    RealNoteWorkspaceShell,
)
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientError,
    WorkspaceHttpClient,
)

# ---------------------------------------------------------------------------
# Dev/staging marker — this is not a production UI contract
# ---------------------------------------------------------------------------

IS_PRODUCTION_UI: bool = False
DEV_PAGE_LABEL: str = "dev/staging — not a production UI contract"


# ---------------------------------------------------------------------------
# Note load intent
# ---------------------------------------------------------------------------


@dataclass
class NoteLoadIntent:
    """Represents the operator's intent to load a specific note by path.

    note_path is forwarded to the runtime API as a query parameter.
    The UI does not resolve vault paths or access vault files directly.
    The runtime API is bound to an environment; it determines which vault
    is read.
    """

    note_path: str
    artifact_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Page state
# ---------------------------------------------------------------------------


@dataclass
class DevPageState:
    """Current render state for the dev/staging workspace page."""

    shell: Optional[RealNoteWorkspaceShell] = None
    error: Optional[str] = None
    panel_rail_placeholder: str = "Panel / agent rail — placeholder (dev)"
    canvas_session_id: str | None = None
    canvas_session_state: str = "idle"
    canvas_user_present: bool = False
    canvas_can_edit_body: bool = False
    canvas_runtime_can_edit_body: bool = False
    canvas_recovery_needed: bool = False
    canvas_recovery_acknowledged: bool = False
    canvas_conflict_detected: bool = False
    canvas_session_log_path: str | None = None
    canvas_undo_available: bool = False
    canvas_applied_edit_count: int = 0
    canvas_undone_edit_count: int = 0
    canvas_session_persistence: str = ""
    panel_state: str = "idle"
    panel_proposal_count: int = 0
    panel_render: dict[str, Any] | None = None
    panel_proposals: list[dict[str, Any]] | None = None
    panel_last_response: dict[str, Any] | None = None
    suggestion_state: str = "idle"
    suggestion_dom_alias: str = "idle"
    suggestion_allowed_transitions: list[str] | None = None
    suggestion_composer_enabled: bool = True
    suggestion_cards: list[dict[str, Any]] | None = None
    suggested_insertions: list[dict[str, Any]] | None = None
    guard_writeguard_status: str = "ok"
    guard_canvas_enabled: bool = True
    is_loaded: bool = False


# ---------------------------------------------------------------------------
# Dev page model
# ---------------------------------------------------------------------------


class RealNoteWorkspaceDevPage:
    """Minimal dev/staging page for real-note workspace.

    Loads a note through the runtime API and renders it via the
    read-only workspace shell. Does not access vault files directly.

    Usage (dev runtime on port 18001):
        client = WorkspaceHttpClient("http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        state = page.load(NoteLoadIntent(note_path="Notes/example.md"))
        fields = page.render_fields()

    To target a different environment, pass a different base_url.
    The runtime owns environment and vault binding.
    """

    is_production_ui: bool = IS_PRODUCTION_UI
    dev_page_label: str = DEV_PAGE_LABEL

    def __init__(self, http_client: WorkspaceHttpClient) -> None:
        self._http = http_client
        self.state: DevPageState = DevPageState()
        self._last_content_hash_by_note: dict[str, str] = {}
        self._acknowledged_recovery_tokens: set[tuple[str, str, str, str]] = set()
        self._trusted_hash_refresh_notes: set[str] = set()

    def load(self, intent: NoteLoadIntent) -> DevPageState:
        """Load a note via the runtime API.

        Calls GET /api/companion/workspace through the injected client.
        The runtime API determines which vault is read; the page does
        not choose or inspect vault files.
        """
        params: dict = {"note_path": intent.note_path}

        try:
            raw = self._http.get("/api/companion/workspace", params=params)
        except WorkspaceClientError as exc:
            self._trusted_hash_refresh_notes.discard(intent.note_path)
            self.state = DevPageState(error=str(exc))
            return self.state

        artifact = raw.get("artifact") or {}
        canvas = raw.get("canvas") or {}
        panel = raw.get("panel") or {}
        suggestions = raw.get("suggestions") or {}
        guards = raw.get("guards") or {}

        # The runtime echoes artifact_id only when supplied in the request.
        # Fall back to note_path so note-path-only loads don't fail the shell's
        # non-empty artifact_id invariant.
        resolved_note_path = artifact.get("note_path") or intent.note_path
        resolved_artifact_id = (
            artifact.get("artifact_id")
            or intent.artifact_id
            or resolved_note_path
        )
        payload = ArtifactNotePayload(
            artifact_id=resolved_artifact_id,
            note_path=resolved_note_path,
            title=artifact.get("title", ""),
            body=artifact.get("body", ""),
            content_hash=artifact.get("content_hash", ""),
        )
        content_hash = payload.content_hash
        previous_hash = self._last_content_hash_by_note.get(resolved_note_path)
        session_state = canvas.get("session_state") or "idle"
        recovery_needed = bool(canvas.get("recovery_needed", False))
        recovery_token = _recovery_token(
            note_path=resolved_note_path,
            session_id=canvas.get("session_id"),
            session_state=session_state,
            content_hash=content_hash,
        )
        recovery_acknowledged = recovery_token in self._acknowledged_recovery_tokens
        hash_conflict = (
            previous_hash is not None
            and bool(content_hash)
            and previous_hash != content_hash
            and resolved_note_path not in self._trusted_hash_refresh_notes
        )
        self._trusted_hash_refresh_notes.discard(resolved_note_path)
        state_conflict = session_state in {"paused", "interrupted"}
        conflict_detected = recovery_needed or hash_conflict or state_conflict
        runtime_can_edit_body = bool(canvas.get("can_edit_body", False))
        can_edit_body = runtime_can_edit_body and (not conflict_detected or recovery_acknowledged)
        if content_hash:
            self._last_content_hash_by_note[resolved_note_path] = content_hash
        shell = RealNoteWorkspaceShell(payload=payload, agent_rail_state=None)
        panel_count = int(panel.get("proposal_count") or 0)
        panel_state = panel.get("state") or "idle"
        panel_message = _panel_message(panel)
        render_state = PanelRenderState(
            artifact_id=resolved_artifact_id,
            state=panel_state,
            message=panel_message,
            proposal_count=panel_count,
        )
        panel_render = render_panel_state(render_state)
        panel_proposals = _proposal_rows_from_panel(
            panel=panel,
            artifact_id=resolved_artifact_id,
        )
        suggestion_machine = CanvasRailStateMachine(
            _normalise_suggestion_state(suggestions.get("current_suggestion_state"))
        )
        panel_last_response = self.state.panel_last_response
        if panel_last_response and panel_last_response.get("artifact_id") != resolved_artifact_id:
            panel_last_response = None
        self.state = DevPageState(
            shell=shell,
            panel_rail_placeholder=panel_render.get("label", "Panel ready"),
            canvas_session_id=canvas.get("session_id"),
            canvas_session_state=session_state,
            canvas_user_present=bool(canvas.get("user_present", False)),
            canvas_runtime_can_edit_body=runtime_can_edit_body,
            canvas_can_edit_body=can_edit_body,
            canvas_recovery_needed=recovery_needed,
            canvas_recovery_acknowledged=recovery_acknowledged,
            canvas_conflict_detected=conflict_detected,
            canvas_session_log_path=canvas.get("session_log_path"),
            canvas_undo_available=bool(canvas.get("undo_available", False)),
            canvas_applied_edit_count=int(canvas.get("applied_edit_count") or 0),
            canvas_undone_edit_count=int(canvas.get("undone_edit_count") or 0),
            canvas_session_persistence=canvas.get("session_persistence") or "",
            panel_state=panel_state,
            panel_proposal_count=panel_count,
            panel_render=panel_render,
            panel_proposals=panel_proposals,
            panel_last_response=panel_last_response,
            suggestion_state=suggestion_machine.state,
            suggestion_dom_alias=suggestion_machine.dom_alias,
            suggestion_allowed_transitions=sorted(suggestion_machine.allowed_transitions()),
            suggestion_composer_enabled=suggestion_machine.composer_enabled,
            suggestion_cards=_suggestion_cards_from_payload(suggestions),
            suggested_insertions=_suggested_insertions_from_payload(suggestions),
            guard_writeguard_status=guards.get("writeguard_status") or "ok",
            guard_canvas_enabled=bool(guards.get("canvas_enabled", True)),
            is_loaded=True,
        )
        return self.state

    def open_canvas_session(self, intent: NoteLoadIntent) -> DevPageState:
        """Open a Canvas session through the runtime, then refresh workspace state."""
        try:
            self._http.post(
                "/api/canvas/sessions",
                json={"note_path": intent.note_path},
            )
        except WorkspaceClientError as exc:
            self.state = DevPageState(error=str(exc))
            return self.state
        return self.load(intent)

    def close_canvas_session(
        self,
        *,
        session_id: str,
        note_path: str,
    ) -> DevPageState:
        """Close a Canvas session through the runtime, then refresh workspace state."""
        try:
            self._http.delete(
                f"/api/canvas/sessions/{session_id}",
                params={"total_summary": "session closed from Companion UI"},
            )
        except WorkspaceClientError as exc:
            self.state = DevPageState(error=str(exc))
            return self.state
        return self.load(NoteLoadIntent(note_path=note_path))

    def apply_canvas_edit(
        self,
        *,
        session_id: str,
        note_path: str,
        new_body: str,
        change_summary: str,
        content_hash: str,
    ) -> DevPageState:
        """Apply a body-safe Canvas edit, then refresh workspace state."""
        if not self.state.canvas_can_edit_body:
            self.state.error = "Canvas body edit unavailable outside an active editable session"
            self.state.is_loaded = False
            return self.state
        try:
            self._http.post(
                f"/api/canvas/sessions/{session_id}/edits",
                json={
                    "new_body": new_body,
                    "change_summary": change_summary,
                    "content_hash": content_hash,
                },
            )
        except WorkspaceClientError as exc:
            self.state = DevPageState(error=str(exc))
            return self.state
        self._trusted_hash_refresh_notes.add(note_path)
        return self.load(NoteLoadIntent(note_path=note_path))

    def acknowledge_canvas_recovery(self, *, note_path: str) -> DevPageState:
        """Acknowledge recovery/conflict state before body edits resume."""
        if self.state.shell is not None and self.state.shell.note_path == note_path:
            self._acknowledged_recovery_tokens.add(
                _recovery_token(
                    note_path=note_path,
                    session_id=self.state.canvas_session_id,
                    session_state=self.state.canvas_session_state,
                    content_hash=self.state.shell.content_hash,
                )
            )
            self.state.canvas_recovery_acknowledged = True
            self.state.canvas_conflict_detected = False
            self.state.canvas_can_edit_body = self.state.canvas_runtime_can_edit_body
        return self.state

    def undo_last_canvas_edit(
        self,
        *,
        session_id: str,
        note_path: str,
    ) -> DevPageState:
        """Undo the most recent Canvas body edit, then refresh workspace state."""
        if not self.state.canvas_undo_available:
            self.state.error = "No undoable Canvas body edit is available"
            self.state.is_loaded = False
            return self.state
        try:
            self._http.delete(f"/api/canvas/sessions/{session_id}/edits/last")
        except WorkspaceClientError as exc:
            self.state = DevPageState(error=str(exc))
            return self.state
        return self.load(NoteLoadIntent(note_path=note_path))

    def confirm_panel_proposal(
        self,
        *,
        proposal_id: str,
        artifact_id: str,
        note_path: str,
    ) -> DevPageState:
        """Confirm a staged Panel proposal, then refresh workspace state."""
        return self._submit_panel_decision(
            proposal_id=proposal_id,
            artifact_id=artifact_id,
            note_path=note_path,
            action="confirm",
        )

    def reject_panel_proposal(
        self,
        *,
        proposal_id: str,
        artifact_id: str,
        note_path: str,
    ) -> DevPageState:
        """Reject a staged Panel proposal, then refresh workspace state."""
        return self._submit_panel_decision(
            proposal_id=proposal_id,
            artifact_id=artifact_id,
            note_path=note_path,
            action="reject",
        )

    def _submit_panel_decision(
        self,
        *,
        proposal_id: str,
        artifact_id: str,
        note_path: str,
        action: str,
    ) -> DevPageState:
        try:
            response = self._http.post(
                "/api/panel/confirm",
                json={
                    "proposal_id": proposal_id,
                    "artifact_id": artifact_id,
                    "action": action,
                    "idempotency_key": str(uuid4()),
                },
            )
        except WorkspaceClientError as exc:
            self.state = DevPageState(error=str(exc))
            return self.state
        self.state.panel_last_response = response
        refreshed = self.load(NoteLoadIntent(note_path=note_path, artifact_id=artifact_id))
        refreshed.panel_last_response = response
        return refreshed

    def render_fields(self) -> Optional[dict]:
        """Return a flat dict of renderable fields for the current state.

        Returns None if the note has not been loaded successfully.
        """
        if not self.state.is_loaded or self.state.shell is None:
            return None
        shell = self.state.shell
        return {
            "title": shell.title,
            "note_path": shell.note_path,
            "artifact_id": shell.artifact_id,
            "body": shell.body,
            "content_hash": shell.content_hash,
            "panel_rail": self.state.panel_rail_placeholder,
            "canvas_session_id": self.state.canvas_session_id,
            "canvas_session_state": self.state.canvas_session_state,
            "canvas_user_present": self.state.canvas_user_present,
            "canvas_can_edit_body": self.state.canvas_can_edit_body,
            "canvas_recovery_needed": self.state.canvas_recovery_needed,
            "canvas_recovery_acknowledged": self.state.canvas_recovery_acknowledged,
            "canvas_conflict_detected": self.state.canvas_conflict_detected,
            "canvas_session_log_path": self.state.canvas_session_log_path,
            "canvas_undo_available": self.state.canvas_undo_available,
            "canvas_applied_edit_count": self.state.canvas_applied_edit_count,
            "canvas_undone_edit_count": self.state.canvas_undone_edit_count,
            "canvas_session_persistence": self.state.canvas_session_persistence,
            "panel_state": self.state.panel_state,
            "panel_proposal_count": self.state.panel_proposal_count,
            "panel_render": self.state.panel_render or {},
            "panel_proposals": self.state.panel_proposals or [],
            "panel_last_response": self.state.panel_last_response or {},
            "suggestion_state": self.state.suggestion_state,
            "suggestion_dom_alias": self.state.suggestion_dom_alias,
            "suggestion_allowed_transitions": self.state.suggestion_allowed_transitions or [],
            "suggestion_composer_enabled": self.state.suggestion_composer_enabled,
            "suggestion_cards": self.state.suggestion_cards or [],
            "suggested_insertions": self.state.suggested_insertions or [],
            "guard_writeguard_status": self.state.guard_writeguard_status,
            "guard_canvas_enabled": self.state.guard_canvas_enabled,
            "is_production_ui": self.is_production_ui,
            "dev_page_label": self.dev_page_label,
        }


def _panel_message(panel: dict[str, Any]) -> str | None:
    state = panel.get("state") or "idle"
    if state == "blocked":
        return panel.get("blocked_reason") or panel.get("message")
    if state == "no-match":
        return panel.get("no_match_reason") or panel.get("message")
    return panel.get("message")


def _proposal_rows_from_panel(
    *,
    panel: dict[str, Any],
    artifact_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in panel.get("proposals") or []:
        evidence_raw = raw.get("evidence") or {}
        evidence = ProposalEvidence(
            trigger_summary=evidence_raw.get("trigger_summary", ""),
            action_class=evidence_raw.get("action_class", ""),
            cognition_route=evidence_raw.get("cognition_route", ""),
        )
        affordances = _proposal_affordance_set(raw.get("affordances"))
        row = ProposalRow(
            proposal_id=raw.get("proposal_id", ""),
            artifact_id=raw.get("artifact_id") or artifact_id,
            description=raw.get("description", ""),
            evidence=evidence,
            available_affordances=affordances,
            status=raw.get("status", "staged"),
        )
        rows.append(row.as_render_dict())
    return rows


def _proposal_affordance_set(raw: Any) -> set[str]:
    if isinstance(raw, dict):
        return {name for name, enabled in raw.items() if enabled}
    if isinstance(raw, list):
        return set(raw)
    return {"confirm", "correct", "reject"}


def _normalise_suggestion_state(raw_state: Any) -> str:
    state = str(raw_state or "idle")
    return state if state in RAIL_STATES else "idle"


def _recovery_token(
    *,
    note_path: str,
    session_id: Any,
    session_state: str,
    content_hash: str,
) -> tuple[str, str, str, str]:
    return (note_path, str(session_id or ""), session_state, content_hash)


def _suggestion_payloads(suggestions: dict[str, Any]) -> list[dict[str, Any]]:
    raw = suggestions.get("proposals") or suggestions.get("proposal")
    if raw is None and suggestions.get("server_declared_classification"):
        raw = suggestions
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _suggestion_cards_from_payload(suggestions: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    fallback_classification = suggestions.get("server_declared_classification")
    for index, raw in enumerate(_suggestion_payloads(suggestions), start=1):
        variant = raw.get("server_declared_classification") or fallback_classification
        if variant not in {"body", "governance", "blocked"}:
            variant = "blocked"
        card = SuggestionCard(
            suggestion_id=str(raw.get("suggestion_id") or f"suggestion-{index}"),
            variant=variant,
            title=str(raw.get("title") or raw.get("summary") or "Suggestion"),
            preview_text=str(raw.get("preview_text") or raw.get("proposed_text") or ""),
            denial_reason=raw.get("denial_reason") or "Suggestion is blocked.",
        )
        cards.append(card.as_render_dict())
    return cards


def _suggested_insertions_from_payload(suggestions: dict[str, Any]) -> list[dict[str, Any]]:
    insertions: list[dict[str, Any]] = []
    fallback_classification = suggestions.get("server_declared_classification")
    for index, raw in enumerate(_suggestion_payloads(suggestions), start=1):
        variant = raw.get("server_declared_classification") or fallback_classification
        if variant != "body":
            continue
        proposed_text = str(raw.get("proposed_text") or raw.get("preview_text") or "")
        if not proposed_text:
            continue
        insertion = SuggestedInsertion(
            suggestion_id=str(raw.get("suggestion_id") or f"suggestion-{index}"),
            anchor_description=str(raw.get("anchor_description") or "current note body"),
            proposed_text=proposed_text,
        )
        insertions.append(insertion.as_render_dict())
    return insertions
