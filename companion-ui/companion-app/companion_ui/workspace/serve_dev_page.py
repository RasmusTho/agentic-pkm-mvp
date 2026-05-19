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
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

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
    body = _e(fields.get("body", ""))
    panel_rail = _e(fields.get("panel_rail", "Panel / agent rail placeholder"))
    canvas_session_id = _e(fields.get("canvas_session_id") or "")
    canvas_state = _e(fields.get("canvas_session_state", "idle"))
    canvas_user_present = bool(fields.get("canvas_user_present", False))
    canvas_can_edit_body = bool(fields.get("canvas_can_edit_body", False))
    persistence = str(fields.get("canvas_session_persistence", ""))
    panel_render = fields.get("panel_render") or {}
    panel_state = _e(panel_render.get("state") or fields.get("panel_state", "idle"))
    panel_label = _e(panel_render.get("label") or panel_rail)
    panel_message = _e(panel_render.get("message") or "")
    proposal_count = int(fields.get("panel_proposal_count", 0) or 0)
    writeguard_status = _e(fields.get("guard_writeguard_status", "ok"))
    canvas_enabled = bool(fields.get("guard_canvas_enabled", True))
    guard_messages: list[str] = []
    if writeguard_status.lower() == "blocked":
        guard_messages.append("WriteGuard blocked")
    if not canvas_enabled:
        guard_messages.append("Canvas disabled")
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
    )
    canvas_controls_html = _render_canvas_session_controls(
        note_path=note_path_val,
        session_id=canvas_session_id,
        can_edit_body=canvas_can_edit_body,
        user_present=canvas_user_present,
    )

    return f"""
  <div class="workspace-layout">
    <div class="workspace-main">
      <header class="note-header" data-testid="workspace-note-header" data-region="note-header">
        <h1 class="note-title">{title}</h1>
        <div class="note-provenance">
          <span class="prov-item"><span class="prov-label">path</span><code>{note_path_val}</code></span>
          <span class="prov-sep">&middot;</span>
          <span class="prov-item"><span class="prov-label">artifact</span><code>{artifact_id}</code></span>
          <span class="prov-sep">&middot;</span>
          <span class="prov-item"><span class="prov-label">hash</span><code>{content_hash}</code></span>
        </div>
      </header>
      <div class="note-body" data-testid="workspace-note-body" data-region="note-body">
        <pre class="note-body-content">{body}</pre>
      </div>
    </div>
    <aside class="agent-rail" data-testid="workspace-agent-rail" data-region="agent-rail">
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
        <div class="rail-state-row">
          <span class="rail-state-label">Panel</span>
          <span class="rail-state-value" data-testid="workspace-panel-label">{panel_label}</span>
          <span class="rail-state-count" data-testid="workspace-panel-proposal-count">{proposal_text}</span>
        </div>
        {panel_message_html}
        {proposal_rows_html}
        {guard_html}
        {persistence_html}
        {panel_rail}
      </div>
    </aside>
  </div>"""


def _render_canvas_session_controls(
    *,
    note_path: str,
    session_id: str,
    can_edit_body: bool,
    user_present: bool,
) -> str:
    start_disabled = " disabled" if session_id else ""
    close_disabled = "" if session_id else " disabled"
    edit_disabled = "" if can_edit_body else " disabled"
    present_text = "user present" if user_present else "user not present"
    return f"""
        <div class="canvas-controls" data-testid="workspace-canvas-session-controls">
          <button
            type="button"
            data-testid="workspace-canvas-start"
            data-api-method="POST"
            data-api-path="/api/canvas/sessions"
            data-note-path="{note_path}"{start_disabled}>Start</button>
          <button
            type="button"
            data-testid="workspace-canvas-close"
            data-api-method="DELETE"
            data-api-path="/api/canvas/sessions/{session_id}"{close_disabled}>Close</button>
          <button
            type="button"
            data-testid="workspace-canvas-edit-submit"{edit_disabled}>Apply body edit</button>
          <span class="canvas-presence" data-testid="workspace-canvas-user-present">{present_text}</span>
        </div>"""


def _render_panel_proposal_rows(proposals: list[dict]) -> str:
    if not proposals:
        return ""

    rows: list[str] = []
    for proposal in proposals:
        evidence = proposal.get("evidence") or {}
        affordances = proposal.get("affordances") or {}
        enabled_affordances = [
            label
            for label in ("confirm", "correct", "reject")
            if affordances.get(label)
        ]
        rows.append(
            f"""
        <div class="panel-proposal-row" data-testid="workspace-panel-proposal-row">
          <div class="panel-proposal-title">{_e(proposal.get("description", ""))}</div>
          <div class="panel-proposal-meta">
            <span>{_e(proposal.get("proposal_id", ""))}</span>
            <span>{_e(proposal.get("status", ""))}</span>
          </div>
          <div class="panel-proposal-evidence" data-testid="workspace-panel-evidence">
            <span>{_e(evidence.get("trigger_summary", ""))}</span>
            <span>{_e(evidence.get("action_class", ""))}</span>
            <span>{_e(evidence.get("cognition_route", ""))}</span>
          </div>
          <div class="panel-proposal-affordances">
            {_e(" / ".join(enabled_affordances))}
          </div>
        </div>"""
        )
    return "\n".join(rows)


def _render_error_section(error: str) -> str:
    """Render a visible error state using Yggdrasil destructive tokens."""
    return f"""
  <div class="error-state" data-testid="workspace-error-state">
    <span class="error-label">API Error</span>
    <span class="error-message"><code>{_e(error)}</code></span>
  </div>"""


def render_index_html(
    *,
    api_base_url: str,
    note_path: str = "",
    fields: Optional[dict] = None,
    error: str = "",
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

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Companion UI — Real-Note Workspace [DEV]</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;1,400&family=Space+Grotesk:wght@300;400;500;600&display=swap" rel="stylesheet">
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
      padding: 20px;
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      color: var(--fg-1);
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
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
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-api">
      <span class="api-label">Runtime API</span>
      <span class="api-url" title="{_e(api_base_url)}">{_e(api_base_url)}</span>
    </div>
    <span class="dev-chip">DEV / not production</span>
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
    </form>
  </div>
  {content_section}
</body>
</html>"""


def handle_get(
    *,
    query_string: str,
    client: WorkspaceHttpClient,
    api_base_url: str,
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
    )


def make_handler(*, client: WorkspaceHttpClient, api_base_url: str) -> type:
    """Return a configured BaseHTTPRequestHandler subclass.

    The returned class closes over client and api_base_url as class attributes
    so each request instance can reach them without global state.
    """

    class _Handler(BaseHTTPRequestHandler):
        _client = client
        _api_base_url = api_base_url

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            body = handle_get(
                query_string=parsed.query,
                client=self._client,
                api_base_url=self._api_base_url,
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
