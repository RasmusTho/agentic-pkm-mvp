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

from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from companion_ui.canvas_suggestion_flow.keyboard_shortcuts import SuggestionShortcutMap
from companion_ui.canvas_suggestion_flow.portrait_sheet import PortraitSheet, SheetSnap
from companion_ui.canvas_suggestion_flow.receipt_strip import ReceiptPill, ReceiptsStrip
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
    WorkspaceClientHTTPError,
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
    active_filters carries optional vault browser filter dimensions (kind,
    zone, review_state, trust) forwarded as multi-value query params.
    The UI does not resolve vault paths or access vault files directly.
    The runtime API is bound to an environment; it determines which vault
    is read.
    """

    note_path: str
    artifact_id: Optional[str] = None
    active_filters: dict[str, list[str]] = field(default_factory=dict)
    vault_browser_cursor: str = ""
    vault_browser_limit: int = 250


# ---------------------------------------------------------------------------
# Page state
# ---------------------------------------------------------------------------


@dataclass
class DevPageState:
    """Current render state for the dev/staging workspace page."""

    shell: Optional[RealNoteWorkspaceShell] = None
    error: Optional[str] = None
    panel_rail_placeholder: str = "Panel / agent rail — placeholder (dev)"
    artifact_kind: str = "human_note"
    artifact_identity_source: str = "unknown"
    artifact_identity_state: str = "unknown"
    artifact_companion_of: str | None = None
    artifact_owns_identity: bool = True
    runtime_environment_label: str = "unknown"
    runtime_api_base_url_label: str = "local-dev"
    runtime_trace_id: str = ""
    runtime_vault_name: str = "unresolved"
    runtime_vault_channel: str = "unknown"
    runtime_vault_provenance: str = "unresolved"
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
    panel_selectable_options: list[dict[str, Any]] | None = None
    panel_last_response: dict[str, Any] | None = None
    suggestion_state: str = "idle"
    suggestion_dom_alias: str = "idle"
    suggestion_allowed_transitions: list[str] | None = None
    suggestion_composer_enabled: bool = True
    suggestion_apply_transition_path: list[str] | None = None
    governance_pending_transition_path: list[str] | None = None
    governance_actions: list[dict[str, Any]] | None = None
    governance_receipts: list[dict[str, Any]] | None = None
    portrait_sheet: dict[str, Any] | None = None
    keyboard_shortcuts: dict[str, Any] | None = None
    find_candidates: list[dict[str, Any]] | None = None
    find_payload_available: bool = False
    reorient_sections: dict[str, list[dict[str, Any]]] | None = None
    resurface_candidates: list[dict[str, Any]] | None = None
    suggestion_cards: list[dict[str, Any]] | None = None
    suggested_insertions: list[dict[str, Any]] | None = None
    guard_writeguard_status: str = "ok"
    guard_canvas_enabled: bool = True
    guard_update_flow_available: bool = False
    guard_degraded: bool = False
    guard_workspace_update_available: bool = False
    guard_workspace_update_state: str = "disabled"
    guard_workspace_update_reason: str = "not_declared"
    guard_workspace_update_scope: str = "active_note_body"
    guard_workspace_update_governance_actions_enabled: bool = False
    guard_workspace_update_config_mode: str = "inherited"
    active_note_body_update_enabled: bool = False
    active_note_body_update_state: str = "idle"
    active_note_body_update_message: str = ""
    vault_browser_notes: list[dict[str, Any]] | None = None
    vault_link_index: list[str] | None = None
    vault_browser_query: str = ""
    vault_browser_total_notes: int = 0
    vault_browser_filtered_notes: int = 0
    vault_browser_error: str | None = None
    vault_browser_read_only: bool = True
    vault_browser_identity_available: bool = False
    vault_browser_vault_name: str = "unresolved"
    vault_browser_vault_channel: str = "unknown"
    vault_browser_vault_provenance: str = "unresolved"
    vault_browser_active_filters: dict[str, Any] = field(default_factory=dict)
    vault_browser_pagination: dict[str, Any] = field(default_factory=dict)
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
        runtime = raw.get("runtime") or {}
        workspace_update_guard = guards.get("workspace_update") or {}
        vault_browser_error: str | None = None
        if isinstance(self._http, WorkspaceHttpClient):
            try:
                browser_params: dict[str, Any] = {"q": "", "limit": 250}
                if intent.vault_browser_cursor:
                    browser_params["cursor"] = intent.vault_browser_cursor
                if intent.vault_browser_limit:
                    browser_params["limit"] = intent.vault_browser_limit
                browser_params.update(intent.active_filters)
                vault_browser = self._http.get(
                    "/api/companion/vault-browser",
                    params=browser_params,
                )
            except WorkspaceClientError as exc:
                vault_browser = {}
                vault_browser_error = str(exc)
        else:
            vault_browser = {}
        # #1431 — fetch the complete vault link index so wikilinks resolve
        # end-to-end. This is a best-effort, non-critical enrichment: any failure
        # (client error, missing endpoint on an older runtime, malformed payload)
        # must degrade to an empty index — links stay diagnostic (prior
        # behaviour) and the note still renders. The UI never reads the vault
        # filesystem; it only consumes the runtime API payload.
        vault_link_index: list[str] = []
        if isinstance(self._http, WorkspaceHttpClient):
            try:
                link_index_payload = self._http.get(
                    "/api/companion/vault-link-index", params={}
                )
                vault_link_index = [
                    str(path) for path in (link_index_payload.get("note_paths") or []) if path
                ]
            except Exception:
                vault_link_index = []
        raw_find_payload = raw.get("find")
        runtime_find_payload = runtime.get("find")
        find_payload_available = isinstance(raw_find_payload, dict) or isinstance(
            runtime_find_payload,
            dict,
        )
        find_payload = raw_find_payload or runtime_find_payload or {}
        reorient_payload = raw.get("reorient") or runtime.get("reorient") or {}
        resurface_payload = raw.get("resurface") or runtime.get("resurface") or {}
        vault_browser_identity = vault_browser.get("vault_identity") or {}

        # The runtime echoes artifact_id only when supplied in the request.
        # Fall back to note_path so note-path-only loads don't fail the shell's
        # non-empty artifact_id invariant.
        resolved_note_path = artifact.get("note_path") or intent.note_path
        vault_browser_notes = [
            dict(note)
            for note in list(vault_browser.get("notes") or [])
            if isinstance(note, dict)
        ]
        active_note_declares_relations = any(
            note.get("note_path") == resolved_note_path
            and ("relations" in note or "relations_state" in note)
            for note in vault_browser_notes
        )
        if (
            isinstance(self._http, WorkspaceHttpClient)
            and resolved_note_path
            and not active_note_declares_relations
        ):
            try:
                related_payload = self._http.get(
                    "/api/companion/vault-related",
                    params={"note_path": resolved_note_path},
                )
                related_results = list(related_payload.get("results") or [])
                relations_update = {
                    "relations": related_results,
                    "relations_state": "ready" if related_results else "empty",
                }
            except Exception:
                relations_update = {"relations_state": "unavailable"}
            vault_browser_notes = [
                {
                    **note,
                    **(
                        relations_update
                        if note.get("note_path") == resolved_note_path
                        else {}
                    ),
                }
                for note in vault_browser_notes
            ]
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
        if workspace_update_guard:
            workspace_update_available = bool(workspace_update_guard.get("available", False))
            workspace_update_state = str(workspace_update_guard.get("state") or "disabled")
            workspace_update_reason = str(workspace_update_guard.get("reason") or "not_declared")
            workspace_update_scope = str(workspace_update_guard.get("scope") or "active_note_body")
            workspace_update_governance_actions_enabled = bool(
                workspace_update_guard.get("governance_actions_enabled", False)
            )
            workspace_update_config_mode = str(workspace_update_guard.get("config_mode") or "inherited")
        else:
            # Compatibility fallback for runtime payloads without explicit workspace_update capability.
            workspace_update_available = runtime_can_edit_body and bool(guards.get("canvas_enabled", True))
            workspace_update_state = "legacy_inferred" if workspace_update_available else "disabled"
            workspace_update_reason = "legacy_payload"
            workspace_update_scope = "active_note_body"
            workspace_update_governance_actions_enabled = False
            workspace_update_config_mode = "inherited"
        can_edit_body = (
            runtime_can_edit_body
            and workspace_update_available
            and (not conflict_detected or recovery_acknowledged)
        )
        if content_hash:
            self._last_content_hash_by_note[resolved_note_path] = content_hash
        shell = RealNoteWorkspaceShell(
            payload=payload,
            agent_rail_state=None,
            # Mirror the server-declared canvas guard so the co-authoring region
            # is reachable when the runtime enables it. The UI never infers this.
            canvas_enabled=bool(guards.get("canvas_enabled", True)),
        )
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
        panel_selectable_options = [
            option
            for option in (panel.get("selectable_options") or [])
            if isinstance(option, dict)
        ]
        suggestion_machine = CanvasRailStateMachine(
            _normalise_suggestion_state(suggestions.get("current_suggestion_state"))
        )
        panel_last_response = self.state.panel_last_response
        if panel_last_response and panel_last_response.get("artifact_id") != resolved_artifact_id:
            panel_last_response = None
        suggestion_cards = _suggestion_cards_from_payload(suggestions)
        self.state = DevPageState(
            shell=shell,
            panel_rail_placeholder=panel_render.get("label", "Panel ready"),
            artifact_kind=artifact.get("artifact_kind") or "human_note",
            artifact_identity_source=artifact.get("identity_source") or "unknown",
            artifact_identity_state=artifact.get("identity_state") or "unknown",
            artifact_companion_of=artifact.get("companion_of"),
            artifact_owns_identity=bool(artifact.get("owns_identity", True)),
            runtime_environment_label=runtime.get("environment_label") or "unknown",
            runtime_api_base_url_label=runtime.get("api_base_url_label") or "local-dev",
            runtime_trace_id=runtime.get("trace_id") or "",
            runtime_vault_name=(runtime.get("vault_identity") or {}).get("vault_name") or "unresolved",
            runtime_vault_channel=(runtime.get("vault_identity") or {}).get("channel") or "unknown",
            runtime_vault_provenance=(runtime.get("vault_identity") or {}).get("provenance") or "unresolved",
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
            panel_selectable_options=panel_selectable_options,
            panel_last_response=panel_last_response,
            suggestion_state=suggestion_machine.state,
            suggestion_dom_alias=suggestion_machine.dom_alias,
            suggestion_allowed_transitions=sorted(suggestion_machine.allowed_transitions()),
            suggestion_composer_enabled=suggestion_machine.composer_enabled,
            suggestion_cards=suggestion_cards,
            governance_actions=_governance_actions_from_payload(suggestions),
            portrait_sheet=_portrait_sheet_from_cards(
                suggestion_cards,
                rail_state=suggestion_machine.state,
            ),
            keyboard_shortcuts=_shortcut_map_from_cards(
                suggestion_cards,
                rail_state=suggestion_machine.state,
            ),
            find_candidates=_find_candidates_from_payload(find_payload),
            find_payload_available=find_payload_available,
            reorient_sections=_reorient_sections_from_payload(reorient_payload),
            resurface_candidates=_resurface_candidates_from_payload(resurface_payload),
            suggested_insertions=_suggested_insertions_from_payload(suggestions),
            guard_writeguard_status=guards.get("writeguard_status") or "ok",
            guard_canvas_enabled=bool(guards.get("canvas_enabled", True)),
            guard_update_flow_available=bool(guards.get("update_flow_available", False)),
            guard_degraded=bool(guards.get("degraded", False)),
            guard_workspace_update_available=workspace_update_available,
            guard_workspace_update_state=workspace_update_state,
            guard_workspace_update_reason=workspace_update_reason,
            guard_workspace_update_scope=workspace_update_scope,
            guard_workspace_update_governance_actions_enabled=workspace_update_governance_actions_enabled,
            guard_workspace_update_config_mode=workspace_update_config_mode,
            active_note_body_update_enabled=workspace_update_available,
            vault_browser_notes=vault_browser_notes,
            vault_link_index=vault_link_index,
            vault_browser_query=str(vault_browser.get("query") or ""),
            vault_browser_total_notes=int(vault_browser.get("total_notes") or 0),
            vault_browser_filtered_notes=int(vault_browser.get("filtered_notes") or 0),
            vault_browser_error=vault_browser_error,
            vault_browser_read_only=bool(vault_browser.get("read_only", True)),
            vault_browser_identity_available=bool(vault_browser.get("identity_available", False)),
            vault_browser_vault_name=str(vault_browser_identity.get("vault_name") or "unresolved"),
            vault_browser_vault_channel=str(vault_browser_identity.get("channel") or "unknown"),
            vault_browser_vault_provenance=str(vault_browser_identity.get("provenance") or "unresolved"),
            vault_browser_active_filters=dict(vault_browser.get("active_filters") or {}),
            vault_browser_pagination=dict(vault_browser.get("pagination") or {}),
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
        preview_confirmed: bool = True,
    ) -> DevPageState:
        """Apply a body-safe Canvas edit, then refresh workspace state."""
        if not self.state.canvas_can_edit_body:
            self.state.error = "Canvas body edit unavailable outside an active editable session"
            self.state.is_loaded = False
            return self.state
        if not preview_confirmed:
            self.state.error = "Canvas body edit requires preview before apply"
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

    def apply_body_suggestion(
        self,
        *,
        suggestion_id: str,
        session_id: str,
        note_path: str,
    ) -> DevPageState:
        """Apply a staged body suggestion through the Canvas edit API."""
        if self.state.shell is None:
            self.state.error = "No workspace note is loaded"
            self.state.is_loaded = False
            return self.state
        if self.state.suggestion_state != "staged_body":
            self.state.error = "Body suggestion apply requires staged_body state"
            self.state.is_loaded = False
            return self.state

        insertion = next(
            (
                item
                for item in (self.state.suggested_insertions or [])
                if item.get("data_suggestion_id") == suggestion_id
            ),
            None,
        )
        if insertion is None:
            self.state.error = f"Unknown body suggestion: {suggestion_id}"
            self.state.is_loaded = False
            return self.state

        machine = CanvasRailStateMachine(self.state.suggestion_state)
        transition_path = [machine.state]
        machine.transition("apply_pending")
        transition_path.append(machine.state)

        try:
            self._http.post(
                f"/api/canvas/sessions/{session_id}/edits",
                json={
                    "new_body": str(insertion.get("proposed_text") or ""),
                    "change_summary": f"Applied body suggestion {suggestion_id}",
                    "content_hash": self.state.shell.content_hash,
                },
            )
        except WorkspaceClientError as exc:
            machine.transition("staged_body", error=str(exc))
            self.state.suggestion_state = machine.state
            self.state.suggestion_dom_alias = machine.dom_alias
            self.state.suggestion_allowed_transitions = sorted(machine.allowed_transitions())
            self.state.suggestion_composer_enabled = machine.composer_enabled
            self.state.suggestion_apply_transition_path = transition_path + [machine.state]
            self.state.error = str(exc)
            self.state.is_loaded = False
            return self.state

        machine.transition("applied")
        transition_path.append(machine.state)
        machine.transition("idle")
        transition_path.append(machine.state)

        self._trusted_hash_refresh_notes.add(note_path)
        refreshed = self.load(NoteLoadIntent(note_path=note_path))
        refreshed.suggestion_state = machine.state
        refreshed.suggestion_dom_alias = machine.dom_alias
        refreshed.suggestion_allowed_transitions = sorted(machine.allowed_transitions())
        refreshed.suggestion_composer_enabled = machine.composer_enabled
        refreshed.suggestion_apply_transition_path = transition_path
        return refreshed

    def update_active_note_body(self, *, new_body: str) -> DevPageState:
        """Update the currently loaded note body through the workspace update API."""
        if self.state.shell is None:
            self.state.error = "No workspace note is loaded"
            self.state.is_loaded = False
            self.state.active_note_body_update_state = "failure"
            self.state.active_note_body_update_message = "No active note loaded."
            return self.state

        note_path = self.state.shell.note_path
        if not self.state.guard_workspace_update_available:
            self.state.active_note_body_update_state = "blocked"
            self.state.active_note_body_update_message = (
                "Workspace update capability is disabled for the active runtime."
            )
            return self.state

        try:
            response = self._http.post(
                "/api/companion/workspace/update",
                json={
                    "active_note_path": note_path,
                    "target_note_path": note_path,
                    "new_body": new_body,
                    "content_hash": self.state.shell.content_hash,
                },
            )
        except WorkspaceClientHTTPError as exc:
            lowered = exc.detail.lower()
            is_blocked = exc.status_code in {403, 409} and (
                "blocked" in lowered
                or "writeguard" in lowered
                or "scope" in lowered
                or "unavailable" in lowered
            )
            self.state.active_note_body_update_state = "blocked" if is_blocked else "failure"
            self.state.active_note_body_update_message = exc.detail
            self.state.error = str(exc)
            return self.state
        except WorkspaceClientError as exc:
            self.state.active_note_body_update_state = "failure"
            self.state.active_note_body_update_message = str(exc)
            self.state.error = str(exc)
            return self.state

        refreshed = self.load(NoteLoadIntent(note_path=note_path))
        refreshed.active_note_body_update_state = "success"
        refreshed.active_note_body_update_message = (
            str(response.get("reason") or "active_note_body_updated")
        )
        return refreshed

    def queue_governance_suggestion(
        self,
        *,
        suggestion_id: str,
        session_id: str,
        note_path: str,
    ) -> DevPageState:
        """Queue a staged governance suggestion through the Canvas Panel pipeline."""
        if self.state.shell is None:
            self.state.error = "No workspace note is loaded"
            self.state.is_loaded = False
            return self.state
        if self.state.suggestion_state != "staged_governance":
            self.state.error = "Governance queue requires staged_governance state"
            self.state.is_loaded = False
            return self.state

        action = next(
            (
                item
                for item in (self.state.governance_actions or [])
                if item.get("suggestion_id") == suggestion_id
            ),
            None,
        )
        if action is None:
            self.state.error = f"Unknown governance suggestion: {suggestion_id}"
            self.state.is_loaded = False
            return self.state

        machine = CanvasRailStateMachine(self.state.suggestion_state)
        transition_path = [machine.state]
        machine.transition("governance_pending")
        transition_path.append(machine.state)

        try:
            response = self._http.post(
                f"/api/canvas/sessions/{session_id}/governance",
                json={
                    "action_type": action["action_type"],
                    "payload": action["payload"],
                },
            )
        except WorkspaceClientError as exc:
            machine.transition("staged_governance", error=str(exc))
            self.state.suggestion_state = machine.state
            self.state.suggestion_dom_alias = machine.dom_alias
            self.state.suggestion_allowed_transitions = sorted(machine.allowed_transitions())
            self.state.suggestion_composer_enabled = machine.composer_enabled
            self.state.governance_pending_transition_path = transition_path + [machine.state]
            self.state.error = str(exc)
            self.state.is_loaded = False
            return self.state

        receipt = ReceiptPill(
            receipt_id=str(response.get("intent_id") or ""),
            suggestion_id=suggestion_id,
            artifact_id=str(response.get("artifact_id") or self.state.shell.artifact_id),
            outcome="queued",
            label=f"queued · {response.get('intent_id')} · {action['action_type']}",
            display_timestamp="queued",
            message=action.get("summary"),
        ).to_render_dict()

        machine.transition("idle")
        transition_path.append(machine.state)

        refreshed = self.load(NoteLoadIntent(note_path=note_path))
        refreshed.suggestion_state = machine.state
        refreshed.suggestion_dom_alias = machine.dom_alias
        refreshed.suggestion_allowed_transitions = sorted(machine.allowed_transitions())
        refreshed.suggestion_composer_enabled = machine.composer_enabled
        refreshed.governance_pending_transition_path = transition_path
        refreshed.governance_receipts = ReceiptsStrip(
            pills=[
                ReceiptPill(
                    receipt_id=receipt["data_receipt_id"],
                    suggestion_id=receipt["data_suggestion_id"],
                    artifact_id=receipt["data_artifact_id"],
                    outcome=receipt["data_status"],
                    label=receipt["label"],
                    display_timestamp=receipt["display_timestamp"],
                    message=receipt.get("message"),
                )
            ]
        ).to_render_dict()["non_terminal_pills"]
        return refreshed

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

    def correct_panel_proposal(
        self,
        *,
        proposal_id: str,
        artifact_id: str,
        note_path: str,
        corrected_action_id: str | None = None,
        corrected_parameters: dict[str, Any] | None = None,
    ) -> DevPageState:
        """Submit a corrected staged Panel proposal, then refresh workspace state."""
        if corrected_action_id is None and corrected_parameters is None:
            self.state.error = (
                "Panel correction requires corrected_action_id or corrected_parameters"
            )
            self.state.is_loaded = False
            return self.state
        return self._submit_panel_decision(
            proposal_id=proposal_id,
            artifact_id=artifact_id,
            note_path=note_path,
            action="confirm",
            correction={
                "enabled": True,
                "corrected_action_id": corrected_action_id,
                "corrected_parameters": corrected_parameters,
            },
        )

    def _submit_panel_decision(
        self,
        *,
        proposal_id: str,
        artifact_id: str,
        note_path: str,
        action: str,
        correction: dict[str, Any] | None = None,
    ) -> DevPageState:
        request_payload: dict[str, Any] = {
            "proposal_id": proposal_id,
            "artifact_id": artifact_id,
            "action": action,
            "idempotency_key": str(uuid4()),
        }
        if correction is not None:
            request_payload["correction"] = correction
        try:
            response = self._http.post(
                "/api/panel/confirm",
                json=request_payload,
            )
        except WorkspaceClientHTTPError as exc:
            if exc.status_code == 422 and "same-turn" in exc.detail.lower():
                self.state.panel_last_response = {
                    "proposal_id": proposal_id,
                    "artifact_id": artifact_id,
                    "status": "blocked",
                    "outcome": "blocked",
                    "block_reason": {
                        "gate": "same-turn",
                        "message": (
                            "Same-turn confirmation is not allowed. "
                            "The proposal must be confirmed in a later interaction."
                        ),
                    },
                }
                return self.state
            self.state = DevPageState(error=str(exc))
            return self.state
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
            "artifact_kind": self.state.artifact_kind,
            "artifact_identity_source": self.state.artifact_identity_source,
            "artifact_identity_state": self.state.artifact_identity_state,
            "artifact_companion_of": self.state.artifact_companion_of,
            "artifact_owns_identity": self.state.artifact_owns_identity,
            "runtime_environment_label": self.state.runtime_environment_label,
            "runtime_api_base_url_label": self.state.runtime_api_base_url_label,
            "runtime_trace_id": self.state.runtime_trace_id,
            "runtime_vault_name": self.state.runtime_vault_name,
            "runtime_vault_channel": self.state.runtime_vault_channel,
            "runtime_vault_provenance": self.state.runtime_vault_provenance,
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
            "panel_selectable_options": self.state.panel_selectable_options or [],
            "panel_last_response": self.state.panel_last_response or {},
            "suggestion_state": self.state.suggestion_state,
            "suggestion_dom_alias": self.state.suggestion_dom_alias,
            "suggestion_allowed_transitions": self.state.suggestion_allowed_transitions or [],
            "suggestion_composer_enabled": self.state.suggestion_composer_enabled,
            "suggestion_apply_transition_path": self.state.suggestion_apply_transition_path
            or [],
            "governance_pending_transition_path": self.state.governance_pending_transition_path
            or [],
            "governance_receipts": self.state.governance_receipts or [],
            "portrait_sheet": self.state.portrait_sheet or {},
            "keyboard_shortcuts": self.state.keyboard_shortcuts or {},
            "find_candidates": self.state.find_candidates or [],
            "find_payload_available": self.state.find_payload_available,
            "reorient_sections": self.state.reorient_sections or {},
            "resurface_candidates": self.state.resurface_candidates or [],
            "suggestion_cards": self.state.suggestion_cards or [],
            "suggested_insertions": self.state.suggested_insertions or [],
            "guard_writeguard_status": self.state.guard_writeguard_status,
            "guard_canvas_enabled": self.state.guard_canvas_enabled,
            "guard_update_flow_available": self.state.guard_update_flow_available,
            "guard_degraded": self.state.guard_degraded,
            "guard_workspace_update_available": self.state.guard_workspace_update_available,
            "guard_workspace_update_state": self.state.guard_workspace_update_state,
            "guard_workspace_update_reason": self.state.guard_workspace_update_reason,
            "guard_workspace_update_scope": self.state.guard_workspace_update_scope,
            "guard_workspace_update_governance_actions_enabled": (
                self.state.guard_workspace_update_governance_actions_enabled
            ),
            "guard_workspace_update_config_mode": self.state.guard_workspace_update_config_mode,
            "active_note_body_update_enabled": self.state.active_note_body_update_enabled,
            "active_note_body_update_state": self.state.active_note_body_update_state,
            "active_note_body_update_message": self.state.active_note_body_update_message,
            "vault_browser_notes": self.state.vault_browser_notes or [],
            "vault_link_index": self.state.vault_link_index or [],
            "vault_browser_query": self.state.vault_browser_query,
            "vault_browser_total_notes": self.state.vault_browser_total_notes,
            "vault_browser_filtered_notes": self.state.vault_browser_filtered_notes,
            "vault_browser_error": self.state.vault_browser_error,
            "vault_browser_read_only": self.state.vault_browser_read_only,
            "vault_browser_identity_available": self.state.vault_browser_identity_available,
            "vault_browser_vault_name": self.state.vault_browser_vault_name,
            "vault_browser_vault_channel": self.state.vault_browser_vault_channel,
            "vault_browser_vault_provenance": self.state.vault_browser_vault_provenance,
            "vault_browser_active_filters": self.state.vault_browser_active_filters,
            "vault_browser_pagination": self.state.vault_browser_pagination,
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


def _reorient_sections_from_payload(
    reorient: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    sections: dict[str, list[dict[str, Any]]] = {}
    for section in (
        "facts",
        "inferences",
        "candidates",
        "stale_context",
        "recent_deltas",
        "open_loops",
    ):
        raw_items = reorient.get(section) or []
        items: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_items, start=1):
            if isinstance(raw, str):
                raw = {"label": raw}
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or raw.get("text") or "").strip()
            if not label:
                continue
            items.append(
                {
                    "item_id": str(raw.get("item_id") or f"{section}-{index}"),
                    "label": label,
                    "source_link": str(raw.get("source_link") or raw.get("source") or ""),
                    "panel_handoff": bool(raw.get("panel_handoff", False)),
                }
            )
        sections[section] = items
    return sections


def _resurface_candidates_from_payload(resurface: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = resurface.get("candidates") or []
    if isinstance(raw_candidates, dict):
        raw_candidates = [raw_candidates]
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict):
            continue
        why_now = str(raw.get("why_now") or raw.get("why") or "").strip()
        relation = str(
            raw.get("relation_to_active_artifact") or raw.get("relation") or ""
        ).strip()
        source_link = str(raw.get("source_link") or raw.get("source") or "").strip()
        if not why_now or not relation or not source_link:
            continue
        signal_labels = raw.get("signal_labels") or raw.get("signals") or []
        if not isinstance(signal_labels, list):
            signal_labels = [str(signal_labels)]
        candidates.append(
            {
                "candidate_id": str(
                    raw.get("candidate_id") or raw.get("id") or f"resurface-{index}"
                ),
                "label": str(raw.get("label") or raw.get("title") or "Resurfacing candidate"),
                "why_now": why_now,
                "relation_to_active_artifact": relation,
                "source_link": source_link,
                "signal_labels": [str(label) for label in signal_labels],
            }
        )
    return candidates

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


def _governance_actions_from_payload(suggestions: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    fallback_classification = suggestions.get("server_declared_classification")
    for index, raw in enumerate(_suggestion_payloads(suggestions), start=1):
        variant = raw.get("server_declared_classification") or fallback_classification
        if variant != "governance":
            continue
        suggestion_id = str(raw.get("suggestion_id") or f"suggestion-{index}")
        payload = raw.get("payload")
        if not isinstance(payload, dict):
            payload = {
                "suggestion_id": suggestion_id,
                "title": raw.get("title"),
                "summary": raw.get("summary") or raw.get("preview_text"),
            }
        actions.append(
            {
                "suggestion_id": suggestion_id,
                "action_type": str(raw.get("action_type") or "frontmatter_update"),
                "payload": payload,
                "summary": raw.get("summary") or raw.get("preview_text"),
            }
        )
    return actions


def _portrait_sheet_from_cards(
    cards: list[dict[str, Any]],
    *,
    rail_state: str,
) -> dict[str, Any]:
    suggestion_id = str(cards[0].get("data_suggestion_id") or "suggestion") if cards else "none"
    sheet = PortraitSheet(
        suggestion_id=suggestion_id,
        current_snap=SheetSnap.PEEK if cards else SheetSnap.CLOSED,
        rail_state=rail_state,
    )
    if rail_state in {"staged_body", "staged_governance"}:
        sheet = sheet.auto_snap_on_proposal()
    return sheet.to_render_dict()


def _shortcut_map_from_cards(
    cards: list[dict[str, Any]],
    *,
    rail_state: str,
) -> dict[str, Any]:
    variant = str(cards[0].get("data_variant") or "terminal") if cards else "terminal"
    if rail_state in {"applied", "discarded"}:
        variant = "terminal"
    return SuggestionShortcutMap(
        variant=variant,
        rail_state=rail_state,
        terminal_state=rail_state in {"applied", "discarded", "blocked"},
    ).to_render_dict()


def _find_candidates_from_payload(find_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_candidates = find_payload.get("candidates") or find_payload.get("hits") or []
    if isinstance(raw_candidates, dict):
        raw_candidates = [raw_candidates]
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict):
            continue
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        citation = raw.get("citation") or raw.get("source_ref") or payload.get("source_ref")
        citation_missing = not bool(str(citation or "").strip())
        scope = raw.get("scope") or payload.get("scope") or find_payload.get("scope")
        why = (
            raw.get("why")
            or raw.get("why_this_source")
            or raw.get("explanation")
            or payload.get("why")
            or "Matched the current Find query."
        )
        candidates.append(
            {
                "candidate_id": str(raw.get("candidate_id") or raw.get("id") or f"find-{index}"),
                "title": str(raw.get("title") or raw.get("doc_id") or raw.get("object_id") or "Source"),
                "snippet": str(raw.get("snippet") or raw.get("text") or ""),
                "citation": str(citation or "uncited"),
                "citation_missing": citation_missing,
                "scope": str(scope or "workspace"),
                "why": str(why),
                "panel_handoff": bool(raw.get("panel_handoff", True)),
                "panel_handoff_status": str(
                    raw.get("panel_handoff_status") or "unavailable"
                ),
            }
        )
    return candidates


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
