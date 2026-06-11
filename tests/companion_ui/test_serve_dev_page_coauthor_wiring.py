"""Served-page wiring for the live canvas co-authoring loop (#1733).

The agentic render models and HTTP client shipped in #1717/#1727, but the
served dev page (`serve_dev_page.py`) never actually calls
``POST /api/canvas/sessions/{id}/coauthor``. These tests assert that the served
page now wires that loop end to end behind ``CANVAS_ENABLED``:

- a co-authoring intent input + "Co-author" submit control that posts to
  ``/coauthor`` and renders the server-applied body + change summary,
- a governance-bearing 409 (``status="routed_to_panel"``) rendering a read-only
  "view in Panel" affordance keyed to the returned ``intent_id``,
- and complete omission of the co-author surface when canvas is disabled.

Server declares, UI renders: no local body composition, no governance
inference, receipts never invented.
"""

from __future__ import annotations

import io
import json
from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import make_handler, render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError
from tests.companion_ui.vault_browser_test_helpers import (
    default_vault_browser_payload,
    is_vault_browser_get,
)


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if url == "/api/companion/vault-browser":
            return {}
        self.get_calls.append((url, params))
        if is_vault_browser_get(url):
            return default_vault_browser_payload()
        return self.payloads.pop(0)

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return {"session_id": "session-1", "ok": True}


def _workspace_payload(
    *,
    can_edit_body: bool = True,
    canvas_enabled: bool = True,
) -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "art-1733",
            "note_path": "Notes/canvas.md",
            "title": "Canvas Note",
            "body": "# Canvas Note\n\nBody.",
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": "session-1",
            "session_state": "active" if can_edit_body else "idle",
            "user_present": can_edit_body,
            "can_edit_body": can_edit_body,
            "recovery_needed": False,
            "session_log_path": None,
            "session_persistence": "in_memory",
        },
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {"canvas_enabled": canvas_enabled, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _render_canvas(client: _FakeClient) -> str:
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    page.load(NoteLoadIntent(note_path="Notes/canvas.md"))
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/canvas.md",
        fields=fields,
    )


def test_served_page_calls_coauthor_and_renders_applied_edit() -> None:
    """The co-author control posts the intent to /coauthor and renders the
    server-applied body + change summary into the existing body-render path."""
    html = _render_canvas(_FakeClient([_workspace_payload(can_edit_body=True)]))

    # Intent input + submit control are present and runtime-backed.
    assert 'data-testid="workspace-canvas-coauthor-intent"' in html
    assert 'data-testid="workspace-canvas-coauthor-submit"' in html

    # The submit control targets the live /coauthor endpoint via POST.
    assert "/api/canvas/sessions/session-1/coauthor" in html
    assert 'data-capability="canvas.coauthor"' in html

    # A result region exists to receive the server-applied body + summary.
    assert 'data-testid="workspace-canvas-coauthor-applied-body"' in html
    assert 'data-testid="workspace-canvas-coauthor-change-summary"' in html

    # The JS posts the intent value as {intent: ...} and renders applied_body /
    # change_summary returned by the server (no local body composition).
    assert "/coauthor" in html
    assert "applied_body" in html
    assert "change_summary" in html
    assert "JSON.stringify" in html


def test_served_page_renders_view_in_panel_affordance_on_409() -> None:
    """A governance-bearing 409 (status='routed_to_panel') is wired to render a
    read-only view-in-Panel affordance keyed to the returned intent_id and must
    NOT apply a body edit."""
    html = _render_canvas(_FakeClient([_workspace_payload(can_edit_body=True)]))

    # The view-in-Panel affordance markup is keyed to the server intent_id.
    assert 'data-testid="workspace-canvas-view-in-panel"' in html
    assert "data-intent-id" in html

    # JS branches on the 409 / routed_to_panel handoff and surfaces intent_id.
    assert "409" in html
    assert "routed_to_panel" in html
    assert "intent_id" in html

    # The 503 provider-unavailable path renders a calm non-destructive notice.
    assert 'data-testid="workspace-canvas-coauthor-notice"' in html
    assert "503" in html


def test_served_page_renders_exploratory_without_applying() -> None:
    """An exploratory 200 (status='exploratory_no_edit') must render as a
    read-only, non-mutating notice and must NOT fall through to the applied-edit
    render path (which would mark the result 'applied' with an empty body).

    Regression guard for PR #1764 Codex P2: the served client previously treated
    any non-409/non-503 2xx as an applied edit, so the new exploratory response
    would be misrendered as an applied edit with empty body/summary.
    """
    html = _render_canvas(_FakeClient([_workspace_payload(can_edit_body=True)]))

    # The client branches on the exploratory status BEFORE the generic res.ok
    # applied-edit path, and renders a distinct non-mutating result state.
    assert "exploratory_no_edit" in html
    # The exploratory branch is guarded on the server-declared status, not on
    # HTTP-ok alone, so it cannot be reached by an ordinary applied edit.
    assert "res.data.status === 'exploratory_no_edit'" in html


def test_served_page_canvas_coauthor_absent_when_disabled() -> None:
    """When CANVAS_ENABLED is unset (guards.canvas_enabled false): no intent
    input, no co-author control, and no /coauthor call/affordance."""
    html = _render_canvas(
        _FakeClient([_workspace_payload(can_edit_body=True, canvas_enabled=False)])
    )

    assert 'data-testid="workspace-canvas-coauthor-intent"' not in html
    assert 'data-testid="workspace-canvas-coauthor-submit"' not in html
    assert 'data-testid="workspace-canvas-view-in-panel"' not in html
    assert 'data-capability="canvas.coauthor"' not in html
    assert "/coauthor" not in html


# ---------------------------------------------------------------------------
# Same-origin POST proxy: the dynamic /coauthor path must reach the runtime and
# preserve the governance handoff body, otherwise the served page 404s the
# request locally and the 409/503 handling never runs.
# ---------------------------------------------------------------------------


class _ProxyClient:
    def __init__(self, *, post_result: Any = None, post_error: Exception | None = None) -> None:
        self.post_result = post_result if post_result is not None else {"ok": True}
        self.post_error = post_error
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        if self.post_error is not None:
            raise self.post_error
        return self.post_result


class _CapturingHandler:
    """Drives a make_handler subclass' do_POST without a real socket."""

    def __init__(self, handler_cls: type, path: str, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self._instance = handler_cls.__new__(handler_cls)
        self._instance.path = path
        self._instance.rfile = io.BytesIO(raw)
        self._instance.wfile = io.BytesIO()
        self._instance.headers = {"Content-Length": str(len(raw))}
        self.status_code: int | None = None
        self.payload: dict[str, Any] | None = None

        def _send_json(status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self.payload = payload

        self._instance._send_json = _send_json  # type: ignore[method-assign]

    def run_post(self) -> None:
        self._instance.do_POST()


def test_page_server_proxies_coauthor_and_forwards_applied_body() -> None:
    client = _ProxyClient(
        post_result={
            "applied_body": "# Note\n\nTightened.",
            "change_summary": "tightened intro",
        }
    )
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]
    driver = _CapturingHandler(
        handler_cls,
        "/api/canvas/sessions/sess-1/coauthor",
        {"intent": "tighten the intro"},
    )

    driver.run_post()

    # The dynamic coauthor path was forwarded to the runtime (not 404'd locally).
    assert client.post_calls == [
        ("/api/canvas/sessions/sess-1/coauthor", {"intent": "tighten the intro"})
    ]
    assert driver.status_code == 200
    assert driver.payload == {
        "applied_body": "# Note\n\nTightened.",
        "change_summary": "tightened intro",
    }


def test_page_server_proxy_preserves_409_governance_handoff_body() -> None:
    # The runtime returns the governance handoff as a 409 JSON body; the proxy
    # must forward that body verbatim (status + intent_id) so the page can key
    # the view-in-Panel affordance to it.
    governance_body = {
        "status": "routed_to_panel",
        "intent_id": "abc123",
        "action_type": "maturity_transition",
        "detail": "governance-bearing mutation routed to Panel",
    }
    client = _ProxyClient(
        post_error=WorkspaceClientHTTPError(409, json.dumps(governance_body))
    )
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]
    driver = _CapturingHandler(
        handler_cls,
        "/api/canvas/sessions/sess-1/coauthor",
        {"intent": "promote to evergreen"},
    )

    driver.run_post()

    assert driver.status_code == 409
    assert driver.payload == governance_body


def test_page_server_proxy_rejects_unknown_canvas_post_path() -> None:
    client = _ProxyClient()
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]
    driver = _CapturingHandler(
        handler_cls,
        "/api/canvas/sessions/sess-1/coauthor/extra",
        {"intent": "x"},
    )

    driver.run_post()

    assert driver.status_code == 404
    assert client.post_calls == []
