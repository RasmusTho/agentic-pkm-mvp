"""Tests for the Companion UI single-origin ``/api/companion/*`` proxy (issue #2125).

The companion UI server is served from one origin (e.g. ``:8111``) while the
runtime API binds elsewhere (e.g. ``127.0.0.1:18001``). To remove the
"wrong device" failure mode (a remote browser can reach the UI origin but not
the runtime origin), the UI server proxies ``/api/companion/*`` through itself
to the configured ``COMPANION_API_BASE_URL`` so the browser only ever talks to
the UI origin.

This proxy is **transport only**: it forwards runtime status codes and bodies
unchanged. A runtime 503 stays a 503 (rendered as the #2123 "Vault unreachable"
state) — it is never re-classified, masked as success, cached, or rewritten.

These tests drive ``make_handler``'s request handler without a real socket,
following the pattern in ``test_serve_dev_page_operator_proxy.py``. The fake
client stands in for the *only* path to the runtime: the handler reaching it
proves the browser was served through the UI-origin proxy rather than calling
the runtime origin directly.
"""

from __future__ import annotations

import io
from typing import Any

from companion_ui.workspace.serve_dev_page import make_handler
from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError


class _FakeClient:
    """Records calls and returns configured payloads or raises a configured error.

    The fake client is the configured runtime *target*. The browser has no other
    route to runtime data, so a handler call landing here is exactly the
    UI-origin proxy hop under test.
    """

    def __init__(
        self,
        get_responses: dict[str, Any] | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.get_responses = get_responses or {}
        self.get_error = get_error
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if self.get_error:
            raise self.get_error
        return self.get_responses.get(url, {})

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("POST not exercised by this test")

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("DELETE not exercised by this test")


class _GetDriver:
    """Drives ``make_handler._Handler.do_GET`` without a real socket."""

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

    def run_get(self) -> None:
        self._instance.do_GET()


def test_orientation_served_through_ui_origin() -> None:
    """An orientation request to the UI origin is served through the proxy.

    With the runtime reachable only via the configured target (the fake
    client), a GET to the UI-origin path ``/api/companion/orientation`` resolves
    by forwarding to that target and returning its payload — the browser never
    needs the runtime origin.
    """
    orientation_data = {
        "contract_version": "workspace_orientation.v1",
        "leave_point": {"kind": "derived_only"},
    }
    client = _FakeClient(get_responses={"/api/companion/orientation": orientation_data})
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    driver = _GetDriver(handler_cls, "/api/companion/orientation")
    driver.run_get()

    # Served through the UI origin: status 200 with the runtime payload, having
    # forwarded to the configured target exactly once.
    assert driver.status_code == 200
    assert driver.payload == orientation_data
    assert client.get_calls == [("/api/companion/orientation", {})]


def test_proxy_passes_through_503() -> None:
    """A runtime 503 is passed through unchanged (status 503 + body).

    The runtime returning 503 must surface as a 503 with the runtime body
    intact, so the page renders the #2123 unreachable state — never masked as a
    200 success or re-classified by the UI.
    """
    runtime_body = '{"error": "runtime_unavailable", "detail": "vault unreachable"}'
    client = _FakeClient(get_error=WorkspaceClientHTTPError(503, runtime_body))
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    driver = _GetDriver(handler_cls, "/api/companion/orientation")
    driver.run_get()

    # Status passed through unchanged, and not masked as success.
    assert driver.status_code == 503
    assert driver.status_code != 200
    # Body passed through verbatim (parsed runtime JSON, no rewriting).
    assert driver.payload == {
        "error": "runtime_unavailable",
        "detail": "vault unreachable",
    }
