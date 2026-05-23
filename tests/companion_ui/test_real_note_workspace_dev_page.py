"""Tests: minimal real-note workspace dev page (#1072).

Verifies that the dev page:
- exposes note-path load intent (NoteLoadIntent)
- renders title, path, artifact_id, body, and content marker from the real-note payload shape
- preserves note body as primary surface and agent/Panel rail as secondary
- is marked as dev/staging, not production UI contract
- has no direct vault file access
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import (
    DEV_PAGE_LABEL,
    IS_PRODUCTION_UI,
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.real_note_workspace_shell import (
    REGION_AGENT_RAIL,
    REGION_NOTE_BODY,
)
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _artifact_response(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "artifact_id": "note-uuid-42",
        "artifact_kind": "human_note",
        "note_path": "/vault/notes/research.md",
        "title": "Research Note",
        "body": "# Research Note\n\nDetailed body.",
        "content_hash": "deadbeef0042",
        "identity_source": "frontmatter.uuid",
        "identity_state": "resolved",
        "companion_of": None,
        "owns_identity": True,
    }
    base.update(overrides)
    return base


def _workspace_response(
    *,
    artifact: dict[str, Any] | None = None,
    canvas: dict[str, Any] | None = None,
    panel: dict[str, Any] | None = None,
    guards: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "artifact": artifact or _artifact_response(),
        "canvas": canvas or {"session_state": "idle", "session_persistence": "in_memory"},
        "panel": panel or {"state": "idle", "proposal_count": 0},
        "guards": guards or {
            "canvas_enabled": True,
            "writeguard_status": "ok",
            "workspace_update": {
                "available": True,
                "state": "available",
                "reason": "explicit_dev_config",
                "scope": "active_note_body",
                "governance_actions_enabled": False,
                "config_mode": "explicit",
            },
        },
        "runtime": {
            "environment_label": "dev",
            "api_base_url_label": "local-dev",
            "trace_id": "trace-42",
        },
        "suggestions": {},
    }


def _mock_get_response(payload: dict) -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = payload
    return m


def _loaded_page(
    note_path: str = "notes/research.md",
    response: dict | None = None,
) -> RealNoteWorkspaceDevPage:
    resp = response or _workspace_response()
    mock_resp = _mock_get_response(resp)
    with patch("httpx.get", return_value=mock_resp):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path=note_path))
    return page


# ---------------------------------------------------------------------------
# AC 1: dev page exposes note-path load intent
# ---------------------------------------------------------------------------


def test_dev_page_exposes_note_path_load_intent() -> None:
    """Dev page accepts a NoteLoadIntent with note_path and forwards it to the API."""
    # NoteLoadIntent is the load intent type
    intent = NoteLoadIntent(note_path="Notes/test.md")
    assert intent.note_path == "Notes/test.md"
    assert intent.artifact_id is None

    # Optional artifact_id is supported
    intent_with_id = NoteLoadIntent(note_path="Notes/test.md", artifact_id="uuid-1")
    assert intent_with_id.artifact_id == "uuid-1"

    # Dev page calls the runtime API with note_path from the intent
    mock_resp = _mock_get_response(_workspace_response())
    with patch("httpx.get", return_value=mock_resp) as mock_get:
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        state = page.load(NoteLoadIntent(note_path="Notes/test.md"))

    assert state.is_loaded is True
    call_args = mock_get.call_args
    assert call_args.args[0] == "http://localhost:18001/api/companion/workspace"
    assert "note_path" in call_args.kwargs["params"]
    assert call_args.kwargs["params"]["note_path"] == "Notes/test.md"


# ---------------------------------------------------------------------------
# AC 2: dev page renders real-note payload fields
# ---------------------------------------------------------------------------


def test_dev_page_renders_real_note_payload() -> None:
    """Dev page renders title, path, artifact_id, body, and content marker."""
    page = _loaded_page(response=_workspace_response(artifact=_artifact_response(
        artifact_id="note-uuid-42",
        note_path="notes/research.md",
        title="Research Note",
        body="# Research Note\n\nDetailed body.",
        content_hash="deadbeef0042",
    )))

    assert page.state.is_loaded is True
    assert page.state.shell is not None

    # All required fields present
    shell = page.state.shell
    assert shell.title == "Research Note"
    assert shell.note_path == "notes/research.md"
    assert shell.artifact_id == "note-uuid-42"
    assert "Detailed body" in shell.body
    assert shell.content_hash == "deadbeef0042"

    # render_fields exposes all required fields
    fields = page.render_fields()
    assert fields is not None
    assert fields["title"] == "Research Note"
    assert fields["note_path"] == "notes/research.md"


def test_loads_from_workspace_aggregate() -> None:
    """Dev page reads artifact, Canvas, Panel, and guard fields from the workspace aggregate."""
    page = _loaded_page(response=_workspace_response(
        artifact=_artifact_response(title="Aggregate Note"),
        canvas={"session_state": "active", "session_persistence": "in_memory"},
        panel={"state": "proposals-staged", "proposal_count": 2},
        guards={"canvas_enabled": False, "writeguard_status": "blocked"},
    ))

    fields = page.render_fields()
    assert fields is not None
    assert fields["title"] == "Aggregate Note"
    assert fields["canvas_session_state"] == "active"
    assert fields["canvas_session_persistence"] == "in_memory"
    assert fields["panel_state"] == "proposals-staged"
    assert fields["panel_proposal_count"] == 2
    assert fields["guard_writeguard_status"] == "blocked"
    assert fields["guard_canvas_enabled"] is False
    assert fields["artifact_id"] == "note-uuid-42"
    assert "Detailed body" in fields["body"]
    assert fields["content_hash"] == "deadbeef0042"
    assert fields["artifact_identity_source"] == "frontmatter.uuid"
    assert fields["artifact_identity_state"] == "resolved"
    assert fields["runtime_environment_label"] == "dev"
    assert fields["runtime_api_base_url_label"] == "local-dev"
    assert fields["runtime_trace_id"] == "trace-42"


def test_artifact_identity_states_render_from_workspace_payload() -> None:
    page = _loaded_page(response=_workspace_response(artifact=_artifact_response(
        artifact_id=None,
        note_path="notes/blocked.md",
        title="Blocked Note",
        identity_source="missing",
        identity_state="unresolved_missing_uuid",
    )))
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/blocked.md",
        fields=fields,
    )

    assert 'data-testid="workspace-artifact-identity-pill"' in html
    assert 'data-identity-state="unresolved_missing_uuid"' in html
    assert 'data-identity-source="missing"' in html
    assert 'data-testid="workspace-artifact-identity-caution"' in html
    assert "Artifact identity unresolved" in html


def test_writeguard_blocked_marks_mutating_affordances_blocked() -> None:
    page = _loaded_page(response=_workspace_response(
        artifact=_artifact_response(title="Guarded Note"),
        canvas={
            "session_id": "session-1",
            "session_state": "active",
            "user_present": True,
            "can_edit_body": True,
            "session_persistence": "in_memory",
        },
        panel={
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": "proposal-1",
                    "artifact_id": "note-uuid-42",
                    "description": "Apply guarded change",
                    "status": "staged",
                    "affordances": {"confirm": True, "correct": True, "reject": True},
                }
            ],
        },
        guards={"canvas_enabled": True, "writeguard_status": "blocked"},
    ))
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/research.md",
        fields=fields,
    )

    assert 'data-testid="workspace-guard-indicator"' in html
    assert "WriteGuard blocked" in html
    assert 'data-capability="canvas.applyBodyEdit"' in html
    assert 'data-affordance-status="blocked"' in html
    assert 'data-testid="workspace-panel-proposal-unavailable"' in html


# ---------------------------------------------------------------------------
# AC 3: dev page preserves Obsidian-like workflow layout
# ---------------------------------------------------------------------------


def test_dev_page_preserves_obsidian_like_workflow_layout() -> None:
    """Note body is primary surface; agent/Panel rail is secondary placeholder."""
    page = _loaded_page()

    assert page.state.shell is not None
    shell = page.state.shell

    # Note body is primary
    assert shell.region_role(REGION_NOTE_BODY) == "primary"
    # Agent rail is secondary
    assert shell.region_role(REGION_AGENT_RAIL) == "secondary"
    # Agent rail slot is always present
    assert shell.has_agent_rail is True

    # Panel rail placeholder present in state
    placeholder = page.state.panel_rail_placeholder
    assert placeholder  # non-empty
    label_lower = placeholder.lower()
    assert "panel" in label_lower or "rail" in label_lower or "agent" in label_lower

    # render_fields includes panel_rail
    fields = page.render_fields()
    assert fields is not None
    assert "panel_rail" in fields
    assert fields["panel_rail"]


# ---------------------------------------------------------------------------
# AC 4: dev page is marked as dev/staging, not production UI
# ---------------------------------------------------------------------------


def test_dev_page_is_marked_non_production() -> None:
    """Dev page must be clearly marked as staging/dev, not production UI contract."""
    # Module-level markers
    assert IS_PRODUCTION_UI is False
    assert DEV_PAGE_LABEL
    label_lower = DEV_PAGE_LABEL.lower()
    assert "dev" in label_lower or "staging" in label_lower
    assert "production" in label_lower

    client = WorkspaceHttpClient(base_url="http://localhost:18001")
    page = RealNoteWorkspaceDevPage(client)

    # Instance attributes carry the marker
    assert page.is_production_ui is False
    page_label_lower = page.dev_page_label.lower()
    assert "dev" in page_label_lower or "staging" in page_label_lower

    # render_fields exposes is_production_ui=False after load
    mock_resp = _mock_get_response(_workspace_response())
    with patch("httpx.get", return_value=mock_resp):
        page.load(NoteLoadIntent(note_path="notes/test.md"))

    fields = page.render_fields()
    assert fields is not None
    assert fields["is_production_ui"] is False
    assert "dev_page_label" in fields


# ---------------------------------------------------------------------------
# AC 5: dev page has no direct vault file access
# ---------------------------------------------------------------------------


def test_dev_page_has_no_direct_vault_file_access() -> None:
    """Architecture guard: dev page must not access vault files directly."""
    vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes", "open"}
    page_file = (
        pathlib.Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "workspace"
        / "real_note_workspace_dev_page.py"
    )
    assert page_file.exists(), f"real_note_workspace_dev_page.py not found: {page_file}"

    tree = ast.parse(page_file.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in vault_io_calls:
            violations.append(f"line {getattr(node, 'lineno', '?')}: uses .{node.attr}")

    assert not violations, (
        "real_note_workspace_dev_page must not access vault files directly:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Error path: load failure surfaces as state.error, not silent empty
# ---------------------------------------------------------------------------


def test_dev_page_load_failure_surfaces_error() -> None:
    """When the runtime API returns an error, state.error is set and is_loaded is False."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = '{"error": "note_not_found"}'

    with patch("httpx.get", return_value=mock_resp):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        state = page.load(NoteLoadIntent(note_path="missing/note.md"))

    assert state.is_loaded is False
    assert state.error is not None
    assert state.shell is None
    assert page.render_fields() is None


# ---------------------------------------------------------------------------
# Regression: note-path-only load must not raise when runtime returns no artifact_id
# ---------------------------------------------------------------------------


def test_dev_page_note_path_only_load_succeeds_without_artifact_id() -> None:
    """When no artifact_id is supplied and the runtime echoes '' back, the page
    must not raise. It should fall back to note_path as the artifact identifier
    so the workspace shell's non-empty artifact_id invariant is satisfied."""
    # Simulate the runtime behaviour: artifact_id echoed as "" when not supplied
    response_without_artifact_id = _workspace_response(artifact={
        "artifact_id": "",
        "note_path": "notes/test.md",
        "title": "Test Note",
        "body": "# Test Note\n\nBody.",
        "content_hash": "abc000",
    })
    mock_resp = _mock_get_response(response_without_artifact_id)

    with patch("httpx.get", return_value=mock_resp):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        state = page.load(NoteLoadIntent(note_path="notes/test.md"))

    assert state.is_loaded is True, f"Expected load to succeed; error: {state.error}"
    assert state.shell is not None
    # Artifact ID falls back to note_path when API returns empty
    assert state.shell.artifact_id == "notes/test.md"
    assert state.shell.title == "Test Note"


# ---------------------------------------------------------------------------
# Vault identity fields in render_fields()
# ---------------------------------------------------------------------------


def _workspace_response_with_vault_identity(
    vault_name: str = "Niflheim",
    channel: str = "dev",
    provenance: str = "env",
) -> dict:
    base = _workspace_response()
    base["runtime"]["vault_identity"] = {
        "vault_name": vault_name,
        "channel": channel,
        "provenance": provenance,
    }
    return base


def test_render_fields_includes_vault_identity() -> None:
    page = _loaded_page(response=_workspace_response_with_vault_identity())
    fields = page.render_fields()
    assert fields is not None
    assert fields["runtime_vault_name"] == "Niflheim"
    assert fields["runtime_vault_channel"] == "dev"
    assert fields["runtime_vault_provenance"] == "env"


def test_render_fields_vault_identity_defaults_when_absent() -> None:
    """Existing API responses without vault_identity must not break render_fields."""
    page = _loaded_page(response=_workspace_response())  # no vault_identity in runtime
    fields = page.render_fields()
    assert fields is not None
    assert fields["runtime_vault_name"] == "unresolved"
    assert fields["runtime_vault_channel"] == "unknown"
    assert fields["runtime_vault_provenance"] == "unresolved"


def test_render_fields_vault_identity_path_with_spaces() -> None:
    page = _loaded_page(response=_workspace_response_with_vault_identity(
        vault_name="Mobile Documents",
        channel="dev",
        provenance="env",
    ))
    fields = page.render_fields()
    assert fields is not None
    assert fields["runtime_vault_name"] == "Mobile Documents"


def test_workspace_renders_update_flow_availability() -> None:
    page = _loaded_page(
        response=_workspace_response(
            guards={
                "canvas_enabled": True,
                "writeguard_status": "ok",
                "workspace_update": {
                    "available": True,
                    "state": "available",
                    "reason": "explicit_dev_config",
                    "scope": "active_note_body",
                    "governance_actions_enabled": False,
                    "config_mode": "explicit",
                },
            }
        )
    )
    fields = page.render_fields()
    assert fields is not None
    assert fields["guard_workspace_update_available"] is True
    assert fields["guard_workspace_update_state"] == "available"
    assert fields["guard_workspace_update_scope"] == "active_note_body"

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/research.md",
        fields=fields,
    )
    assert 'data-testid="workspace-update-flow-state"' in html
    assert 'data-update-state="available"' in html
    assert 'data-testid="workspace-update-governance-state"' in html
    assert "governance via update" in html


def test_workspace_update_flow_disabled_state_is_non_mutating() -> None:
    page = _loaded_page(
        response=_workspace_response(
            canvas={
                "session_id": "session-1",
                "session_state": "active",
                "user_present": True,
                "can_edit_body": True,
                "session_persistence": "in_memory",
            },
            guards={
                "canvas_enabled": True,
                "writeguard_status": "ok",
                "workspace_update": {
                    "available": False,
                    "state": "disabled",
                    "reason": "disabled_by_config",
                    "scope": "active_note_body",
                    "governance_actions_enabled": False,
                    "config_mode": "explicit",
                },
            },
        )
    )
    fields = page.render_fields()
    assert fields is not None
    assert fields["guard_workspace_update_available"] is False
    assert fields["guard_workspace_update_state"] == "disabled"

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/research.md",
        fields=fields,
    )
    assert 'data-testid="workspace-update-flow-state"' in html
    assert 'data-update-state="disabled"' in html
    assert 'data-testid="workspace-canvas-body-edit-unavailable"' in html
    assert 'data-testid="workspace-canvas-body-edit-composer"' not in html
