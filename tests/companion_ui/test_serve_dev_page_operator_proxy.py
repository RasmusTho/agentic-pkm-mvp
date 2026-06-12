"""Tests for Companion UI operator diagnostics proxy wiring (issue #1758).

Verifies that the companion dev/prod server proxies the operator diagnostics
endpoints same-origin to COMPANION_API_BASE_URL, so browsers never need direct
access to the runtime localhost port (LOCAL_ACCESS_MODEL.md same-origin contract).

Endpoints proxied:
  GET  /api/operator/status            -> runtime /api/status
  GET  /api/operator/health            -> runtime /api/health
  GET  /api/operator/settings/validate -> runtime /api/settings/validate
  GET  /api/operator/events/tail       -> runtime /api/events/tail
  POST /api/operator/ask               -> runtime /api/ask (path rewritten)
  GET  /operator                       -> renders overlay HTML (calls all four GET routes)
"""

from __future__ import annotations

import io
import json
from typing import Any

from companion_ui.workspace.serve_dev_page import make_handler


# ---------------------------------------------------------------------------
# Minimal fake client that records calls and returns configured payloads
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(
        self,
        get_responses: dict[str, Any] | None = None,
        post_responses: dict[str, Any] | None = None,
        delete_responses: dict[str, Any] | None = None,
        get_error: Exception | None = None,
        post_error: Exception | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self.get_responses = get_responses or {}
        self.post_responses = post_responses or {}
        self.delete_responses = delete_responses or {}
        self.get_error = get_error
        self.post_error = post_error
        self.delete_error = delete_error
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if self.get_error:
            raise self.get_error
        return self.get_responses.get(url, {})

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        if self.post_error:
            raise self.post_error
        return self.post_responses.get(url, {})

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.delete_calls.append((url, params))
        if self.delete_error:
            raise self.delete_error
        return self.delete_responses.get(url, {})


# ---------------------------------------------------------------------------
# Request driver (no real socket needed)
# ---------------------------------------------------------------------------


class _GetDriver:
    """Drives make_handler._Handler.do_GET without a real socket."""

    def __init__(self, handler_cls: type, path: str) -> None:
        self._instance = handler_cls.__new__(handler_cls)
        self._instance.path = path
        self._instance.wfile = io.BytesIO()
        self._instance.headers = {}
        self.status_code: int | None = None
        self.payload: dict[str, Any] | None = None
        self.body_bytes: bytes | None = None

        def _send_json(status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self.payload = payload

        def send_response(code: int, *_: Any) -> None:
            self.status_code = code

        def send_header(*_: Any) -> None:
            pass

        def end_headers() -> None:
            pass

        def write(data: bytes) -> None:
            self.body_bytes = data

        self._instance._send_json = _send_json  # type: ignore[method-assign]
        self._instance.send_response = send_response  # type: ignore[method-assign]
        self._instance.send_header = send_header  # type: ignore[method-assign]
        self._instance.end_headers = end_headers  # type: ignore[method-assign]
        self._instance.wfile.write = write  # type: ignore[method-assign]

    def run_get(self) -> None:
        self._instance.do_GET()


class _PostDriver:
    """Drives make_handler._Handler.do_POST without a real socket."""

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


class _DeleteDriver:
    """Drives make_handler._Handler.do_DELETE without a real socket."""

    def __init__(self, handler_cls: type, path: str) -> None:
        self._instance = handler_cls.__new__(handler_cls)
        self._instance.path = path
        self._instance.wfile = io.BytesIO()
        self._instance.headers = {}
        self.status_code: int | None = None
        self.payload: dict[str, Any] | None = None

        def _send_json(status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self.payload = payload

        self._instance._send_json = _send_json  # type: ignore[method-assign]

    def run_delete(self) -> None:
        self._instance.do_DELETE()


# ---------------------------------------------------------------------------
# test_operator_endpoints_proxied_same_origin
# ---------------------------------------------------------------------------


def test_operator_endpoints_proxied_same_origin() -> None:
    """The companion server proxies all five operator endpoints same-origin:
    GET /api/operator/status, /api/operator/health, /api/operator/settings/validate,
    /api/operator/events/tail, and POST /api/operator/ask (rewritten to /api/ask).
    """
    status_data = {"sot_version": "v5.5", "stores": []}
    health_data = {"ok": True, "checks": {}}
    settings_data = {"ok": True, "issues": []}
    events_data = {"events": []}
    ask_data = {"answer": "42", "sources": []}

    client = _FakeClient(
        get_responses={
            "/api/status": status_data,
            "/api/health": health_data,
            "/api/settings/validate": settings_data,
            "/api/events/tail": events_data,
        },
        post_responses={"/api/ask": ask_data},
    )
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    # --- GET /api/operator/status ---
    d = _GetDriver(handler_cls, "/api/operator/status")
    d.run_get()
    assert d.status_code == 200
    assert d.payload == status_data
    assert client.get_calls[-1] == ("/api/status", {})

    # --- GET /api/operator/health ---
    d = _GetDriver(handler_cls, "/api/operator/health")
    d.run_get()
    assert d.status_code == 200
    assert d.payload == health_data
    assert client.get_calls[-1] == ("/api/health", {})

    # --- GET /api/operator/settings/validate ---
    d = _GetDriver(handler_cls, "/api/operator/settings/validate")
    d.run_get()
    assert d.status_code == 200
    assert d.payload == settings_data
    assert client.get_calls[-1] == ("/api/settings/validate", {})

    # --- GET /api/operator/events/tail ---
    d = _GetDriver(handler_cls, "/api/operator/events/tail")
    d.run_get()
    assert d.status_code == 200
    assert d.payload == events_data
    assert client.get_calls[-1] == ("/api/events/tail", {})

    # --- POST /api/operator/ask -> /api/ask (path rewrite) ---
    p = _PostDriver(handler_cls, "/api/operator/ask", {"question": "test question"})
    p.run_post()
    assert p.status_code == 200
    assert p.payload == ask_data
    # The path was rewritten from /api/operator/ask to /api/ask on the runtime side
    assert client.post_calls[-1] == ("/api/ask", {"question": "test question"})


def test_operator_events_tail_forwards_query_params() -> None:
    """GET /api/operator/events/tail forwards limit and event_prefix params."""
    events_data = {"events": []}
    client = _FakeClient(get_responses={"/api/events/tail": events_data})
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    d = _GetDriver(handler_cls, "/api/operator/events/tail?limit=10&event_prefix=watcher")
    d.run_get()

    assert d.status_code == 200
    assert client.get_calls[-1] == ("/api/events/tail", {"limit": "10", "event_prefix": "watcher"})


def test_operator_get_proxy_degrades_on_client_error() -> None:
    """When the runtime is unreachable, the proxy returns an error response."""
    from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError

    client = _FakeClient(get_error=WorkspaceClientNetworkError("connection refused"))
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    d = _GetDriver(handler_cls, "/api/operator/status")
    d.run_get()

    # Must not return 200 with blank data — must signal error
    assert d.status_code is not None
    assert d.status_code != 200


def test_operator_overlay_route_calls_all_four_get_endpoints() -> None:
    """GET /operator calls all four runtime GET endpoints and renders HTML."""
    status_data = {"sot_version": "v5.5", "stores": [], "ingestion": {}, "ask": {}}
    health_data = {"ok": True, "checks": {"db": {"ok": True}}}
    settings_data = {"ok": False, "issues": [{"code": "VAULT_MISSING", "message": "missing"}]}
    events_data = {"events": [{"timestamp": "2026-06-09T10:00Z", "event_type": "test", "trace_id": "x"}]}

    client = _FakeClient(
        get_responses={
            "/api/status": status_data,
            "/api/health": health_data,
            "/api/settings/validate": settings_data,
            "/api/events/tail": events_data,
        }
    )
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    d = _GetDriver(handler_cls, "/operator")
    d.run_get()

    assert d.status_code == 200
    # All four endpoints were called
    called_paths = [call[0] for call in client.get_calls]
    assert "/api/status" in called_paths
    assert "/api/health" in called_paths
    assert "/api/settings/validate" in called_paths
    assert "/api/events/tail" in called_paths

    # HTML contains operator overlay panels
    html = (d.body_bytes or b"").decode("utf-8", errors="replace")
    assert 'data-testid="operator-overlay-panels"' in html
    assert "v5.5" in html  # status data rendered
    assert "VAULT_MISSING" in html  # settings issue rendered


def test_operator_overlay_route_degrades_gracefully_on_partial_failure() -> None:
    """GET /operator still renders all panels even when some endpoints fail."""
    from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError

    call_count = 0

    class _PartialClient(_FakeClient):
        def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if url == "/api/status":
                raise WorkspaceClientNetworkError("status down")
            return {}

    client = _PartialClient()
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    d = _GetDriver(handler_cls, "/operator")
    d.run_get()

    # Must return 200 HTML even with partial failures
    assert d.status_code == 200
    html = (d.body_bytes or b"").decode("utf-8", errors="replace")
    # Status panel shows degraded
    assert 'data-state="degraded"' in html
    # Other panels still present
    assert 'data-testid="operator-panel-health"' in html


def test_queue_review_post_proxied() -> None:
    response = {"status": "queued", "intent_id": "intent-1875"}
    client = _FakeClient(
        post_responses={"/api/companion/vault-browser/actions/queue-review": response}
    )
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    p = _PostDriver(
        handler_cls,
        "/api/companion/vault-browser/actions/queue-review",
        {"note_path": "Notes/current.md"},
    )
    p.run_post()

    assert p.status_code == 200
    assert p.payload == response
    assert client.post_calls[-1] == (
        "/api/companion/vault-browser/actions/queue-review",
        {"note_path": "Notes/current.md"},
    )


def test_vault_related_get_proxied() -> None:
    response = {"results": [{"note_path": "Notes/related.md"}]}
    client = _FakeClient(get_responses={"/api/companion/vault-related": response})
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    d = _GetDriver(
        handler_cls,
        "/api/companion/vault-related?note_path=Notes/current.md&artifact_uuid=uuid-1875",
    )
    d.run_get()

    assert d.status_code == 200
    assert d.payload == response
    assert client.get_calls[-1] == (
        "/api/companion/vault-related",
        {"note_path": "Notes/current.md", "artifact_uuid": "uuid-1875"},
    )


def test_canvas_session_lifecycle_routes_proxied() -> None:
    client = _FakeClient(
        post_responses={
            "/api/canvas/sessions": {"session_id": "session-1875"},
            "/api/canvas/sessions/session-1875/edits": {"ok": True},
        },
        delete_responses={
            "/api/canvas/sessions/session-1875/edits/last": {"ok": True},
            "/api/canvas/sessions/session-1875": {"ok": True},
        },
    )
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    p = _PostDriver(handler_cls, "/api/canvas/sessions", {"note_path": "Notes/current.md"})
    p.run_post()
    assert p.status_code == 200
    assert client.post_calls[-1] == ("/api/canvas/sessions", {"note_path": "Notes/current.md"})

    p = _PostDriver(
        handler_cls,
        "/api/canvas/sessions/session-1875/edits",
        {"new_body": "Updated", "change_summary": "route parity"},
    )
    p.run_post()
    assert p.status_code == 200
    assert client.post_calls[-1] == (
        "/api/canvas/sessions/session-1875/edits",
        {"new_body": "Updated", "change_summary": "route parity"},
    )

    d = _DeleteDriver(handler_cls, "/api/canvas/sessions/session-1875/edits/last")
    d.run_delete()
    assert d.status_code == 200
    assert client.delete_calls[-1] == ("/api/canvas/sessions/session-1875/edits/last", {})

    d = _DeleteDriver(handler_cls, "/api/canvas/sessions/session-1875")
    d.run_delete()
    assert d.status_code == 200
    assert client.delete_calls[-1] == ("/api/canvas/sessions/session-1875", {})


def test_canvas_recovery_ack_route_not_proxied() -> None:
    client = _FakeClient()
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    p = _PostDriver(handler_cls, "/api/canvas/sessions/session-1875/recovery/ack", {})
    p.run_post()

    assert p.status_code == 404
    assert p.payload == {"error": "not_found", "message": "Unknown Companion UI route"}
    assert client.post_calls == []


def test_tts_status_get_proxied() -> None:
    response = {"provider_available": True, "cache_entries": 0}
    client = _FakeClient(get_responses={"/api/companion/tts/status": response})
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    d = _GetDriver(handler_cls, "/api/companion/tts/status")
    d.run_get()

    assert d.status_code == 200
    assert d.payload == response
    assert client.get_calls[-1] == ("/api/companion/tts/status", {})
