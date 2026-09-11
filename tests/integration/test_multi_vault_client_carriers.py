"""Behavioral single-origin carrier forwarding for MVR-05B."""

from __future__ import annotations

import io
from typing import Any

from companion_ui.workspace.serve_dev_page import make_handler


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post(self, url: str, *, json: dict[str, Any], headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        return {"ok": True}


def test_proxy_backend_carrier_matrix_and_activation_boundary() -> None:
    client = _Client()
    handler_cls = make_handler(client=client, api_base_url="http://runtime")  # type: ignore[arg-type]
    handler = handler_cls.__new__(handler_cls)
    handler.path = "/api/companion/capture/compatibility"
    handler.headers = {
        "Content-Length": "2",
        "X-API-Key": "api-key",
        "X-Active-Context-Session": "session-bearer",
        "X-Active-Context-Override": "override-bearer",
        "X-Compatibility-Write-Precondition": "opaque-precondition",
    }
    handler.rfile = io.BytesIO(b"{}")
    handler.wfile = io.BytesIO()
    handler._send_json = lambda status_code, payload: None  # type: ignore[method-assign]
    handler.do_POST()

    assert client.calls == [
        (
            "/api/companion/capture/compatibility",
            {
                "X-API-Key": "api-key",
                "X-Active-Context-Session": "session-bearer",
                "X-Active-Context-Override": "override-bearer",
                "X-Compatibility-Write-Precondition": "opaque-precondition",
            },
        )
    ]
    assert handler_cls.route_allowed("POST", "/api/companion/capture/compatibility")
    # No page/picker activation is introduced by the callable carrier route.
    assert not handler_cls.route_allowed("POST", "/api/companion/capture/scoped")
