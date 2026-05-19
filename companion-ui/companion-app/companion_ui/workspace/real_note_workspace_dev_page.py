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
from typing import Optional

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
    canvas_session_state: str = "idle"
    canvas_session_persistence: str = ""
    panel_state: str = "idle"
    panel_proposal_count: int = 0
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
            self.state = DevPageState(error=str(exc))
            return self.state

        artifact = raw.get("artifact") or {}
        canvas = raw.get("canvas") or {}
        panel = raw.get("panel") or {}
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
        shell = RealNoteWorkspaceShell(payload=payload, agent_rail_state=None)
        panel_count = int(panel.get("proposal_count") or 0)
        panel_label = panel.get("state") or "idle"
        if panel_count:
            panel_label = f"{panel_label} ({panel_count} proposal{'s' if panel_count != 1 else ''})"
        self.state = DevPageState(
            shell=shell,
            panel_rail_placeholder=f"Panel state: {panel_label}",
            canvas_session_state=canvas.get("session_state") or "idle",
            canvas_session_persistence=canvas.get("session_persistence") or "",
            panel_state=panel.get("state") or "idle",
            panel_proposal_count=panel_count,
            guard_writeguard_status=guards.get("writeguard_status") or "ok",
            guard_canvas_enabled=bool(guards.get("canvas_enabled", True)),
            is_loaded=True,
        )
        return self.state

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
            "canvas_session_state": self.state.canvas_session_state,
            "canvas_session_persistence": self.state.canvas_session_persistence,
            "panel_state": self.state.panel_state,
            "panel_proposal_count": self.state.panel_proposal_count,
            "guard_writeguard_status": self.state.guard_writeguard_status,
            "guard_canvas_enabled": self.state.guard_canvas_enabled,
            "is_production_ui": self.is_production_ui,
            "dev_page_label": self.dev_page_label,
        }
