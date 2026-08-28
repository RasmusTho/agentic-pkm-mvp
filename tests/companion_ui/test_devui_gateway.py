from __future__ import annotations

from email.message import Message
from io import BytesIO
from typing import Any

from companion_ui.workspace.serve_dev_page import make_handler


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_with_status(
        self, url: str, *, params: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append((url, params))
        return 200, {"contract_version": "fixture.v1"}


def _handler(*, declared_host: str = "127.0.0.1") -> tuple[type, _Client]:
    client = _Client()
    handler = make_handler(
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
        devui_external_bind_host=declared_host,
    )
    return handler, client


def _get(handler: type, path: str, *, forwarded: bool = False) -> tuple[int, dict[str, str], bytes]:
    instance = handler.__new__(handler)
    instance.path = path
    instance.client_address = ("172.19.0.7", 50000)
    headers = Message()
    headers["Host"] = "127.0.0.1:8113"
    if forwarded:
        headers["X-Forwarded-For"] = "127.0.0.1"
    instance.headers = headers
    instance.wfile = BytesIO()
    response_headers: dict[str, str] = {}
    status: list[int] = []
    instance.send_response = lambda code: status.append(code)
    instance.send_header = lambda name, value: response_headers.__setitem__(name, value)
    instance.end_headers = lambda: None
    instance.do_GET()
    return status[0], response_headers, instance.wfile.getvalue()


def test_devui_pages_consume_gateway_admission_without_transport_widening() -> None:
    handler, client = _handler()
    overview = _get(handler, "/devui/overview")
    focus = _get(
        handler,
        "/devui/focus?subject=github%3ARasmusTho%2Fagentic-pkm-mvp%234836",
    )
    stylesheet = _get(handler, "/devui/assets/devui.css")
    refused = _get(handler, "/devui/overview", forwarded=True)
    unknown_api = _get(handler, "/api/devui/composition")

    for status, headers, body in (overview, focus, stylesheet):
        assert status == 200
        assert headers["Cache-Control"] == "no-store"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert body
    assert overview[1]["Content-Security-Policy"] == (
        "default-src 'none'; base-uri 'none'; connect-src 'self'; "
        "font-src 'none'; form-action 'none'; frame-ancestors 'none'; "
        "img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'"
    )
    assert focus[1]["Content-Security-Policy"] == overview[1]["Content-Security-Policy"]
    assert refused[0] == 403
    assert unknown_api[0] == 404
    assert client.calls == []

    disabled, _client = _handler(declared_host="")
    assert _get(disabled, "/devui/overview")[0] == 404
