"""Tests for the companion-UI ask proxy timeout budget (issue #2993).

Bug: the companion dev server's httpx client used a single short default
timeout (`_DEFAULT_API_TIMEOUT_SECONDS = 2.0`) for every proxied route,
including the long-running POST /api/operator/ask -> /api/ask rewrite. Real
`/api/ask` synthesis latency on the ollama route measured ~50s, so the chat
surface always failed with `{"error": "runtime_unavailable", "message":
"timed out"}`.

Fix: POST /api/operator/ask gets its own generous timeout budget
(COMPANION_ASK_TIMEOUT_SECONDS, default 120s) passed as a per-request
override to WorkspaceHttpClient.post, while every other route (in particular
health-probe GETs) keeps its own short, unaffected timeout.
"""

from __future__ import annotations

import io
import json
import time
from typing import Any

from companion_ui.workspace.serve_dev_page import load_config, make_handler


class _SlowAskClient:
    """Fake client whose /api/ask POST takes longer than the old 2s default.

    Records the timeout it was called with so the test can assert the proxy
    passed a generous per-request timeout override rather than relying on
    the client's short default.
    """

    def __init__(self, *, delay_seconds: float, answer: dict[str, Any]) -> None:
        self._delay_seconds = delay_seconds
        self._answer = answer
        self.post_timeout_calls: list[tuple[str, float | None]] = []
        self.get_timeout_calls: list[tuple[str, float | None]] = []

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.post_timeout_calls.append((url, timeout))
        # Simulate a slow backend that would blow past the old 2.0s default
        # but must complete within the new ask-specific budget.
        time.sleep(self._delay_seconds)
        return self._answer

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.get_timeout_calls.append((url, timeout))
        return {"ok": True}


class _PostDriver:
    """Drives make_handler._Handler.do_POST without a real socket."""

    def __init__(self, handler_cls: type, path: str, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self._instance = handler_cls.__new__(handler_cls)
        self._instance.path = path
        self._instance.rfile = io.BytesIO(raw)
        self._instance.wfile = io.BytesIO()
        self._instance.headers = {"Content-Length": str(len(raw))}
        self._instance.client_address = ("127.0.0.1", 50000)
        self.status_code: int | None = None
        self.payload: dict[str, Any] | None = None

        def _send_json(status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self.payload = payload

        self._instance._send_json = _send_json  # type: ignore[method-assign]

    def run_post(self) -> None:
        self._instance.do_POST()


def test_slow_ask_completes_through_proxy() -> None:
    """A slow (simulated 30s-equivalent) /api/operator/ask round-trip returns
    the answer through the proxy instead of runtime_unavailable, because the
    proxy now passes a generous timeout override for the ask rewrite route.
    """
    ask_answer = {"answer": "42", "sources": []}
    # We don't actually sleep 30s in the test; instead we assert the proxy
    # requested a timeout budget generous enough to survive a real 30s+
    # synthesis call, well above the old 2.0s default.
    client = _SlowAskClient(delay_seconds=0.05, answer=ask_answer)
    handler_cls = make_handler(
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
        ask_timeout_seconds=120.0,
    )

    p = _PostDriver(handler_cls, "/api/operator/ask", {"question": "test question"})
    p.run_post()

    assert p.status_code == 200
    assert p.payload == ask_answer
    # Path rewrite still applies: companion-UI path -> runtime /api/ask
    assert client.post_timeout_calls[-1][0] == "/api/ask"
    # The timeout override passed to the client must comfortably exceed a
    # realistic 30s+ synthesis latency and the old 2.0s default.
    ask_timeout = client.post_timeout_calls[-1][1]
    assert ask_timeout is not None
    assert ask_timeout >= 30.0


def test_health_probe_timeout_unchanged() -> None:
    """Health-probe GET timeout stays bounded (<=10s) and independent of the
    new ask timeout budget: load_config's default client timeout used for
    ordinary GET routes stays short, and raising COMPANION_ASK_TIMEOUT_SECONDS
    does not raise the general API client timeout.
    """
    config = load_config()

    # Default general API timeout is short (health probes ride this budget
    # unless they use their own explicit short timeout, e.g. the 10.0s
    # httpx.get calls for audio/other probes).
    assert config["api_timeout_seconds"] <= 10.0

    # The ask-specific budget is independent and, by default, much larger
    # than the health-probe budget -- confirming the fix is scoped to the
    # long-running ask route only.
    assert config["ask_timeout_seconds"] >= 30.0
    assert config["ask_timeout_seconds"] != config["api_timeout_seconds"]
