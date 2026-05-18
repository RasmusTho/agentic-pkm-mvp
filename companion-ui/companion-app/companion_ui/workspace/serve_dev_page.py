"""Minimal browser dev server for the real-note workspace page (#1103).

DEV/STAGING ONLY — not for production use.

Does not implement auth, TLS, reverse proxy, or public exposure.
Calls the configured runtime API through WorkspaceHttpClient
(GET /api/artifacts/note). Does not read vault files directly.
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
    """Render the note view table and body preview from render_fields() output."""
    return f"""
  <div class="note-view">
    <table>
      <tr><th>Title</th><td>{_e(fields.get("title", ""))}</td></tr>
      <tr><th>Note path</th><td><code>{_e(fields.get("note_path", ""))}</code></td></tr>
      <tr><th>Artifact ID</th><td><code>{_e(fields.get("artifact_id", ""))}</code></td></tr>
      <tr><th>Content hash</th><td><code>{_e(fields.get("content_hash", ""))}</code></td></tr>
    </table>
    <h3>Body</h3>
    <pre class="body-preview">{_e(fields.get("body", ""))}</pre>
  </div>
  <div class="rail-placeholder">
    [{_e(fields.get("panel_rail", "Panel / agent rail placeholder"))}]
  </div>"""


def _render_error_section(error: str) -> str:
    """Render a visible error state section."""
    return f"""
  <div class="error">
    <strong>Error loading note</strong><br>
    <code>{_e(error)}</code>
  </div>"""


def render_index_html(
    *,
    api_base_url: str,
    note_path: str = "",
    fields: Optional[dict] = None,
    error: str = "",
) -> str:
    """Render the workspace dev page as plain HTML.

    Pure function — no network calls, no file I/O.
    All user-supplied values are HTML-escaped.
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
  <title>Companion UI — Real-Note Workspace [DEV]</title>
  <style>
    body {{
      font-family: monospace;
      max-width: 960px;
      margin: 2rem auto;
      padding: 0 1rem;
      color: #222;
    }}
    .dev-banner {{
      background: #ffcc00;
      border: 2px solid #cc8800;
      padding: 0.5rem 1rem;
      margin-bottom: 1.5rem;
      font-weight: bold;
    }}
    .api-target {{
      background: #eef2ff;
      border: 1px solid #aab;
      padding: 0.5rem 1rem;
      margin-bottom: 1.5rem;
      font-size: 0.95em;
    }}
    .load-form {{
      margin-bottom: 1.5rem;
    }}
    .load-form input[type=text] {{
      width: 55%;
      padding: 0.35rem 0.5rem;
      font-family: monospace;
      font-size: 1em;
    }}
    .load-form button {{
      padding: 0.35rem 1.2rem;
      margin-left: 0.5rem;
      cursor: pointer;
    }}
    .error {{
      background: #fff0f0;
      border: 2px solid #c00;
      padding: 0.75rem 1rem;
      margin: 1rem 0;
      color: #800;
    }}
    .note-view table {{
      border-collapse: collapse;
      width: 100%;
      margin-bottom: 1rem;
    }}
    .note-view th,
    .note-view td {{
      border: 1px solid #ccc;
      padding: 0.4rem 0.75rem;
      text-align: left;
      vertical-align: top;
    }}
    .note-view th {{
      width: 160px;
      background: #f4f4f4;
    }}
    pre.body-preview {{
      background: #f8f8f8;
      border: 1px solid #ddd;
      padding: 1rem;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 420px;
      overflow-y: auto;
      margin: 0;
    }}
    .rail-placeholder {{
      background: #f0f0f0;
      border: 1px dashed #999;
      padding: 1rem;
      margin-top: 1.25rem;
      color: #666;
      font-style: italic;
    }}
  </style>
</head>
<body>
  <div class="dev-banner">[DEV/STAGING ONLY — not for production use]</div>
  <h1>Companion UI — Real-Note Workspace</h1>
  <div class="api-target">
    <strong>Runtime API:</strong> <code>{_e(api_base_url)}</code>
  </div>
  <div class="load-form">
    <form method="GET" action="/">
      <label for="note_path"><strong>Note path:</strong></label><br>
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
