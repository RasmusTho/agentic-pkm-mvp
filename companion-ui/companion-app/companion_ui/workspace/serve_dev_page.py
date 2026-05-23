"""Minimal browser dev server for the real-note workspace page (#1103).

DEV/STAGING ONLY — not for production use.

Does not implement auth, TLS, reverse proxy, or public exposure.
Calls the configured runtime API through WorkspaceHttpClient
(GET /api/companion/workspace). Does not read vault files directly.
Vault binding is determined by the runtime environment, not by this server.

Environment variables:
    HOST                   Bind address         (default: 127.0.0.1)
    PORT                   Bind port            (default: 8111)
    COMPANION_API_BASE_URL Runtime API base URL (default: http://127.0.0.1:18001)

Runtime API port map (docs/ENVIRONMENTS.md):
    prod → 18000
    dev  → 18001
    test → 18002

Companion UI dev server port map:
    dev  → 8111
    test → 8112
    prod → 8113

Local dev:
    cd companion-ui/companion-app
    COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=127.0.0.1 PORT=8111 \\
        python -m companion_ui.workspace.serve_dev_page

LAN/Tailscale (explicit operator action required — not the default):
    cd companion-ui/companion-app
    COMPANION_API_BASE_URL=http://<host-ip>:18001 HOST=0.0.0.0 PORT=8111 \\
        python -m companion_ui.workspace.serve_dev_page
"""

import html as _html
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8111
_DEFAULT_API_BASE_URL = "http://127.0.0.1:18001"


def load_config() -> dict:
    """Load server configuration from environment variables.

    Returns a dict with keys: host, port, api_base_url.
    Defaults: HOST=127.0.0.1, PORT=8111, COMPANION_API_BASE_URL=http://127.0.0.1:18001.
    """
    return {
        "host": os.environ.get("HOST", _DEFAULT_HOST),
        "port": int(os.environ.get("PORT", str(_DEFAULT_PORT))),
        "api_base_url": os.environ.get("COMPANION_API_BASE_URL", _DEFAULT_API_BASE_URL),
    }


def _e(value: str) -> str:
    """HTML-escape a string for safe inline output."""
    return _html.escape(str(value))


def _status_label(value: object, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _render_note_section(fields: dict) -> str:
    """Render the workspace shell from render_fields() output.

    Uses Yggdrasil design tokens. Stable data-testid / data-region attributes
    match the region constants in real_note_workspace_shell.py for future
    Canvas/Panel integration.
    """
    title = _e(fields.get("title", ""))
    note_path_val = _e(fields.get("note_path", ""))
    artifact_id = _e(fields.get("artifact_id", ""))
    content_hash = _e(fields.get("content_hash", ""))
    artifact_kind = _e(_status_label(fields.get("artifact_kind"), fallback="human_note"))
    identity_source = _e(_status_label(fields.get("artifact_identity_source")))
    identity_state_raw = _status_label(fields.get("artifact_identity_state"))
    identity_state = _e(identity_state_raw)
    companion_of = _e(fields.get("artifact_companion_of") or "")
    owns_identity = bool(fields.get("artifact_owns_identity", True))
    runtime_environment = _e(_status_label(fields.get("runtime_environment_label")))
    runtime_channel = _e(_status_label(fields.get("runtime_api_base_url_label"), fallback="local-dev"))
    runtime_trace_id = _e(fields.get("runtime_trace_id") or "")
    vault_name = _e(fields.get("runtime_vault_name") or "unresolved")
    vault_channel = _e(fields.get("runtime_vault_channel") or "unknown")
    vault_provenance = fields.get("runtime_vault_provenance") or "unresolved"
    body = _e(fields.get("body", ""))
    panel_rail = _e(fields.get("panel_rail", "Panel / agent rail placeholder"))
    canvas_session_id = _e(fields.get("canvas_session_id") or "")
    canvas_state = _e(fields.get("canvas_session_state", "idle"))
    canvas_user_present = bool(fields.get("canvas_user_present", False))
    canvas_can_edit_body = bool(fields.get("canvas_can_edit_body", False))
    recovery_needed = bool(fields.get("canvas_recovery_needed", False))
    recovery_acknowledged = bool(fields.get("canvas_recovery_acknowledged", False))
    conflict_detected = bool(fields.get("canvas_conflict_detected", False))
    session_log_path = _e(fields.get("canvas_session_log_path") or "")
    undo_available = bool(fields.get("canvas_undo_available", False))
    applied_edit_count = int(fields.get("canvas_applied_edit_count", 0) or 0)
    undone_edit_count = int(fields.get("canvas_undone_edit_count", 0) or 0)
    persistence = str(fields.get("canvas_session_persistence", ""))
    panel_render = fields.get("panel_render") or {}
    panel_state = _e(panel_render.get("state") or fields.get("panel_state", "idle"))
    panel_label = _e(panel_render.get("label") or panel_rail)
    panel_message = _e(panel_render.get("message") or "")
    proposal_count = int(fields.get("panel_proposal_count", 0) or 0)
    writeguard_status = _e(fields.get("guard_writeguard_status", "ok"))
    writeguard_blocked = writeguard_status.lower() == "blocked"
    canvas_enabled = bool(fields.get("guard_canvas_enabled", True))
    update_flow_available = bool(fields.get("guard_update_flow_available", False))
    guard_degraded = bool(fields.get("guard_degraded", False))
    workspace_update_available = bool(fields.get("guard_workspace_update_available", False))
    workspace_update_state = _e(fields.get("guard_workspace_update_state") or "disabled")
    workspace_update_reason = _e(fields.get("guard_workspace_update_reason") or "not_declared")
    workspace_update_scope = _e(fields.get("guard_workspace_update_scope") or "active_note_body")
    workspace_update_governance_actions_enabled = bool(
        fields.get("guard_workspace_update_governance_actions_enabled", False)
    )
    workspace_update_config_mode = _e(fields.get("guard_workspace_update_config_mode") or "inherited")
    active_note_body_update_enabled = bool(
        fields.get("active_note_body_update_enabled", workspace_update_available)
    )
    active_note_body_update_state = _e(fields.get("active_note_body_update_state") or "idle")
    active_note_body_update_message = _e(fields.get("active_note_body_update_message") or "")
    identity_caution_html = ""
    if identity_state_raw.startswith("unresolved"):
        identity_caution_html = (
            '<div class="identity-caution" data-testid="workspace-artifact-identity-caution">'
            "Artifact identity unresolved; runtime may block governed actions until identity is resolved."
            "</div>"
        )
    companion_html = (
        f'<span class="identity-meta" data-testid="workspace-companion-of">companion of {companion_of}</span>'
        if companion_of
        else ""
    )
    safety_strip_html = f"""
      <section
        class="runtime-safety-strip"
        data-testid="workspace-runtime-safety-strip"
        data-affordance-status="read-only"
        data-runtime-backed="true">
        <div class="safety-item" data-testid="workspace-runtime-channel">
          <span class="safety-label">runtime</span>
          <span>{runtime_environment}</span>
          <span class="safety-sep">/</span>
          <span>{runtime_channel}</span>
        </div>
        <div class="safety-item" data-testid="workspace-vault-identity" data-vault-provenance="{vault_provenance}">
          <span class="safety-label">vault/channel</span>
          <span>{vault_name}</span>
          <span class="safety-sep">/</span>
          <span>{vault_channel}</span>
        </div>
        <div class="safety-item" data-testid="workspace-writeguard-state">
          <span class="safety-label">WriteGuard</span>
          <span>{writeguard_status}</span>
        </div>
        <div class="safety-item" data-testid="workspace-canvas-enabled-state">
          <span class="safety-label">Canvas</span>
          <span>{'enabled' if canvas_enabled else 'disabled'}</span>
        </div>
        <div class="safety-item" data-testid="workspace-update-flow-state"
             data-update-flow="{'available' if update_flow_available else 'disabled'}">
          <span class="safety-label">Update flow</span>
          <span>{'available' if update_flow_available else 'disabled'}</span>
        </div>
        <div class="safety-item" data-testid="workspace-guard-degraded-state">
          <span class="safety-label">guard</span>
          <span>{'degraded' if guard_degraded else 'normal'}</span>
        </div>
        <div class="safety-item" data-testid="workspace-update-flow-state" data-update-state="{workspace_update_state}">
          <span class="safety-label">workspace update</span>
          <span>{'available' if workspace_update_available else 'disabled'}</span>
          <span class="safety-sep">/</span>
          <span>{workspace_update_scope}</span>
        </div>
        <div class="safety-item" data-testid="workspace-update-flow-reason">
          <span class="safety-label">update reason</span>
          <span>{workspace_update_reason}</span>
          <span class="safety-sep">/</span>
          <span>{workspace_update_config_mode}</span>
        </div>
        <div class="safety-item" data-testid="workspace-update-governance-state">
          <span class="safety-label">governance via update</span>
          <span>{'enabled' if workspace_update_governance_actions_enabled else 'disabled'}</span>
        </div>
        <div class="safety-item" data-testid="workspace-runtime-trace-id">
          <span class="safety-label">trace</span>
          <code>{runtime_trace_id or 'unavailable'}</code>
        </div>
      </section>"""
    guard_messages: list[str] = []
    if writeguard_status.lower() == "blocked":
        guard_messages.append("WriteGuard blocked")
    if not canvas_enabled:
        guard_messages.append("Canvas disabled")
    if not workspace_update_available:
        guard_messages.append("Workspace update disabled")
    guard_html = ""
    if guard_messages:
        guard_html = (
            '<div class="rail-alert rail-alert-blocked" '
            'data-testid="workspace-guard-indicator">'
            + _e(" / ".join(guard_messages))
            + "</div>"
        )
    persistence_html = ""
    if persistence == "in_memory":
        persistence_html = (
            '<div class="rail-alert rail-alert-muted" '
            'data-testid="workspace-session-persistence">'
            "Session persistence: in_memory"
            "</div>"
        )
    proposal_text = f"{proposal_count} proposal{'s' if proposal_count != 1 else ''}"
    panel_message_html = ""
    if panel_message:
        panel_message_html = (
            '<div class="panel-message" data-testid="workspace-panel-message">'
            + panel_message
            + "</div>"
        )
    proposal_rows_html = _render_panel_proposal_rows(
        fields.get("panel_proposals") or [],
        writeguard_blocked=writeguard_blocked,
    )
    panel_response_html = _render_panel_confirm_response(
        fields.get("panel_last_response") or {},
    )
    suggestion_flow_html = _render_suggestion_flow_region(fields)
    suggestion_cards_html = _render_suggestion_cards(fields.get("suggestion_cards") or [])
    portrait_sheet_html = _render_portrait_sheet(fields.get("portrait_sheet") or {})
    shortcut_html = _render_keyboard_shortcuts(fields.get("keyboard_shortcuts") or {})
    governance_receipts_html = _render_governance_receipts(
        fields.get("governance_receipts") or []
    )
    find_mode_html = _render_find_mode(
        fields.get("find_candidates") or [],
        payload_available=bool(fields.get("find_payload_available", False)),
    )
    reorient_mode_html = _render_reorient_mode(fields.get("reorient_sections") or {})
    resurface_mode_html = _render_resurface_mode(
        fields.get("resurface_candidates") or [],
        degraded=guard_degraded,
    )
    act_mode_html = _render_act_mode(
        proposals=fields.get("panel_proposals") or [],
        response=fields.get("panel_last_response") or {},
        writeguard_blocked=writeguard_blocked,
    )
    vault_browser_html = _render_vault_browser(
        note_path=fields.get("note_path") or "",
        notes=fields.get("vault_browser_notes") or [],
        query=str(fields.get("vault_browser_query") or ""),
        total_notes=int(fields.get("vault_browser_total_notes") or 0),
        filtered_notes=int(fields.get("vault_browser_filtered_notes") or 0),
        error=fields.get("vault_browser_error"),
        read_only=bool(fields.get("vault_browser_read_only", True)),
        identity_available=bool(fields.get("vault_browser_identity_available", False)),
        vault_name=str(fields.get("vault_browser_vault_name") or "unresolved"),
        vault_channel=str(fields.get("vault_browser_vault_channel") or "unknown"),
        vault_provenance=str(fields.get("vault_browser_vault_provenance") or "unresolved"),
    )
    suggested_insertions_html = _render_suggested_insertions(
        fields.get("suggested_insertions") or []
    )
    canvas_controls_html = _render_canvas_session_controls(
        note_path=note_path_val,
        session_id=canvas_session_id,
        session_state=canvas_state,
        can_edit_body=canvas_can_edit_body,
        user_present=canvas_user_present,
        content_hash=content_hash,
        recovery_needed=recovery_needed,
        recovery_acknowledged=recovery_acknowledged,
        conflict_detected=conflict_detected,
        canvas_enabled=canvas_enabled,
        workspace_update_available=workspace_update_available,
        workspace_update_reason=workspace_update_reason,
        writeguard_blocked=writeguard_blocked,
        session_log_path=session_log_path,
        undo_available=undo_available,
        applied_edit_count=applied_edit_count,
        undone_edit_count=undone_edit_count,
    )
    active_note_body_update_html = _render_active_note_body_update_flow(
        note_path=note_path_val,
        content_hash=content_hash,
        enabled=active_note_body_update_enabled,
        state=active_note_body_update_state,
        message=active_note_body_update_message,
        reason=workspace_update_reason,
    )

    return f"""
  <div class="workspace-layout">
    <div class="workspace-main">
      {safety_strip_html}
      <header
        class="note-header active-note-header"
        data-testid="workspace-note-header"
        data-region="note-header">
        <h1 class="note-title">{title}</h1>
        <div class="note-provenance">
          <span class="prov-item"><span class="prov-label">path</span><code>{note_path_val}</code></span>
          <span class="prov-sep">&middot;</span>
          <span
            class="prov-item artifact-identity-pill"
            data-testid="workspace-artifact-identity-pill"
            data-identity-state="{identity_state}"
            data-identity-source="{identity_source}"
            data-artifact-kind="{artifact_kind}"
            data-owns-identity="{'true' if owns_identity else 'false'}">
            <span class="prov-label">artifact</span><code>{artifact_id or 'unresolved'}</code>
            <span class="identity-meta">{identity_state}</span>
            <span class="identity-meta">{identity_source}</span>
            {companion_html}
          </span>
          <span class="prov-sep">&middot;</span>
          <span
            class="prov-item content-hash-pill"
            data-testid="workspace-content-hash-pill">
            <span class="prov-label">hash</span><code>{content_hash or 'unavailable'}</code>
          </span>
        </div>
        {identity_caution_html}
      </header>
      <div class="note-body" data-testid="workspace-note-body" data-region="note-body">
        <pre class="note-body-content">{body}</pre>
        {suggested_insertions_html}
      </div>
    </div>
    <aside
      class="agent-rail"
      data-testid="workspace-agent-rail"
      data-region="agent-rail"
      data-layout-desktop="side-rail">
      <div class="rail-header">
        <span class="rail-label">Companion&nbsp;/ Panel</span>
        <span class="rail-badge" data-testid="workspace-panel-state">{panel_state}</span>
      </div>
      <div class="rail-placeholder-body">
        <div class="rail-state-row" data-testid="workspace-canvas-state">
          <span class="rail-state-label">Canvas</span>
          <span class="rail-state-value">{canvas_state}</span>
        </div>
        {canvas_controls_html}
        {active_note_body_update_html}
        <div class="rail-state-row">
          <span class="rail-state-label">Panel</span>
          <span class="rail-state-value" data-testid="workspace-panel-label">{panel_label}</span>
          <span class="rail-state-count" data-testid="workspace-panel-proposal-count">{proposal_text}</span>
        </div>
        {panel_message_html}
        {proposal_rows_html}
        {panel_response_html}
        {suggestion_flow_html}
        {suggestion_cards_html}
        {shortcut_html}
        {governance_receipts_html}
        {find_mode_html}
        {reorient_mode_html}
        {resurface_mode_html}
        {act_mode_html}
        {vault_browser_html}
        {guard_html}
        {persistence_html}
        {panel_rail}
      </div>
    </aside>
    {portrait_sheet_html}
  </div>"""


def _render_active_note_body_update_flow(
    *,
    note_path: str,
    content_hash: str,
    enabled: bool,
    state: str,
    message: str,
    reason: str,
) -> str:
    safe_state = _e(state or "idle")
    safe_message = _e(message)
    if not enabled:
        return f"""
        <section
          class="active-note-body-update-flow"
          data-testid="workspace-active-note-body-update-flow"
          data-flow-state="disabled">
          <div
            class="active-note-body-update-blocked"
            data-testid="workspace-active-note-body-update-state-blocked">
            Active-note body update unavailable: {_e(reason)}.
          </div>
        </section>"""

    status_html = ""
    if safe_state == "success":
        status_html = (
            '<div class="active-note-body-update-success" '
            'data-testid="workspace-active-note-body-update-state-success">'
            + (safe_message or "Body update saved.")
            + "</div>"
        )
    elif safe_state == "blocked":
        status_html = (
            '<div class="active-note-body-update-blocked" '
            'data-testid="workspace-active-note-body-update-state-blocked">'
            + (safe_message or "Body update blocked by runtime guard.")
            + "</div>"
        )
    elif safe_state == "failure":
        status_html = (
            '<div class="active-note-body-update-failure" '
            'data-testid="workspace-active-note-body-update-state-failure">'
            + (safe_message or "Body update failed.")
            + "</div>"
        )

    return f"""
        <section
          class="active-note-body-update-flow"
          data-testid="workspace-active-note-body-update-flow"
          data-flow-state="enabled">
          <label for="active_note_body_update_input">Active note body update</label>
          <textarea
            id="active_note_body_update_input"
            data-testid="workspace-active-note-body-update-input"
            aria-label="Active note body update input"></textarea>
          <button
            type="button"
            data-testid="workspace-active-note-body-update-submit"
            data-api-method="POST"
            data-api-path="/api/companion/workspace/update"
            data-note-path="{_e(note_path)}"
            data-content-hash="{_e(content_hash)}">Update body</button>
          {status_html}
        </section>"""


def _render_vault_browser(
    *,
    note_path: str,
    notes: list[dict],
    query: str,
    total_notes: int,
    filtered_notes: int,
    error: object,
    read_only: bool,
    identity_available: bool,
    vault_name: str,
    vault_channel: str,
    vault_provenance: str,
) -> str:
    query_text = _e(query or "")
    identity_label = f"{vault_name}/{vault_channel}"
    identity_html = (
        f'<span data-testid="workspace-vault-browser-active-identity">{_e(identity_label)}</span>'
    )
    if error:
        state_html = (
            '<div class="vault-browser-state" data-testid="workspace-vault-browser-state-error">'
            + _e(str(error))
            + "</div>"
        )
    elif not identity_available:
        state_html = (
            '<div class="vault-browser-state" '
            'data-testid="workspace-vault-browser-state-identity-unavailable">'
            "Vault identity unavailable; browsing context is unresolved."
            "</div>"
        )
    elif filtered_notes == 0:
        state_html = (
            '<div class="vault-browser-state" data-testid="workspace-vault-browser-state-empty">'
            "No notes matched the current filter."
            "</div>"
        )
    else:
        state_html = (
            '<div class="vault-browser-state" data-testid="workspace-vault-browser-state-ready">'
            f"{filtered_notes} matches from {total_notes} markdown notes."
            "</div>"
        )

    rows: list[str] = []
    for note in notes:
        path = str(note.get("note_path") or "").strip()
        if not path:
            continue
        title = _e(note.get("title") or path)
        zone = _e(note.get("zone") or "root")
        href = "/?note_path=" + quote(path, safe="/")
        active = "true" if path == note_path else "false"
        rows.append(
            f"""
          <li class="vault-browser-row" data-testid="workspace-vault-browser-note-row" data-active="{active}">
            <a href="{href}" data-testid="workspace-vault-browser-note-link">{title}</a>
            <code data-testid="workspace-vault-browser-note-path">{_e(path)}</code>
            <span data-testid="workspace-vault-browser-note-zone">{zone}</span>
          </li>"""
        )

    list_html = (
        '<ul class="vault-browser-list" data-testid="workspace-vault-browser-list">'
        + "".join(rows)
        + "</ul>"
        if rows
        else ""
    )
    read_only_text = "read-only" if read_only else "mutating"
    return f"""
        <details class="vault-browser" data-testid="workspace-vault-browser" open>
          <summary data-testid="workspace-vault-browser-toggle">Browse vault notes</summary>
          <div class="vault-browser-meta" data-testid="workspace-vault-browser-meta">
            {identity_html}
            <span data-testid="workspace-vault-browser-read-only">{read_only_text}</span>
            <span data-testid="workspace-vault-browser-query">{query_text}</span>
            <span data-testid="workspace-vault-browser-provenance">{_e(vault_provenance)}</span>
          </div>
          {state_html}
          {list_html}
        </details>"""


def _render_suggestion_flow_region(fields: dict) -> str:
    suggestion_state = _e(fields.get("suggestion_state", "idle"))
    dom_alias = _e(fields.get("suggestion_dom_alias", suggestion_state))
    composer_enabled = bool(fields.get("suggestion_composer_enabled", True))
    composer_text = "composer enabled" if composer_enabled else "composer locked"
    transitions = fields.get("suggestion_allowed_transitions") or []
    transition_html = "".join(
        (
            '<span class="suggestion-transition" '
            f'data-testid="workspace-suggestion-transition" data-transition-to="{_e(target)}">'
            f"{_e(target)}</span>"
        )
        for target in transitions
    )
    return f"""
        <div
          class="suggestion-flow"
          data-testid="workspace-suggestion-flow"
          data-suggestion-state="{suggestion_state}"
          data-suggestion-dom-alias="{dom_alias}">
          <div class="rail-state-row">
            <span class="rail-state-label">Suggestion</span>
            <span class="rail-state-value">{suggestion_state}</span>
          </div>
          <div class="suggestion-composer-state">{composer_text}</div>
          <div class="suggestion-transitions">{transition_html}</div>
        </div>"""


def _render_portrait_sheet(sheet: dict) -> str:
    if not sheet:
        return ""
    visible = "true" if sheet.get("is_visible") else "false"
    return f"""
    <aside
      class="portrait-sheet"
      data-testid="{_e(sheet.get("data_testid", "portrait-sheet"))}"
      data-layout-portrait="bottom-sheet"
      data-suggestion-id="{_e(sheet.get("suggestion_id", ""))}"
      data-rail-state="{_e(sheet.get("rail_state", ""))}"
      data-current-snap="{_e(sheet.get("current_snap", ""))}"
      data-height-hint="{_e(sheet.get("height_hint", ""))}"
      data-auto-snap-target="{_e(sheet.get("auto_snap_target", ""))}"
      data-forbidden-auto-snap="{_e(sheet.get("forbidden_auto_snap", ""))}"
      data-touch-target-min-height="{_e(sheet.get("touch_target_min_height", ""))}"
      data-receipts-strip-position="{_e(sheet.get("receipts_strip_position", ""))}"
      aria-hidden="{visible == "false"}">
    </aside>"""


def _render_keyboard_shortcuts(shortcuts: dict) -> str:
    bindings = shortcuts.get("key_bindings") or {}
    if not bindings:
        return ""
    rows = "".join(
        (
            '<span class="shortcut-hint" data-testid="workspace-shortcut" '
            f'data-intent="{_e(intent)}" data-key="{_e(key)}">{_e(key)}</span>'
        )
        for intent, key in bindings.items()
    )
    return f"""
        <div
          class="shortcut-map"
          data-testid="workspace-shortcut-map"
          data-variant="{_e(shortcuts.get("variant", ""))}"
          data-rail-state="{_e(shortcuts.get("rail_state", ""))}"
          data-ignore-input-focus="true">
          {rows}
        </div>"""


def _render_find_mode(candidates: list[dict], *, payload_available: bool = False) -> str:
    if not candidates:
        state_value = "empty" if payload_available else "unavailable"
        affordance_status = "read-only" if payload_available else "unavailable"
        testid = "find-empty-state" if payload_available else "find-unavailable-state"
        copy = (
            "Find returned no candidates for this note. This is an empty read-side result, not an action."
            if payload_available
            else "Find is unavailable because no backend candidate payload is available yet."
        )
        return """
        <section
          class="find-mode"
          data-testid="find-mode"
          data-affordance-status="{affordance_status}"
          data-capability="find">
          <div class="rail-state-row">
            <span class="rail-state-label">Find</span>
            <span class="rail-state-value">{state_value}</span>
          </div>
          <div class="find-unavailable" data-testid="{testid}">
            {copy}
          </div>
        </section>""".format(
            affordance_status=affordance_status,
            state_value=state_value,
            testid=testid,
            copy=copy,
        )
    rows: list[str] = []
    for candidate in candidates:
        handoff = ""
        handoff_status = str(candidate.get("panel_handoff_status") or "unavailable")
        if handoff_status not in {"read-only", "staged", "actionable", "unavailable"}:
            handoff_status = "unavailable"
        if candidate.get("panel_handoff", True):
            handoff = (
                '<button type="button" class="find-panel-handoff" '
                'data-testid="find-panel-handoff" '
                'data-intent="find.panelHandoff" '
                f'data-affordance-status="{_e(handoff_status)}" '
                'data-runtime-backed="false" '
                'aria-disabled="true" disabled>'
                f"Panel {handoff_status}</button>"
            )
        citation_state = "missing" if candidate.get("citation_missing") else "available"
        rows.append(
            f"""
        <article
          class="find-candidate"
          data-testid="find-candidate"
          data-affordance-status="read-only"
          data-runtime-backed="true"
          data-candidate-id="{_e(candidate.get("candidate_id", ""))}">
          <div class="find-candidate-title">{_e(candidate.get("title", ""))}</div>
          <div class="find-candidate-snippet">{_e(candidate.get("snippet", ""))}</div>
          <div class="find-candidate-meta">
            <span
              data-testid="find-candidate-citation"
              data-citation-state="{_e(citation_state)}">
              {_e(candidate.get("citation", ""))}
            </span>
            <span data-testid="find-candidate-scope">{_e(candidate.get("scope", ""))}</span>
          </div>
          <div class="find-candidate-why" data-testid="find-candidate-why">
            {_e(candidate.get("why", ""))}
          </div>
          {handoff}
        </article>"""
        )
    return f"""
        <section
          class="find-mode"
          data-testid="find-mode"
          data-affordance-status="read-only"
          data-capability="find">
          <div class="rail-state-row">
            <span class="rail-state-label">Find</span>
            <span class="rail-state-value">{len(candidates)} candidates</span>
          </div>
          {"".join(rows)}
        </section>"""


def _render_reorient_mode(sections: dict[str, list[dict]]) -> str:
    if not any(sections.get(name) for name in sections):
        return """
        <section
          class="reorient-mode"
          data-testid="reorient-mode"
          data-affordance-status="read-only"
          data-capability="reorient">
          <div class="rail-state-row">
            <span class="rail-state-label">Reorient</span>
            <span class="rail-state-value">read-only</span>
          </div>
          <div class="reorient-empty" data-testid="reorient-empty-state">
            Reorient is available, but no orientation payload is available for this note yet.
          </div>
        </section>"""

    labels = {
        "facts": "Facts",
        "inferences": "Inferences",
        "candidates": "Candidates",
        "stale_context": "Stale context",
        "recent_deltas": "Recent deltas",
        "open_loops": "Open loops",
    }
    groups = [
        ("where-am-i", "Where am I?", ("facts", "inferences")),
        ("what-changed", "What changed?", ("recent_deltas", "stale_context")),
        ("what-next", "What next?", ("candidates", "open_loops")),
    ]
    section_html: list[str] = []
    for group_id, group_label, section_names in groups:
        rows: list[str] = []
        for name in section_names:
            items = sections.get(name) or []
            if not items:
                continue
            item_kind = {
                "facts": "fact",
                "inferences": "inference",
                "candidates": "candidate",
                "stale_context": "stale-caution",
                "recent_deltas": "recent-delta",
                "open_loops": "open-loop",
            }[name]
            for item in items:
                handoff = ""
                if item.get("panel_handoff"):
                    handoff = (
                        '<button type="button" class="reorient-panel-handoff" '
                        'data-testid="reorient-panel-handoff" '
                        'data-intent="reorient.panelHandoff" '
                        'data-affordance-status="read-only" '
                        'data-runtime-backed="false" '
                        'aria-disabled="true" disabled>'
                        "Panel handoff candidate</button>"
                    )
                rows.append(
                    f"""
              <li
                class="reorient-item"
                data-testid="reorient-item"
                data-reorient-section="{_e(name)}"
                data-reorient-kind="{_e(item_kind)}">
                <span class="reorient-kind" data-testid="reorient-kind">{_e(labels[name])}</span>
                <span class="reorient-item-label">{_e(item.get("label", ""))}</span>
                <a
                  class="reorient-source"
                  data-testid="reorient-source-link"
                  href="#"
                  data-source-link="{_e(item.get("source_link", ""))}">
                  {_e(item.get("source_link", ""))}
                </a>
                {handoff}
              </li>"""
                )
        section_html.append(
            f"""
            <section
              class="reorient-section"
              data-testid="reorient-section"
              data-reorient-group="{_e(group_id)}">
              <div class="reorient-section-title">{_e(group_label)}</div>
              <ul class="reorient-list">{"".join(rows)}</ul>
            </section>"""
        )
    return f"""
        <section
          class="reorient-mode"
          data-testid="reorient-mode"
          data-affordance-status="read-only"
          data-capability="reorient">
          <div class="rail-state-row">
            <span class="rail-state-label">Reorient</span>
            <span class="rail-state-value">read-only</span>
          </div>
          {"".join(section_html)}
        </section>"""


def _render_resurface_mode(candidates: list[dict], *, degraded: bool = False) -> str:
    if not candidates:
        affordance_status = "unavailable" if degraded else "read-only"
        state_label = "degraded" if degraded else "empty"
        state_testid = "resurface-degraded-state" if degraded else "resurface-empty-state"
        state_copy = (
            "Resurface is degraded because the runtime reported degraded guard state; "
            "no candidate payload is actionable here."
            if degraded
            else "No Resurface candidates are available for this note. Nothing needs action here."
        )
        return f"""
        <section
          class="resurface-mode"
          data-testid="resurface-mode"
          data-affordance-status="{affordance_status}"
          data-capability="resurface">
          <div class="rail-state-row">
            <span class="rail-state-label">Resurface</span>
            <span class="rail-state-value">{state_label}</span>
          </div>
          <div class="resurface-empty" data-testid="{state_testid}">
            {state_copy}
          </div>
        </section>"""
    rows: list[str] = []
    for candidate in candidates:
        signals = "".join(
            (
                '<span class="resurface-signal" data-testid="resurface-signal">'
                f"{_e(signal)}</span>"
            )
            for signal in candidate.get("signal_labels", [])
        )
        actions = "".join(
            (
                '<button type="button" class="resurface-action" '
                f'data-testid="resurface-action-{intent}" '
                f'data-intent="resurface.{intent}" '
                'data-affordance-status="unavailable" '
                'data-runtime-backed="false" '
                'data-persistence-backed="false" '
                'aria-disabled="true" disabled>'
                f"{label} unavailable (no persistence)</button>"
            )
            for intent, label in (
                ("dismiss", "Dismiss"),
                ("snooze", "Snooze"),
                ("pin", "Pin"),
            )
        )
        rows.append(
            f"""
          <article
            class="resurface-candidate"
            data-testid="resurface-candidate"
            data-affordance-status="read-only"
            data-runtime-backed="true"
            data-candidate-id="{_e(candidate.get("candidate_id", ""))}">
            <div class="resurface-title" data-testid="resurface-candidate-label">
              {_e(candidate.get("label", ""))}
            </div>
            <div class="resurface-why" data-testid="resurface-why-now">
              {_e(candidate.get("why_now", ""))}
            </div>
            <div class="resurface-relation" data-testid="resurface-relation">
              {_e(candidate.get("relation_to_active_artifact", ""))}
            </div>
            <a
              class="resurface-source"
              data-testid="resurface-source-link"
              href="#"
              data-source-link="{_e(candidate.get("source_link", ""))}">
              {_e(candidate.get("source_link", ""))}
            </a>
            <div class="resurface-signals">{signals}</div>
            <div class="resurface-actions">{actions}</div>
          </article>"""
        )
    return f"""
        <section
          class="resurface-mode"
          data-testid="resurface-mode"
          data-affordance-status="read-only"
          data-capability="resurface">
          <div class="rail-state-row">
            <span class="rail-state-label">Resurface</span>
            <span class="rail-state-value">low-pressure</span>
          </div>
          {"".join(rows)}
        </section>"""


def _render_act_mode(
    *,
    proposals: list[dict],
    response: dict,
    writeguard_blocked: bool,
) -> str:
    if not proposals and not response:
        return ""

    proposal_rows: list[str] = []
    for proposal in proposals:
        evidence = proposal.get("evidence") or {}
        proposal_id = _e(proposal.get("proposal_id", ""))
        artifact_id = _e(proposal.get("artifact_id", ""))
        affordances = proposal.get("affordances") or {}
        proposal_status = str(proposal.get("status") or "staged")
        proposal_available = proposal_status in {"staged", "corrected"} and not writeguard_blocked
        proposal_affordance_status = "active" if proposal_available else "blocked" if writeguard_blocked else "unavailable"
        actions = "".join(
            (
                '<button type="button" class="act-panel-action" '
                f'data-testid="act-{label}" '
                f'data-panel-action="{_e(label)}" '
                'data-api-method="POST" '
                'data-api-path="/api/panel/confirm" '
                f'data-affordance-status="{proposal_affordance_status}" '
                f'data-proposal-id="{proposal_id}" '
                f'data-artifact-id="{artifact_id}" '
                'data-writeguard-bypass="false">'
                f"{_e(label)}</button>"
            )
            for label in ("confirm", "correct", "reject")
            if affordances.get(label, True) and proposal_available
        )
        if not proposal_available:
            actions = (
                '<span class="act-panel-unavailable" '
                'data-testid="act-panel-unavailable" '
                f'data-affordance-status="{proposal_affordance_status}">'
                f"{_e(proposal_status)} proposal unavailable</span>"
            )
        proposal_rows.append(
            f"""
          <article
            class="act-proposal"
            data-testid="act-proposal-review"
            data-affordance-status="{proposal_affordance_status}"
            data-proposal-id="{proposal_id}"
            data-artifact-id="{artifact_id}">
            <div class="act-proposal-title">{_e(proposal.get("description", ""))}</div>
            <div class="act-bundle" data-testid="act-action-bundle-context">
              <span>{_e(evidence.get("trigger_summary", ""))}</span>
              <span>{_e(evidence.get("action_class", ""))}</span>
              <span>{_e(evidence.get("cognition_route", ""))}</span>
            </div>
            <div class="act-flow" data-testid="act-governed-flow">
              intent &rarr; propose &rarr; decide &rarr; execute &rarr; receipt
            </div>
            <div class="act-actions">{actions}</div>
          </article>"""
        )

    receipt_html = ""
    if response:
        receipt = response.get("receipt") or {}
        block_reason = response.get("block_reason") or {}
        receipt_message = (
            receipt.get("message")
            or receipt.get("outcome")
            or block_reason.get("message")
            or response.get("outcome")
            or response.get("status")
            or ""
        )
        receipt_html = f"""
          <div class="act-receipt" data-testid="act-durable-receipt">
            <span data-testid="act-receipt-status">{_e(response.get("status", ""))}</span>
            <span data-testid="act-receipt-outcome">{_e(response.get("outcome", ""))}</span>
            <span>{_e(receipt_message)}</span>
          </div>"""

    return f"""
        <section
          class="act-mode"
          data-testid="act-mode"
          data-authority-surface="panel"
          data-affordance-status="{'blocked' if writeguard_blocked else 'active'}"
          data-writeguard-bypass="false">
          <div class="rail-state-row">
            <span class="rail-state-label">Act</span>
            <span class="rail-state-value">Panel confirm path</span>
          </div>
          {"".join(proposal_rows)}
          {receipt_html}
        </section>"""


def _render_suggestion_cards(cards: list[dict]) -> str:
    rows: list[str] = []
    for card in cards:
        intents = card.get("available_intents") or []
        actions = "".join(
            (
                '<button type="button" class="suggestion-action" '
                f'data-intent="{_e(intent)}">{_e(_suggestion_action_label(intent))}</button>'
            )
            for intent in intents
        )
        role = f' role="{_e(card.get("aria_role"))}"' if card.get("aria_role") else ""
        notice = ""
        if card.get("classification_notice"):
            notice = (
                '<div class="suggestion-card-notice" '
                'data-testid="suggestion-card-classification">'
                + _e(card.get("classification_notice"))
                + "</div>"
            )
        denial = ""
        if card.get("denial_reason"):
            denial = (
                '<div class="suggestion-card-denial" data-testid="suggestion-card-denial">'
                + _e(card.get("denial_reason"))
                + "</div>"
            )
        rows.append(
            f"""
        <div
          class="suggestion-card"
          data-testid="suggestion-card"
          data-variant="{_e(card.get("data_variant", ""))}"
          data-suggestion-id="{_e(card.get("data_suggestion_id", ""))}"{role}>
          <div class="suggestion-card-title">{_e(card.get("title", ""))}</div>
          <div class="suggestion-card-preview">{_e(card.get("preview_text", ""))}</div>
          {notice}
          {denial}
          <div class="suggestion-card-actions">{actions}</div>
        </div>"""
        )
    return "\n".join(rows)


def _render_governance_receipts(receipts: list[dict]) -> str:
    rows: list[str] = []
    for receipt in receipts:
        rows.append(
            f"""
        <button
          type="button"
          class="receipt-pill"
          data-testid="{_e(receipt.get("data_testid", "receipt-pill"))}"
          data-receipt-id="{_e(receipt.get("data_receipt_id", ""))}"
          data-suggestion-id="{_e(receipt.get("data_suggestion_id", ""))}"
          data-artifact-id="{_e(receipt.get("data_artifact_id", ""))}"
          data-status="{_e(receipt.get("data_status", ""))}"
          data-intent="{_e(receipt.get("data_intent", "governance.openReceipt"))}"
          aria-label="{_e(receipt.get("aria_label", ""))}">
          <span class="receipt-pill-label">{_e(receipt.get("label", ""))}</span>
          <span class="receipt-pill-time">{_e(receipt.get("display_timestamp", ""))}</span>
        </button>"""
        )
    if not rows:
        return ""
    return f"""
        <div class="receipts-strip" data-testid="receipts-strip" aria-live="polite">
          {"".join(rows)}
        </div>"""


def _suggestion_action_label(intent: str) -> str:
    return {
        "suggestion.apply": "Apply",
        "suggestion.discard": "Discard",
        "suggestion.inspect": "Inspect",
        "governance.queue": "Queue",
        "blocked.acknowledge": "Acknowledge",
    }.get(intent, intent)


def _render_suggested_insertions(insertions: list[dict]) -> str:
    rows: list[str] = []
    for insertion in insertions:
        if not insertion.get("is_visible", True):
            continue
        rows.append(
            f"""
        <ins
          class="suggested-insertion"
          data-testid="suggested-insertion-block"
          data-suggestion-id="{_e(insertion.get("data_suggestion_id", ""))}"
          data-state="{_e(insertion.get("data_state", ""))}"
          aria-label="{_e(insertion.get("aria_label", ""))}">
          <span class="suggested-insertion-label">{_e(insertion.get("label", ""))}</span>
          <span class="suggested-insertion-text">{_e(insertion.get("proposed_text", ""))}</span>
        </ins>"""
        )
    return "\n".join(rows)


def _render_canvas_session_controls(
    *,
    note_path: str,
    session_id: str,
    session_state: str,
    can_edit_body: bool,
    user_present: bool,
    content_hash: str,
    recovery_needed: bool,
    recovery_acknowledged: bool,
    conflict_detected: bool,
    canvas_enabled: bool,
    workspace_update_available: bool,
    workspace_update_reason: str,
    writeguard_blocked: bool,
    session_log_path: str,
    undo_available: bool,
    applied_edit_count: int,
    undone_edit_count: int,
) -> str:
    canvas_blocked = not canvas_enabled or writeguard_blocked or (not workspace_update_available)
    start_status = "blocked" if not canvas_enabled else "experimental" if not session_id else "unavailable"
    close_status = "blocked" if not canvas_enabled else "experimental" if session_id else "unavailable"
    edit_status = "blocked" if canvas_blocked else "active" if can_edit_body else "unavailable"
    undo_status = "blocked" if canvas_blocked else "active" if undo_available else "unavailable"
    start_disabled = " disabled" if session_id or not canvas_enabled else ""
    close_disabled = "" if session_id else " disabled"
    if not canvas_enabled:
        close_disabled = " disabled"
    edit_disabled = "" if can_edit_body and not canvas_blocked else " disabled"
    undo_disabled = "" if undo_available and not canvas_blocked else " disabled"
    edit_api_path = f"/api/canvas/sessions/{session_id}/edits" if session_id else ""
    undo_api_path = f"/api/canvas/sessions/{session_id}/edits/last" if session_id else ""
    present_text = "user present" if user_present else "user not present"
    log_text = session_log_path or "no session log"
    undo_state_html = (
        '<span class="canvas-undo-state" data-testid="workspace-canvas-undo-state">'
        + ("Undo available" if undo_available else "No undo available")
        + "</span>"
    )
    composer_html = ""
    if can_edit_body and not canvas_blocked:
        composer_html = f"""
          <form
            class="canvas-body-edit-composer"
            data-testid="workspace-canvas-body-edit-composer"
            data-affordance-status="active"
            data-capability="canvas.applyBodyEdit"
            data-api-method="POST"
            data-api-path="{edit_api_path}"
            data-requires-preview="true">
            <label for="canvas_new_body">Body edit draft</label>
            <textarea
              id="canvas_new_body"
              name="new_body"
              data-testid="workspace-canvas-body-edit-textarea"
              aria-label="Body edit draft"></textarea>
            <input type="hidden" name="content_hash" value="{content_hash}">
            <div
              class="canvas-body-edit-preview"
              data-testid="workspace-canvas-body-edit-preview"
              data-preview-state="required">
              Preview required before apply. Runtime owns the writer path.
            </div>
            <div class="canvas-body-edit-actions">
              <button
                type="button"
                data-testid="workspace-canvas-edit-discard"
                data-affordance-status="active"
                data-runtime-backed="false"
                data-api-method="LOCAL">Discard draft</button>
            </div>
          </form>"""
    else:
        unavailable_copy = "Body edit composer unavailable until Canvas has an active editable session."
        if not workspace_update_available:
            unavailable_copy = (
                "Body edit composer disabled by workspace update capability: "
                f"{workspace_update_reason}."
            )
        composer_html = """
          <div
            class="canvas-body-edit-unavailable"
            data-testid="workspace-canvas-body-edit-unavailable"
            data-affordance-status="blocked">
            """ + unavailable_copy + """
          </div>"""
    recovery_api_path = f"/api/canvas/sessions/{session_id}/recovery/ack" if session_id else ""
    recovery_html = ""
    if conflict_detected:
        recovery_state = "acknowledged" if recovery_acknowledged else "needs acknowledgement"
        recovery_reason = "recovery needed" if recovery_needed else "paused/interrupted"
        recovery_html = f"""
          <div class="canvas-recovery-conflict" data-testid="workspace-canvas-recovery-conflict">
            <span data-testid="workspace-canvas-conflict-session-state">{session_state}</span>
            <span>{recovery_reason}</span>
            <span data-testid="workspace-canvas-recovery-state">{recovery_state}</span>
            <span data-testid="workspace-canvas-recovery-copy">
              Acknowledge recovery before applying body edits.
            </span>
            <button
              type="button"
              data-testid="workspace-canvas-recovery-ack"
              data-api-method="LOCAL"
              data-api-path="{recovery_api_path}">Acknowledge</button>
          </div>"""
    return f"""
        <div class="canvas-controls" data-testid="workspace-canvas-session-controls">
          <button
            type="button"
            data-testid="workspace-canvas-start"
            data-affordance-status="{start_status}"
            data-capability="canvas.openSession"
            data-api-method="POST"
            data-api-path="/api/canvas/sessions"
            data-note-path="{note_path}"{start_disabled}>Start</button>
          <button
            type="button"
            data-testid="workspace-canvas-close"
            data-affordance-status="{close_status}"
            data-capability="canvas.closeSession"
            data-api-method="DELETE"
            data-api-path="/api/canvas/sessions/{session_id}"{close_disabled}>Close</button>
          <button
            type="button"
            data-testid="workspace-canvas-edit-submit"
            data-affordance-status="{edit_status}"
            data-capability="canvas.applyBodyEdit"
            data-api-method="POST"
            data-api-path="{edit_api_path}"
            data-content-hash="{content_hash}"{edit_disabled}>Apply body edit</button>
          <button
            type="button"
            data-testid="workspace-canvas-undo"
            data-affordance-status="{undo_status}"
            data-capability="canvas.undoBodyEdit"
            data-api-method="DELETE"
            data-api-path="{undo_api_path}"{undo_disabled}>Undo</button>
          <span class="canvas-presence" data-testid="workspace-canvas-user-present">{present_text}</span>
          {composer_html}
          {recovery_html}
          {undo_state_html}
          <div class="canvas-provenance" data-testid="workspace-canvas-provenance">
            <span class="canvas-provenance-label">log</span>
            <code data-testid="workspace-canvas-session-log-path">{log_text}</code>
            <span data-testid="workspace-canvas-edit-count">{applied_edit_count} edit{'s' if applied_edit_count != 1 else ''}</span>
            <span data-testid="workspace-canvas-undone-count">{undone_edit_count} undone</span>
          </div>
        </div>"""


def _render_panel_proposal_rows(
    proposals: list[dict],
    *,
    writeguard_blocked: bool,
) -> str:
    if not proposals:
        return ""

    rows: list[str] = []
    for proposal in proposals:
        evidence = proposal.get("evidence") or {}
        affordances = proposal.get("affordances") or {}
        proposal_status = str(proposal.get("status") or "staged")
        proposal_available = proposal_status in {"staged", "corrected"} and not writeguard_blocked
        affordance_status = "active" if proposal_available else "blocked" if writeguard_blocked else "unavailable"
        enabled_affordances = [
            label
            for label in ("confirm", "correct", "reject")
            if affordances.get(label) and proposal_available
        ]
        proposal_id = _e(proposal.get("proposal_id", ""))
        artifact_id = _e(proposal.get("artifact_id", ""))
        buttons = "".join(
            (
                '<button type="button" class="panel-proposal-action" '
                'data-testid="workspace-panel-action" '
                f'data-panel-action="{_e(label)}" '
                f'data-affordance-status="{affordance_status}" '
                f'data-proposal-id="{proposal_id}" '
                f'data-artifact-id="{artifact_id}" '
                'data-runtime-backed="true" '
                'data-api-method="POST" '
                'data-api-path="/api/panel/confirm">'
                f"{_e(label)}</button>"
            )
            for label in enabled_affordances
        )
        if not proposal_available:
            buttons = (
                '<span class="panel-proposal-unavailable" '
                'data-testid="workspace-panel-proposal-unavailable" '
                f'data-affordance-status="{affordance_status}">'
                f"{_e(proposal_status)} proposal unavailable</span>"
            )
        rows.append(
            f"""
        <div
          class="panel-proposal-row"
          data-testid="workspace-panel-proposal-row"
          data-affordance-status="{affordance_status}"
          data-proposal-id="{proposal_id}"
          data-artifact-id="{artifact_id}">
          <div class="panel-proposal-title">{_e(proposal.get("description", ""))}</div>
          <div class="panel-proposal-meta">
            <span data-testid="workspace-panel-proposal-id">{proposal_id}</span>
            <span data-testid="workspace-panel-artifact-id">{artifact_id}</span>
            <span>{_e(proposal.get("status", ""))}</span>
          </div>
          <details class="panel-proposal-evidence" data-testid="workspace-panel-evidence" open>
            <summary data-testid="workspace-panel-evidence-disclosure">Evidence</summary>
            <span data-testid="workspace-panel-trigger-summary">{_e(evidence.get("trigger_summary", ""))}</span>
            <span data-testid="workspace-panel-action-class">{_e(evidence.get("action_class", ""))}</span>
            <span data-testid="workspace-panel-cognition-route">{_e(evidence.get("cognition_route", ""))}</span>
          </details>
          <div class="panel-proposal-affordances">
            {buttons}
          </div>
        </div>"""
        )
    return "\n".join(rows)


def _render_panel_confirm_response(response: dict) -> str:
    if not response:
        return ""
    status = _e(response.get("status", ""))
    receipt = response.get("receipt") or {}
    block_reason = response.get("block_reason") or {}
    receipt_html = ""
    if status in {"executed", "logged"} and receipt:
        corrected_badge = ""
        if receipt.get("message") == "corrected" or receipt.get("corrected") or response.get("corrected"):
            corrected_badge = (
                '<span class="panel-confirm-corrected" '
                'data-testid="workspace-panel-corrected-receipt">corrected</span>'
            )
        inverse_html = ""
        inverse_action = receipt.get("inverse_action") or receipt.get("inverse_action_id")
        if inverse_action:
            inverse_html = (
                '<div class="panel-confirm-inverse" '
                'data-testid="workspace-panel-inverse-action" '
                'data-affordance-status="read-only" '
                'data-runtime-backed="false">'
                + _e(inverse_action)
                + "</div>"
            )
        receipt_html = f"""
          <div
            class="panel-confirm-receipt"
            data-testid="workspace-panel-receipt"
            data-receipt-persistence="durable-runtime-projection">
            <span data-testid="workspace-panel-receipt-outcome">{_e(receipt.get("outcome") or response.get("outcome") or status)}</span>
            <span data-testid="workspace-panel-receipt-message">{_e(receipt.get("message") or receipt.get("action_taken") or status)}</span>
            <span data-testid="workspace-panel-receipt-timestamp">{_e(receipt.get("timestamp") or response.get("timestamp") or "timestamp unavailable")}</span>
            {corrected_badge}
            {inverse_html}
          </div>"""
    blocked_html = ""
    if status == "blocked" and block_reason:
        message = str(block_reason.get("message") or "")
        if block_reason.get("gate") == "same-turn" or "same-turn" in message.lower():
            message = (
                "Same-turn confirmation is not allowed. "
                "The proposal must be confirmed in a later interaction."
            )
        blocked_html = f"""
          <div class="panel-confirm-blocked" data-testid="workspace-panel-blocked-reason">
            <span data-testid="workspace-panel-block-gate">{_e(block_reason.get("gate") or "unknown")}</span>
            <span data-testid="workspace-panel-block-message">{_e(message)}</span>
          </div>"""
    return f"""
        <div class="panel-confirm-response" data-testid="workspace-panel-confirm-response">
          <span data-testid="workspace-panel-confirm-status">{status}</span>
          {receipt_html}
          {blocked_html}
        </div>"""


def _error_detail(error: str) -> dict:
    if not error.startswith("HTTP "):
        return {}
    _, _, maybe_json = error.partition(": ")
    if not maybe_json:
        return {}
    try:
        payload = json.loads(maybe_json)
    except json.JSONDecodeError:
        return {}
    detail = payload.get("detail")
    return detail if isinstance(detail, dict) else {}


def _render_error_section(error: str) -> str:
    """Render a visible error state using Yggdrasil destructive tokens."""
    detail = _error_detail(error)
    error_kind = str(detail.get("error") or "")
    if error_kind == "note_not_found":
        note_path = _e(detail.get("note_path") or "")
        message = _e(detail.get("message") or "No note exists for the requested note_path")
        return f"""
  <div class="error-state note-not-found-state" data-testid="workspace-note-not-found-state">
    <span class="error-label">Note not found</span>
    <span class="error-message">
      <code>{note_path}</code> — {message}. Check the runtime-relative path and load again.
    </span>
  </div>"""
    runtime_unavailable = any(
        marker in error.lower()
        for marker in ("connection refused", "timed out", "timeout", "network")
    )
    runtime_label = "Runtime unavailable" if runtime_unavailable else "API Error"
    runtime_marker = (
        '<span data-testid="workspace-runtime-unavailable-state"></span>'
        if runtime_unavailable
        else ""
    )
    return f"""
  <div class="error-state" data-testid="workspace-error-state" data-error-kind="{'runtime-unavailable' if runtime_unavailable else 'api-error'}">
    <span class="error-label">{runtime_label}</span>
    {runtime_marker}
    <span class="error-message"><code>{_e(error)}</code></span>
  </div>"""


def render_index_html(
    *,
    api_base_url: str,
    note_path: str = "",
    fields: Optional[dict] = None,
    error: str = "",
    production_profile: bool = False,
) -> str:
    """Render the workspace dev page as a Companion UI visual shell.

    Pure function — no network calls, no file I/O.
    All user-supplied values are HTML-escaped.

    This is the first visual-alignment pass (not production UI). It uses
    Yggdrasil design tokens and the workspace region contract from
    real_note_workspace_shell.py. Canvas body-edit and Panel execution
    are not implemented; the agent rail is a placeholder.
    """
    content_section = ""
    if error:
        content_section = _render_error_section(error)
    elif fields is not None:
        content_section = _render_note_section(fields)
    title_suffix = "PROD" if production_profile else "DEV"
    dev_chip = "" if production_profile else '<span class="dev-chip">DEV / not production</span>'
    production_static_link = (
        '<link rel="stylesheet" href="/static/companion-workspace.css">'
        if production_profile
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Companion UI — Real-Note Workspace [{title_suffix}]</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;1,400&family=Space+Grotesk:wght@300;400;500;600&display=swap" rel="stylesheet">
  {production_static_link}
  <style>
    /* Yggdrasil design tokens (subset inlined for offline resilience) */
    :root {{
      --bg-base:       #070b12;
      --bg-surface:    #0c1220;
      --bg-raised:     #111a2e;
      --bg-overlay:    #162038;
      --fg-1:          #dce8f0;
      --fg-2:          #7a9ab8;
      --fg-3:          #3d5570;
      --border:        #152030;
      --border-strong: #1e3050;
      --border-focus:  #00d4e8;
      --accent:        #d4a843;
      --cyan:          #00d4e8;
      --cyan-muted:    #001e28;
      --agent:         #4a9eff;
      --agent-muted:   #051228;
      --destructive:      #ff3d3d;
      --destructive-muted:#160404;
      --font-display:  'EB Garamond', Georgia, serif;
      --font-ui:       'Space Grotesk', system-ui, sans-serif;
      --font-mono:     'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
      --text-xs:   0.6875rem;
      --text-sm:   0.8125rem;
      --text-base: 0.9375rem;
      --text-xl:   1.5rem;
      --text-2xl:  2rem;
      --radius-sm: 2px;
      --radius-md: 4px;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ font-size: 16px; -webkit-font-smoothing: antialiased; }}
    body {{
      background: var(--bg-base);
      background-image:
        linear-gradient(rgba(0,212,232,0.022) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,212,232,0.022) 1px, transparent 1px);
      background-size: 48px 48px;
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-base);
      line-height: 1.55;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}

    /* ---- Top bar ---- */
    .topbar {{
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px 20px;
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .topbar-api {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-3);
      flex: 1;
      min-width: 0;
    }}
    .topbar-api .api-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      flex-shrink: 0;
    }}
    .topbar-api .api-url {{
      color: var(--fg-2);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .dev-chip {{
      display: inline-block;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.07em;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: var(--radius-sm);
      background: rgba(240,144,48,0.08);
      border: 1px solid rgba(240,144,48,0.35);
      color: #f09030;
      flex-shrink: 0;
    }}

    /* ---- Load form ---- */
    .load-bar {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 20px;
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .load-bar label {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      flex-shrink: 0;
    }}
    .load-bar input[type=text] {{
      flex: 1;
      min-width: 0;
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      padding: 5px 10px;
      outline: none;
    }}
    .load-bar input[type=text]:focus {{
      border-color: var(--border-focus);
      box-shadow: 0 0 0 1px var(--border-focus);
    }}
    .load-bar button {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 5px 14px;
      cursor: pointer;
      flex-shrink: 0;
    }}
    .load-bar button:hover {{ border-color: var(--cyan); color: var(--cyan); }}

    /* ---- Error state ---- */
    .error-state {{
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin: 20px;
      padding: 12px 16px;
      background: var(--destructive-muted);
      border: 1px solid rgba(255,61,61,0.3);
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
    }}
    .error-label {{
      color: var(--destructive);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      font-size: var(--text-xs);
      flex-shrink: 0;
    }}
    .error-message {{ color: var(--fg-2); }}
    .error-message code {{ background: none; border: none; padding: 0; color: var(--fg-1); }}
    .note-not-found-state {{
      background: rgba(212,168,67,0.08);
      border-color: rgba(212,168,67,0.35);
    }}
    .note-not-found-state .error-label {{ color: var(--accent); }}

    /* ---- Workspace layout ---- */
    .workspace-layout {{
      display: flex;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }}
    .workspace-main {{
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .runtime-safety-strip {{
      align-items: center;
      background: rgba(17,26,46,0.65);
      border-bottom: 1px solid var(--border);
      color: var(--fg-2);
      display: flex;
      flex-wrap: wrap;
      gap: 6px 12px;
      padding: 8px 24px;
    }}
    .safety-item {{
      align-items: baseline;
      display: inline-flex;
      gap: 5px;
      min-width: 0;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .safety-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .safety-item code {{
      background: none;
      border: none;
      color: var(--fg-2);
      max-width: 18ch;
      overflow: hidden;
      padding: 0;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .safety-sep {{ color: var(--border-strong); }}

    /* ---- Note header ---- */
    .note-header {{
      padding: 20px 24px 12px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .note-title {{
      font-family: var(--font-display);
      font-size: var(--text-2xl);
      font-weight: 400;
      line-height: 1.2;
      color: var(--fg-1);
      margin-bottom: 8px;
    }}
    .note-provenance {{
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px 8px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-3);
    }}
    .prov-item {{ display: inline-flex; align-items: baseline; gap: 4px; }}
    .artifact-identity-pill, .content-hash-pill {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 2px 6px;
    }}
    .artifact-identity-pill[data-identity-state^="unresolved"] {{
      border-color: rgba(212,168,67,0.35);
    }}
    .identity-meta {{
      color: var(--fg-3);
      font-size: var(--text-xs);
    }}
    .identity-caution {{
      background: rgba(212,168,67,0.08);
      border: 1px solid rgba(212,168,67,0.35);
      border-radius: var(--radius-md);
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      margin-top: 10px;
      padding: 8px 10px;
    }}
    .prov-label {{
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--fg-3);
    }}
    .prov-item code {{
      background: none;
      border: none;
      padding: 0;
      font-size: var(--text-xs);
      color: var(--fg-2);
    }}
    .prov-sep {{ color: var(--border-strong); }}

    /* ---- Note body ---- */
    .note-body {{
      flex: 1;
      overflow-y: auto;
      padding: 24px;
    }}
    .note-body-content {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      margin: 0 auto;
      max-width: 920px;
      min-height: 100%;
      padding: 28px 32px;
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      color: var(--fg-1);
      line-height: 1.75;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .suggested-insertion {{
      background: rgba(212,168,67,0.08);
      border-left: 3px solid var(--accent);
      color: var(--fg-1);
      display: block;
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      margin-top: 12px;
      padding: 10px 12px;
      text-decoration: none;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .suggested-insertion-label {{
      color: var(--accent);
      display: block;
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}

    /* ---- Agent rail ---- */
    .agent-rail {{
      width: 280px;
      flex-shrink: 0;
      background: var(--bg-surface);
      border-left: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .rail-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .rail-label {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--fg-3);
    }}
    .rail-badge {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      padding: 1px 7px;
      border-radius: var(--radius-sm);
      background: var(--agent-muted);
      border: 1px solid rgba(74,158,255,0.2);
      color: var(--agent);
      letter-spacing: 0.04em;
    }}
    .rail-placeholder-body {{
      flex: 1;
      padding: 16px;
      font-size: var(--text-sm);
      color: var(--fg-3);
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .rail-state-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-style: normal;
    }}
    .rail-state-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .rail-state-value, .rail-state-count {{
      color: var(--fg-2);
    }}
    .rail-alert {{
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-style: normal;
      padding: 8px 10px;
    }}
    .rail-alert-blocked {{
      background: var(--destructive-muted);
      border: 1px solid rgba(255,61,61,0.3);
      color: var(--destructive);
    }}
    .rail-alert-muted {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      color: var(--fg-2);
    }}
    .panel-message {{
      border-left: 2px solid var(--accent);
      color: var(--fg-2);
      font-size: var(--text-sm);
      padding-left: 10px;
    }}
    .canvas-controls {{
      display: grid;
      gap: 6px;
      grid-template-columns: 1fr 1fr;
    }}
    .canvas-controls button {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      letter-spacing: 0.04em;
      padding: 5px 8px;
      text-transform: uppercase;
    }}
    .canvas-controls button:disabled {{
      color: var(--fg-3);
      cursor: not-allowed;
      opacity: 0.55;
    }}
    .canvas-presence {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      grid-column: 1 / -1;
    }}
    .canvas-body-edit-composer, .canvas-body-edit-unavailable {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      gap: 7px;
      grid-column: 1 / -1;
      padding: 10px;
    }}
    .canvas-body-edit-composer label, .canvas-undo-state {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .canvas-body-edit-composer textarea {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      min-height: 108px;
      padding: 8px 10px;
      resize: vertical;
      width: 100%;
    }}
    .canvas-body-edit-preview, .canvas-body-edit-unavailable {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .canvas-body-edit-actions {{
      display: flex;
      justify-content: flex-end;
    }}
    .canvas-undo-state {{
      grid-column: 1 / -1;
      letter-spacing: 0;
      text-transform: none;
    }}
    .canvas-recovery-conflict {{
      background: var(--destructive-muted);
      border: 1px solid rgba(255,61,61,0.3);
      border-radius: var(--radius-md);
      color: var(--destructive);
      display: flex;
      flex-direction: column;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      gap: 5px;
      grid-column: 1 / -1;
      padding: 8px 10px;
    }}
    .canvas-recovery-conflict button {{
      background: var(--bg-raised);
      border: 1px solid rgba(255,61,61,0.35);
      color: var(--fg-1);
      width: 100%;
    }}
    .canvas-provenance {{
      color: var(--fg-3);
      display: flex;
      flex-direction: column;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      gap: 2px;
      grid-column: 1 / -1;
      min-width: 0;
    }}
    .canvas-provenance code {{
      color: var(--fg-2);
      overflow-wrap: anywhere;
    }}
    .canvas-provenance-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .suggestion-flow {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 10px;
    }}
    .suggestion-composer-state, .suggestion-transition {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .suggestion-transitions {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .suggestion-card {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding: 10px;
    }}
    .suggestion-card[data-variant="blocked"] {{
      border-color: rgba(255,61,61,0.3);
    }}
    .suggestion-card-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
    }}
    .suggestion-card-preview, .suggestion-card-notice, .suggestion-card-denial {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .suggestion-card-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .suggestion-action {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      padding: 4px 7px;
      text-transform: uppercase;
    }}
    .shortcut-map {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 8px 10px;
    }}
    .shortcut-hint {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      min-height: 20px;
    }}
    .portrait-sheet {{
      display: none;
    }}
    .find-mode, .find-candidate {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px;
    }}
    .find-candidate-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
    }}
    .find-candidate-snippet, .find-candidate-why, .find-candidate-meta {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .find-candidate-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .find-panel-handoff {{
      align-self: flex-start;
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-size: var(--text-xs);
      padding: 4px 7px;
      text-transform: uppercase;
    }}
    @media (max-width: 899px) {{
      .workspace-shell {{
        padding-bottom: 60px;
      }}
      .agent-rail {{
        display: none;
      }}
      .portrait-sheet {{
        background: var(--bg-surface);
        border-top: 1px solid var(--border);
        bottom: 0;
        display: block;
        left: 0;
        min-height: 44px;
        position: fixed;
        right: 0;
        z-index: 20;
      }}
      .portrait-sheet[data-current-snap="peek"] {{
        height: 60px;
      }}
      .portrait-sheet[data-current-snap="half"] {{
        height: 50vh;
      }}
      .portrait-sheet[data-current-snap="full"] {{
        height: calc(100vh - 64px);
      }}
      .portrait-sheet[data-current-snap="closed"] {{
        display: none;
      }}
    }}
    @media (min-width: 900px) {{
      .agent-rail[data-layout-desktop="side-rail"] {{
        display: flex;
      }}
    }}
    .panel-proposal-row {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 10px;
    }}
    .panel-proposal-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
      font-style: normal;
    }}
    .panel-proposal-meta, .panel-proposal-evidence, .panel-proposal-affordances {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-style: normal;
    }}
    .panel-proposal-action {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      padding: 4px 7px;
      text-transform: uppercase;
    }}
    .panel-confirm-response {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      gap: 5px;
      padding: 10px;
    }}
    .panel-confirm-receipt {{ color: var(--fg-1); }}
    .panel-confirm-blocked {{ color: var(--destructive); }}
    /* Vault note browser overlay */
    .vault-browser-overlay {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(7, 11, 18, 0.85);
      z-index: 1000;
      align-items: flex-start;
      justify-content: center;
      padding: 40px 16px;
    }}
    .vault-browser-overlay.open {{ display: flex; }}
    .vault-browser-panel {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-height: 80vh;
      max-width: 640px;
      overflow: hidden;
      padding: 20px;
      width: 100%;
    }}
    .vault-browser-header {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }}
    .vault-browser-title {{
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      font-weight: 600;
    }}
    .vault-browser-identity {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .vault-browser-close {{
      background: transparent;
      border: none;
      color: var(--fg-2);
      cursor: pointer;
      font-size: 1.2rem;
      line-height: 1;
      padding: 0 4px;
    }}
    .vault-browser-search {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      padding: 8px 12px;
      width: 100%;
    }}
    .vault-browser-list {{
      flex: 1;
      list-style: none;
      margin: 0;
      overflow-y: auto;
      padding: 0;
    }}
    .vault-browser-item {{
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 8px 4px;
    }}
    .vault-browser-item:hover {{ background: var(--bg-raised); }}
    .vault-browser-item-title {{
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
    }}
    .vault-browser-item-path {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .vault-browser-status {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-api">
      <span class="api-label">Runtime API</span>
      <span class="api-url" title="{_e(api_base_url)}">{_e(api_base_url)}</span>
    </div>
    {dev_chip}
  </div>
  <div class="load-bar">
    <form method="GET" action="/" style="display:flex;align-items:center;gap:8px;width:100%">
      <label for="note_path">note_path</label>
      <input
        type="text"
        id="note_path"
        name="note_path"
        value="{_e(note_path)}"
        placeholder="Some/Note.md"
        autocomplete="off">
      <button type="submit">Load</button>
      <button type="button"
        id="vault-browse-btn"
        data-testid="vault-browse-button"
        onclick="vaultBrowser.open()">Browse vault</button>
    </form>
  </div>
  {content_section}

  <!-- Vault note browser overlay -->
  <div class="vault-browser-overlay" id="vault-browser-overlay"
       data-testid="vault-browser-overlay" role="dialog" aria-modal="true">
    <div class="vault-browser-panel">
      <div class="vault-browser-header">
        <span class="vault-browser-title">Browse vault</span>
        <span class="vault-browser-identity" id="vault-browser-identity"
              data-testid="vault-browser-identity"></span>
        <button class="vault-browser-close" onclick="vaultBrowser.close()"
                data-testid="vault-browser-close" aria-label="Close">&times;</button>
      </div>
      <input type="text" class="vault-browser-search" id="vault-browser-search"
             data-testid="vault-browser-search"
             placeholder="Search by title or path…"
             autocomplete="off">
      <ul class="vault-browser-list" id="vault-browser-list"
          data-testid="vault-browser-list"></ul>
      <div class="vault-browser-status" id="vault-browser-status"
           data-testid="vault-browser-status"></div>
    </div>
  </div>

  <script>
  (function() {{
    var API_BASE = {repr(_e(api_base_url))};
    var overlay = document.getElementById('vault-browser-overlay');
    var list    = document.getElementById('vault-browser-list');
    var status  = document.getElementById('vault-browser-status');
    var search  = document.getElementById('vault-browser-search');
    var identity = document.getElementById('vault-browser-identity');
    var debounceTimer = null;

    function setStatus(msg) {{ status.textContent = msg; }}

    function renderNotes(notes, vaultIdentity) {{
      list.innerHTML = '';
      if (vaultIdentity && vaultIdentity.vault_name && vaultIdentity.channel) {{
        identity.textContent = vaultIdentity.vault_name + ' / ' + vaultIdentity.channel;
      }}
      if (!notes || notes.length === 0) {{
        setStatus('No notes found.');
        return;
      }}
      setStatus(notes.length + ' note' + (notes.length === 1 ? '' : 's'));
      notes.forEach(function(note) {{
        var li = document.createElement('li');
        li.className = 'vault-browser-item';
        li.setAttribute('data-note-path', note.path);
        li.innerHTML = '<span class="vault-browser-item-title">' +
          _esc(note.title) + '</span><span class="vault-browser-item-path">' +
          _esc(note.path) + '</span>';
        li.addEventListener('click', function() {{
          vaultBrowser.selectNote(note.path);
        }});
        list.appendChild(li);
      }});
    }}

    function _esc(s) {{
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }}

    function fetchNotes(q) {{
      setStatus('Loading…');
      list.innerHTML = '';
      var url = API_BASE + '/api/companion/vault/notes' + (q ? '?q=' + encodeURIComponent(q) : '');
      fetch(url)
        .then(function(r) {{
          if (!r.ok) throw new Error('API error ' + r.status);
          return r.json();
        }})
        .then(function(data) {{
          renderNotes(data.notes, data.vault_identity);
        }})
        .catch(function(err) {{
          setStatus('Error: ' + err.message);
        }});
    }}

    window.vaultBrowser = {{
      open: function() {{
        overlay.classList.add('open');
        search.value = '';
        fetchNotes('');
        search.focus();
      }},
      close: function() {{
        overlay.classList.remove('open');
      }},
      selectNote: function(path) {{
        vaultBrowser.close();
        var input = document.getElementById('note_path');
        if (input) {{ input.value = path; input.form.submit(); }}
      }}
    }};

    search.addEventListener('input', function() {{
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function() {{
        fetchNotes(search.value.trim());
      }}, 300);
    }});

    overlay.addEventListener('click', function(e) {{
      if (e.target === overlay) vaultBrowser.close();
    }});

    document.addEventListener('keydown', function(e) {{
      if (e.key === 'Escape') vaultBrowser.close();
    }});
  }})();
  </script>
</body>
</html>"""


def handle_get(
    *,
    query_string: str,
    client: WorkspaceHttpClient,
    api_base_url: str,
    production_profile: bool = False,
) -> str:
    """Parse query string, optionally load a note, and return full page HTML.

    Pure except for the WorkspaceHttpClient network call when note_path is present.
    """
    params = parse_qs(query_string)
    note_path = params.get("note_path", [""])[0].strip()
    fields: Optional[dict] = None
    error = ""

    if note_path:
        page = RealNoteWorkspaceDevPage(client)
        state = page.load(NoteLoadIntent(note_path=note_path))
        if state.is_loaded:
            fields = page.render_fields()
        else:
            error = state.error or "Unknown error"

    return render_index_html(
        api_base_url=api_base_url,
        note_path=note_path,
        fields=fields,
        error=error,
        production_profile=production_profile,
    )


def make_handler(
    *,
    client: WorkspaceHttpClient,
    api_base_url: str,
    production_profile: bool = False,
    static_assets: dict[str, tuple[str, bytes]] | None = None,
) -> type:
    """Return a configured BaseHTTPRequestHandler subclass.

    The returned class closes over client and api_base_url as class attributes
    so each request instance can reach them without global state.
    """

    class _Handler(BaseHTTPRequestHandler):
        _client = client
        _api_base_url = api_base_url
        _production_profile = production_profile
        _static_assets = static_assets or {}

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in self._static_assets:
                content_type, body = self._static_assets[parsed.path]
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = handle_get(
                query_string=parsed.query,
                client=self._client,
                api_base_url=self._api_base_url,
                production_profile=self._production_profile,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            pass  # suppress per-request log noise; startup banner handles visibility

    return _Handler


def main() -> None:
    """Entry point: read env config, bind server, serve until KeyboardInterrupt."""
    config = load_config()
    client = WorkspaceHttpClient(base_url=config["api_base_url"])
    handler = make_handler(client=client, api_base_url=config["api_base_url"])
    server = HTTPServer((config["host"], config["port"]), handler)
    print(
        "[companion-ui] DEV/STAGING ONLY — real-note workspace dev server",
        flush=True,
    )
    print(
        f"[companion-ui] Listening:    http://{config['host']}:{config['port']}/",
        flush=True,
    )
    print(
        f"[companion-ui] Runtime API:  {config['api_base_url']}",
        flush=True,
    )
    print(
        "[companion-ui] Stop with Ctrl-C",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
