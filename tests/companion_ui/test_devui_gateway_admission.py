from __future__ import annotations

from email.message import Message
from typing import Any

import httpx

from companion_ui.workspace.serve_dev_page import make_handler
from companion_ui.workspace.workspace_http_client import (
    WorkspaceHttpClient,
)


class _FakeClient:
    def __init__(
        self,
        *,
        responses: dict[str, dict[str, Any]] | None = None,
        status_code: int = 200,
    ) -> None:
        self.responses = responses or {}
        self.status_code = status_code
        self.calls: list[tuple[str, dict[str, Any], dict[str, str] | None]] = []

    def get_with_status(
        self,
        url: str,
        *,
        params: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append((url, params, None))
        return self.status_code, self.responses.get(url, {})


class _GetDriver:
    def __init__(
        self,
        handler_cls: type,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        client_host: str = "172.19.0.1",
    ) -> None:
        instance = handler_cls.__new__(handler_cls)
        instance.path = path
        instance.client_address = (client_host, 50000)
        request_headers = Message()
        request_headers["Host"] = "127.0.0.1:8113"
        for name, value in (headers or {}).items():
            if name.lower() == "host":
                request_headers.replace_header("Host", value)
            else:
                request_headers[name] = value
        instance.headers = request_headers
        self.instance = instance
        self.status_code: int | None = None
        self.payload: dict[str, Any] | None = None

        def send_json(status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self.payload = payload

        instance._send_json = send_json

    def run(self) -> None:
        self.instance.do_GET()


def _handler(
    client: object,
    *,
    declared_host: str = "127.0.0.1",
) -> type:
    return make_handler(
        client=client,  # type: ignore[arg-type]
        api_base_url="http://api:8000",
        production_profile=True,
        devui_external_bind_host=declared_host,
    )


def test_gateway_uses_declared_host_publish_not_container_peer_for_local_admission() -> None:
    client = _FakeClient(responses={"/api/devui/overview": {"ok": True}})
    handler_cls = _handler(client)

    allowed = _GetDriver(handler_cls, "/api/devui/overview", client_host="172.19.0.7")
    allowed.run()

    assert allowed.status_code == 200
    assert client.calls == [("/api/devui/overview", {}, None)]

    for forwarded_header in (
        "Forwarded",
        "Via",
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Real-IP",
        "CF-Connecting-IP",
        "True-Client-IP",
        "X-Client-IP",
    ):
        refused = _GetDriver(
            handler_cls,
            "/api/devui/overview",
            headers={forwarded_header: "203.0.113.10"},
        )
        refused.run()
        assert refused.status_code == 403

    nonlocal_host = _GetDriver(
        handler_cls,
        "/api/devui/overview",
        headers={"Host": "192.168.1.20:8113"},
    )
    nonlocal_host.run()
    assert nonlocal_host.status_code == 403

    duplicate_host = _GetDriver(handler_cls, "/api/devui/overview")
    duplicate_host.instance.headers["Host"] = "localhost:8113"
    duplicate_host.run()
    assert duplicate_host.status_code == 403

    for malformed_host in (
        "127.0.0.1@attacker.example",
        "127.0.0.1/path",
        "127.0.0.1:invalid",
        "[::1]attacker.example",
        "[::1]:invalid",
        "127.0.0.1 attacker.example",
        "",
    ):
        refused = _GetDriver(
            handler_cls,
            "/api/devui/overview",
            headers={"Host": malformed_host},
        )
        refused.run()
        assert refused.status_code == 403

    for unsafe_declaration in ("", "0.0.0.0", "192.168.1.20", "100.64.0.20"):
        disabled = _GetDriver(
            _handler(_FakeClient(), declared_host=unsafe_declaration),
            "/api/devui/overview",
        )
        disabled.run()
        assert disabled.status_code == 404

    assert client.calls == [("/api/devui/overview", {}, None)]


def test_gateway_proxies_only_two_exact_devui_get_contracts() -> None:
    subject = "github:RasmusTho/agentic-pkm-mvp#4841"
    client = _FakeClient(
        responses={
            "/api/devui/overview": {"view": "overview"},
            "/api/devui/focus": {"view": "focus"},
        }
    )
    handler_cls = _handler(client)

    overview = _GetDriver(handler_cls, "/api/devui/overview")
    overview.run()
    focus = _GetDriver(
        handler_cls,
        "/api/devui/focus?subject=github%3ARasmusTho%2Fagentic-pkm-mvp%234841",
    )
    focus.run()

    assert overview.status_code == 200
    assert overview.payload == {"view": "overview"}
    assert focus.status_code == 200
    assert focus.payload == {"view": "focus"}
    assert client.calls == [
        ("/api/devui/overview", {}, None),
        ("/api/devui/focus", {"subject": subject}, None),
    ]

    invalid_focus_queries = (
        "/api/devui/focus",
        "/api/devui/focus?subject=",
        "/api/devui/focus?subject=%20",
        "/api/devui/focus?subject=one&subject=two",
        "/api/devui/focus?subject=one&extra=two",
        "/api/devui/focus?other=one",
        "/api/devui/focus?subject=one%ZZ",
    )
    for path in invalid_focus_queries:
        refused = _GetDriver(handler_cls, path)
        refused.run()
        assert refused.status_code == 400

    for path in (
        "/api/devui/overview?extra=1",
        "/api/devui/composition",
        "/api/devui/unknown",
        "/api/devui/overview/child",
    ):
        refused = _GetDriver(handler_cls, path)
        refused.run()
        assert refused.status_code == 404

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert handler_cls.route_allowed(method, "/api/devui/overview") is False
        assert handler_cls.route_allowed(method, "/api/devui/focus") is False

    disabled_handler = _handler(_FakeClient(), declared_host="")
    assert disabled_handler.route_allowed("GET", "/api/devui/overview") is False
    assert disabled_handler.route_allowed("GET", "/api/devui/focus") is False

    error_client = _FakeClient(
        responses={"/api/devui/overview": {"state": "unavailable"}},
        status_code=503,
    )
    upstream_error = _GetDriver(_handler(error_client), "/api/devui/overview")
    upstream_error.run()
    assert upstream_error.status_code == 503
    assert upstream_error.payload == {"state": "unavailable"}


def test_gateway_strips_all_inbound_identity_and_credential_headers(monkeypatch) -> None:
    captured: list[tuple[str, dict[str, Any]]] = []

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        captured.append((url, kwargs))
        return httpx.Response(206, json={"ok": True})

    monkeypatch.setattr(httpx, "get", fake_get)
    client = WorkspaceHttpClient("http://api:8000")
    handler_cls = _handler(client)
    allowed = _GetDriver(
        handler_cls,
        "/api/devui/focus?subject=github%3ARasmusTho%2Fagentic-pkm-mvp%234841",
        headers={
            "X-API-Key": "must-not-transit",
            "Authorization": "Bearer must-not-transit",
            "Proxy-Authorization": "Basic must-not-transit",
        },
    )

    allowed.run()

    assert allowed.status_code == 206
    assert captured == [
        (
            "http://api:8000/api/devui/focus",
            {
                "params": {"subject": "github:RasmusTho/agentic-pkm-mvp#4841"},
                "timeout": 10.0,
            },
        )
    ]

    for forwarded_header in (
        "Forwarded",
        "X-Forwarded-For",
        "Via",
        "X-Real-IP",
    ):
        refused = _GetDriver(
            handler_cls,
            "/api/devui/overview",
            headers={forwarded_header: "127.0.0.1"},
        )
        refused.run()
        assert refused.status_code == 403

    assert len(captured) == 1
