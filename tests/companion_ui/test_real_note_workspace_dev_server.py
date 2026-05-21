"""Tests for the real-note workspace browser dev server (#1103).

Verifies:
- Module exists and can be imported.
- Default config uses HOST=127.0.0.1, PORT=8111, COMPANION_API_BASE_URL=http://127.0.0.1:18001.
- Env overrides for host/port/API base URL are respected.
- render_index_html produces dev/staging marker.
- render_index_html includes configured API base URL.
- render_index_html includes note_path input.
- render_index_html renders note fields (title/path/artifact/body/hash) from render_fields() dict.
- render_index_html renders visible error state.
- render_index_html includes Panel/agent rail placeholder when note is present.
- handle_get calls the page/client path and renders title/path/artifact/body/hash on success.
- handle_get renders error state on WorkspaceClientError.
- Full HTTP round-trip: GET / returns HTML with dev marker.
- Full HTTP round-trip: GET /?note_path=... renders note fields.
- Full HTTP round-trip: error state is visible.
- No direct vault file access in serve_dev_page module.
- No named vaults are used as code configuration values.
"""

from __future__ import annotations

import ast
import pathlib
import threading
from http.server import HTTPServer
from typing import Any, Optional

import httpx
import pytest

from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
    WorkspaceClientNetworkError,
)


# ---------------------------------------------------------------------------
# Fake HTTP client that matches the WorkspaceHttpClient.get / .post protocol
# ---------------------------------------------------------------------------


class _FakeClient:
    """Fake HTTP client — no network calls. Implements get/post protocol."""

    def __init__(
        self,
        *,
        get_result: Optional[dict] = None,
        get_error: Optional[Exception] = None,
    ) -> None:
        self._get_result = get_result
        self._get_error = get_error
        self.get_calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if self._get_error is not None:
            raise self._get_error
        return self._get_result or {}

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return {}


def _note_payload(
    note_path: str = "Some/Note.md",
    title: str = "Some Note",
    artifact_id: str = "art-123",
    content_hash: str = "sha256-deadbeef",
    body: str = "This is the note body.",
) -> dict:
    return {
        "artifact": {
            "note_path": note_path,
            "title": title,
            "artifact_id": artifact_id,
            "artifact_kind": "human_note",
            "content_hash": content_hash,
            "body": body,
            "identity_source": "frontmatter.uuid",
            "identity_state": "resolved",
            "companion_of": None,
            "owns_identity": True,
        },
        "canvas": {"session_state": "idle", "session_persistence": "in_memory"},
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {
            "environment_label": "dev",
            "api_base_url_label": "local-dev",
            "trace_id": "trace-server-1",
        },
        "suggestions": {},
    }


# ---------------------------------------------------------------------------
# Live HTTP server fixtures
# ---------------------------------------------------------------------------


def _start_server(client: _FakeClient, api_base_url: str) -> tuple[HTTPServer, int]:
    from companion_ui.workspace.serve_dev_page import make_handler

    handler = make_handler(client=client, api_base_url=api_base_url)
    server = HTTPServer(("127.0.0.1", 0), handler)  # port 0 = OS-assigned
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


@pytest.fixture
def live_server_ok():
    """Live server with a fake client that returns a note successfully."""
    payload = _note_payload()
    client = _FakeClient(get_result=payload)
    server, port = _start_server(client, "http://127.0.0.1:18001")
    yield {
        "port": port,
        "client": client,
        "payload": payload,
        "api_base_url": "http://127.0.0.1:18001",
    }
    server.shutdown()


@pytest.fixture
def live_server_error():
    """Live server with a fake client that always raises a network error."""
    client = _FakeClient(
        get_error=WorkspaceClientNetworkError("Connection refused"),
    )
    server, port = _start_server(client, "http://127.0.0.1:19999")
    yield {"port": port, "client": client, "api_base_url": "http://127.0.0.1:19999"}
    server.shutdown()


# ---------------------------------------------------------------------------
# Import / module-level tests
# ---------------------------------------------------------------------------


class TestModuleImport:
    def test_module_importable(self) -> None:
        import companion_ui.workspace.serve_dev_page  # noqa: F401

    def test_load_config_importable(self) -> None:
        from companion_ui.workspace.serve_dev_page import load_config

        assert callable(load_config)

    def test_render_index_html_importable(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        assert callable(render_index_html)

    def test_handle_get_importable(self) -> None:
        from companion_ui.workspace.serve_dev_page import handle_get

        assert callable(handle_get)

    def test_make_handler_importable(self) -> None:
        from companion_ui.workspace.serve_dev_page import make_handler

        assert callable(make_handler)

    def test_main_importable(self) -> None:
        from companion_ui.workspace.serve_dev_page import main

        assert callable(main)


# ---------------------------------------------------------------------------
# Default config and env override tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_default_host(self, monkeypatch) -> None:
        monkeypatch.delenv("HOST", raising=False)
        from companion_ui.workspace.serve_dev_page import load_config

        assert load_config()["host"] == "127.0.0.1"

    def test_default_port(self, monkeypatch) -> None:
        monkeypatch.delenv("PORT", raising=False)
        from companion_ui.workspace.serve_dev_page import load_config

        assert load_config()["port"] == 8111

    def test_default_api_base_url(self, monkeypatch) -> None:
        monkeypatch.delenv("COMPANION_API_BASE_URL", raising=False)
        from companion_ui.workspace.serve_dev_page import load_config

        assert load_config()["api_base_url"] == "http://127.0.0.1:18001"

    def test_host_override(self, monkeypatch) -> None:
        monkeypatch.setenv("HOST", "0.0.0.0")
        from companion_ui.workspace.serve_dev_page import load_config

        assert load_config()["host"] == "0.0.0.0"

    def test_port_override(self, monkeypatch) -> None:
        monkeypatch.setenv("PORT", "8112")
        from companion_ui.workspace.serve_dev_page import load_config

        assert load_config()["port"] == 8112

    def test_api_base_url_override(self, monkeypatch) -> None:
        monkeypatch.setenv("COMPANION_API_BASE_URL", "http://192.168.1.10:18001")
        from companion_ui.workspace.serve_dev_page import load_config

        assert load_config()["api_base_url"] == "http://192.168.1.10:18001"

    def test_all_overrides_together(self, monkeypatch) -> None:
        monkeypatch.setenv("HOST", "0.0.0.0")
        monkeypatch.setenv("PORT", "8113")
        monkeypatch.setenv("COMPANION_API_BASE_URL", "http://127.0.0.1:18000")
        from companion_ui.workspace.serve_dev_page import load_config

        cfg = load_config()
        assert cfg == {
            "host": "0.0.0.0",
            "port": 8113,
            "api_base_url": "http://127.0.0.1:18000",
        }


# ---------------------------------------------------------------------------
# render_index_html — pure function tests
# ---------------------------------------------------------------------------


class TestRenderIndexHtml:
    def test_contains_dev_staging_marker(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(api_base_url="http://127.0.0.1:18001")
        assert "DEV" in html or "STAGING" in html

    def test_contains_api_base_url(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(api_base_url="http://127.0.0.1:18001")
        assert "http://127.0.0.1:18001" in html

    def test_contains_note_path_input(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(api_base_url="http://127.0.0.1:18001")
        assert 'name="note_path"' in html

    def test_contains_load_button(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(api_base_url="http://127.0.0.1:18001")
        assert "<button" in html

    def test_note_path_value_populated_in_input(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path="Inbox/Todo.md",
        )
        assert "Inbox/Todo.md" in html

    def test_renders_fields_from_dict(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        fields = {
            "title": "Some Note",
            "note_path": "Some/Note.md",
            "artifact_id": "art-123",
            "content_hash": "sha256-deadbeef",
            "body": "This is the note body.",
            "panel_rail": "Panel / agent rail placeholder",
            "is_production_ui": False,
            "dev_page_label": "dev/staging",
        }
        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path="Some/Note.md",
            fields=fields,
        )
        assert "Some Note" in html
        assert "Some/Note.md" in html
        assert "art-123" in html
        assert "sha256-deadbeef" in html
        assert "This is the note body." in html

    def test_renders_rail_placeholder_when_fields_present(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        fields = {
            "title": "T",
            "note_path": "N.md",
            "artifact_id": "a",
            "content_hash": "h",
            "body": "b",
            "panel_rail": "Panel / agent rail placeholder",
            "is_production_ui": False,
            "dev_page_label": "dev/staging",
        }
        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            fields=fields,
        )
        assert "rail" in html.lower() or "panel" in html.lower()

    def test_workspace_renders_affordance_status_markers(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        fields = {
            "title": "T",
            "note_path": "N.md",
            "artifact_id": "a",
            "content_hash": "h",
            "body": "b",
            "panel_rail": "Panel / agent rail placeholder",
            "canvas_session_id": "session-1",
            "canvas_session_state": "active",
            "canvas_can_edit_body": True,
            "canvas_user_present": True,
            "canvas_session_persistence": "in_memory",
            "panel_state": "proposals-staged",
            "panel_proposal_count": 1,
            "panel_render": {"state": "proposals-staged", "label": "Proposal staged"},
            "panel_proposals": [
                {
                    "proposal_id": "proposal-1",
                    "artifact_id": "a",
                    "description": "Do thing",
                    "status": "staged",
                    "affordances": {"confirm": True, "correct": True, "reject": True},
                }
            ],
            "guard_canvas_enabled": True,
            "guard_writeguard_status": "ok",
            "is_production_ui": False,
            "dev_page_label": "dev/staging",
        }
        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            fields=fields,
        )

        assert 'data-affordance-status="active"' in html
        assert 'data-affordance-status="experimental"' in html
        assert 'data-capability="canvas.applyBodyEdit"' in html
        assert 'data-runtime-backed="true"' in html

    def test_renders_runtime_safety_strip_and_identity_pills(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        fields = {
            "title": "Some Note",
            "note_path": "Some/Note.md",
            "artifact_id": "art-123",
            "artifact_kind": "human_note",
            "artifact_identity_source": "frontmatter.uuid",
            "artifact_identity_state": "resolved",
            "content_hash": "sha256-deadbeef",
            "body": "This is the note body.",
            "panel_rail": "Panel / agent rail placeholder",
            "runtime_environment_label": "dev",
            "runtime_api_base_url_label": "local-dev",
            "runtime_trace_id": "trace-123",
            "guard_canvas_enabled": False,
            "guard_writeguard_status": "blocked",
            "guard_degraded": True,
            "is_production_ui": False,
            "dev_page_label": "dev/staging",
        }
        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            fields=fields,
        )

        assert 'data-testid="workspace-runtime-safety-strip"' in html
        assert 'data-testid="workspace-runtime-channel"' in html
        assert "dev" in html
        assert "local-dev" in html
        assert 'data-testid="workspace-vault-identity"' in html
        assert "vault identity unavailable" in html
        assert 'data-testid="workspace-writeguard-state"' in html
        assert "blocked" in html
        assert 'data-testid="workspace-canvas-enabled-state"' in html
        assert "disabled" in html
        assert 'data-testid="workspace-artifact-identity-pill"' in html
        assert 'data-identity-state="resolved"' in html
        assert 'data-testid="workspace-content-hash-pill"' in html

    def test_error_state_is_visible(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(
            api_base_url="http://127.0.0.1:19999",
            note_path="Some/Note.md",
            error="Connection refused",
        )
        assert "error" in html.lower() or "Error" in html
        assert "Connection refused" in html

    def test_note_not_found_renders_distinct_state(self) -> None:
        from companion_ui.workspace.serve_dev_page import handle_get

        client = _FakeClient(
            get_error=WorkspaceClientHTTPError(
                404,
                '{"detail":{"error":"note_not_found","message":"No note exists for the requested note_path","note_path":"Missing/Note.md","trace_id":"trace-missing"}}',
            ),
        )
        html = handle_get(
            query_string="note_path=Missing%2FNote.md",
            client=client,
            api_base_url="http://127.0.0.1:18001",
        )

        assert 'data-testid="workspace-note-not-found-state"' in html
        assert "Note not found" in html
        assert "Missing/Note.md" in html

    def test_note_content_not_shown_when_only_error(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(
            api_base_url="http://127.0.0.1:19999",
            error="Connection refused",
        )
        assert "Artifact ID" not in html

    def test_html_escaping_in_note_path(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path='<script>alert("xss")</script>',
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_escaping_in_error(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            error="<b>bad</b>",
        )
        assert "<b>bad</b>" not in html
        assert "&lt;b&gt;" in html

    def test_valid_html_doctype(self) -> None:
        from companion_ui.workspace.serve_dev_page import render_index_html

        html = render_index_html(api_base_url="http://127.0.0.1:18001")
        assert html.strip().startswith("<!DOCTYPE html>")


# ---------------------------------------------------------------------------
# handle_get — unit tests with fake client
# ---------------------------------------------------------------------------


class TestHandleGet:
    def test_empty_query_renders_index_no_note(self) -> None:
        from companion_ui.workspace.serve_dev_page import handle_get

        client = _FakeClient()
        html = handle_get(
            query_string="",
            client=client,
            api_base_url="http://127.0.0.1:18001",
        )
        assert "DEV" in html or "STAGING" in html
        assert client.get_calls == []

    def test_note_path_param_triggers_api_call(self) -> None:
        from companion_ui.workspace.serve_dev_page import handle_get

        client = _FakeClient(get_result=_note_payload())
        handle_get(
            query_string="note_path=Some%2FNote.md",
            client=client,
            api_base_url="http://127.0.0.1:18001",
        )
        assert len(client.get_calls) == 1
        url, params = client.get_calls[0]
        assert url == "/api/companion/workspace"
        assert params.get("note_path") == "Some/Note.md"

    def test_successful_load_renders_note_fields(self) -> None:
        from companion_ui.workspace.serve_dev_page import handle_get

        payload = _note_payload()
        client = _FakeClient(get_result=payload)
        html = handle_get(
            query_string="note_path=Some%2FNote.md",
            client=client,
            api_base_url="http://127.0.0.1:18001",
        )
        assert "Some Note" in html
        assert "art-123" in html
        assert "sha256-deadbeef" in html
        assert "This is the note body." in html

    def test_client_error_renders_error_state(self) -> None:
        from companion_ui.workspace.serve_dev_page import handle_get

        client = _FakeClient(
            get_error=WorkspaceClientNetworkError("Connection refused"),
        )
        html = handle_get(
            query_string="note_path=Some%2FNote.md",
            client=client,
            api_base_url="http://127.0.0.1:19999",
        )
        assert "Connection refused" in html
        assert "error" in html.lower() or "Error" in html

    def test_api_base_url_shown_in_output(self) -> None:
        from companion_ui.workspace.serve_dev_page import handle_get

        client = _FakeClient()
        html = handle_get(
            query_string="",
            client=client,
            api_base_url="http://192.168.1.42:18001",
        )
        assert "http://192.168.1.42:18001" in html


# ---------------------------------------------------------------------------
# Full HTTP round-trip tests
# ---------------------------------------------------------------------------


class TestLiveServer:
    def test_get_root_returns_200(self, live_server_ok) -> None:
        resp = httpx.get(f"http://127.0.0.1:{live_server_ok['port']}/")
        assert resp.status_code == 200

    def test_get_root_has_dev_marker(self, live_server_ok) -> None:
        resp = httpx.get(f"http://127.0.0.1:{live_server_ok['port']}/")
        assert "DEV" in resp.text or "STAGING" in resp.text

    def test_get_root_has_api_base_url(self, live_server_ok) -> None:
        resp = httpx.get(f"http://127.0.0.1:{live_server_ok['port']}/")
        assert live_server_ok["api_base_url"] in resp.text

    def test_get_root_has_note_path_input(self, live_server_ok) -> None:
        resp = httpx.get(f"http://127.0.0.1:{live_server_ok['port']}/")
        assert "note_path" in resp.text

    def test_get_with_note_path_renders_note(self, live_server_ok) -> None:
        resp = httpx.get(
            f"http://127.0.0.1:{live_server_ok['port']}/",
            params={"note_path": "Some/Note.md"},
        )
        body = resp.text
        assert "Some Note" in body
        assert "art-123" in body
        assert "sha256-deadbeef" in body
        assert "This is the note body." in body

    def test_get_content_type_is_html(self, live_server_ok) -> None:
        resp = httpx.get(f"http://127.0.0.1:{live_server_ok['port']}/")
        assert "text/html" in resp.headers.get("content-type", "")

    def test_error_state_rendered_on_client_failure(self, live_server_error) -> None:
        resp = httpx.get(
            f"http://127.0.0.1:{live_server_error['port']}/",
            params={"note_path": "Missing/Note.md"},
        )
        assert resp.status_code == 200
        assert "error" in resp.text.lower() or "Error" in resp.text
        assert "Connection refused" in resp.text


# ---------------------------------------------------------------------------
# Boundary / safety checks
# ---------------------------------------------------------------------------


class TestDevServerBoundaries:
    def test_no_direct_vault_file_access_in_module(self) -> None:
        """Architecture guard: serve_dev_page must not access vault files directly."""
        vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes"}
        srv_file = (
            pathlib.Path(__file__).resolve().parents[2]
            / "companion-ui"
            / "companion-app"
            / "companion_ui"
            / "workspace"
            / "serve_dev_page.py"
        )
        assert srv_file.exists()
        tree = ast.parse(srv_file.read_text(encoding="utf-8"))
        violations = [
            f"line {node.lineno}: .{node.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in vault_io_calls
        ]
        assert not violations, f"Unexpected vault I/O calls: {violations}"

    def test_no_named_vaults_as_config_values(self) -> None:
        import companion_ui.workspace.serve_dev_page as mod

        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        # Vault names must not appear as code configuration values.
        # They are allowed only in documentation and comments (ASCII subset).
        tree = ast.parse(src)
        vault_names = {"Nifelheim", "Bifrost", "Midgard"}
        string_violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for name in vault_names:
                    if name in node.value:
                        string_violations.append(
                            f"line {node.lineno}: string literal contains {name!r}"
                        )
        assert not string_violations, f"Named vault found in code string: {string_violations}"

    def test_default_bind_is_local_only(self) -> None:
        from companion_ui.workspace.serve_dev_page import _DEFAULT_HOST

        assert _DEFAULT_HOST == "127.0.0.1"

    def test_default_port_is_8111(self) -> None:
        from companion_ui.workspace.serve_dev_page import _DEFAULT_PORT

        assert _DEFAULT_PORT == 8111

    def test_default_api_base_url_points_at_dev_runtime(self) -> None:
        from companion_ui.workspace.serve_dev_page import _DEFAULT_API_BASE_URL

        assert _DEFAULT_API_BASE_URL == "http://127.0.0.1:18001"
