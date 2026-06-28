"""UI /healthz probes upstream — OBSSTAB-11, #2618.

The companion-UI ``/healthz`` endpoint must probe the upstream runtime API and
return 503 when the runtime is unreachable, not an unconditional 200.

These tests drive the real handler path via ``make_handler`` with an injected
fake client, following the pattern in ``test_ui_api_proxy.py``.
"""

from __future__ import annotations

import io
from typing import Any

from companion_ui.workspace.serve_dev_page import make_handler
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientNetworkError,
)


# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class _FakeClient:
    """Records calls, returns configured payloads or raises a configured error."""

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


# ---------------------------------------------------------------------------
# Driver — drives do_GET without a real socket
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_healthz_503_when_upstream_down() -> None:
    """UI /healthz returns 503 when the upstream runtime API is unreachable.

    Acceptance Criterion: AC1 of #2618.
    Verify: test_healthz_503_when_upstream_down
    """
    client = _FakeClient(get_error=WorkspaceClientNetworkError("connection refused"))
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    driver = _GetDriver(handler_cls, "/healthz")
    driver.run_get()

    assert driver.status_code == 503
    assert driver.payload == {"ok": False, "upstream": "unreachable"}
    # Confirm the handler actually attempted the upstream probe.
    assert client.get_calls == [("/api/health", {})]


def test_healthz_200_when_upstream_ok() -> None:
    """UI /healthz returns 200 with service name when upstream is reachable.

    Acceptance Criterion: AC2 of #2618.
    Verify: test_healthz_200_when_upstream_ok
    """
    health_response = {"ok": True, "checks": {}}
    client = _FakeClient(get_responses={"/api/health": health_response})
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]

    driver = _GetDriver(handler_cls, "/healthz")
    driver.run_get()

    assert driver.status_code == 200
    assert driver.payload == {"ok": True, "service": "companion-ui"}
    # Confirm the handler actually probed upstream before returning 200.
    assert client.get_calls == [("/api/health", {})]


def test_prod_handler_healthz_probes_upstream() -> None:
    """Production handler (make_handler(production_profile=True)) has the same probe behaviour.

    The production server (serve_production_page.py) calls the shared
    ``make_handler`` factory, so no source change to that file is needed.
    This test confirms the shared factory applies the upstream-aware probe
    regardless of ``production_profile``.

    Acceptance Criterion: AC3 of #2618.
    Verify: test_prod_handler_healthz_probes_upstream
    """
    # Verify 503 path in prod profile.
    down_client = _FakeClient(get_error=WorkspaceClientNetworkError("connection refused"))
    prod_handler_cls = make_handler(  # type: ignore[arg-type]
        client=down_client,
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
    )
    down_driver = _GetDriver(prod_handler_cls, "/healthz")
    down_driver.run_get()

    assert down_driver.status_code == 503
    assert down_driver.payload == {"ok": False, "upstream": "unreachable"}
    assert down_client.get_calls == [("/api/health", {})]

    # Verify 200 path in prod profile.
    up_client = _FakeClient(get_responses={"/api/health": {"ok": True}})
    prod_handler_up_cls = make_handler(  # type: ignore[arg-type]
        client=up_client,
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
    )
    up_driver = _GetDriver(prod_handler_up_cls, "/healthz")
    up_driver.run_get()

    assert up_driver.status_code == 200
    assert up_driver.payload == {"ok": True, "service": "companion-ui"}
    assert up_client.get_calls == [("/api/health", {})]
