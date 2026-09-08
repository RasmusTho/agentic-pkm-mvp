from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"))
from app.mimer_mcp.server import _GovernedMimerHttpOperations, MimerMcpServer


def _complete_capture(trace_id: str = "trace-capture") -> dict[str, Any]:
    return {
        "outcome": "written",
        "note_path": "Inbox/inbox.md",
        "operation": "append_note",
        "adapter": "fs_vault",
        "captured_at": "2026-09-04T20:00:00Z",
        "trace_id": trace_id,
        "events_emitted": ["capture.inbox.appended"],
        "ingest_warning": "index_binding_degraded",
        "governed_write": {
            "policy_decision": {
                "decision_id": "policy-1",
                "status": "approved",
                "action": "companion.capture.append",
                "write_class": "vault_capture_append",
                "actor": "companion.capture",
                "resource": "Inbox/inbox.md",
                "reason": "WriteGuard allowed the bounded durable mutation.",
                "issued_at": "2026-09-04T20:00:00Z",
                "source": "WriteGuard",
                "contract_version": "governed_write_protocol.v0",
            },
            "decision_token": {
                "token_id": "decision-1",
                "decision_id": "policy-1",
                "action": "companion.capture.append",
                "write_class": "vault_capture_append",
                "actor": "companion.capture",
                "resource": "Inbox/inbox.md",
                "issued_at": "2026-09-04T20:00:00Z",
                "valid": True,
                "contract_version": "governed_write_protocol.v0",
            },
            "authority_receipt": {
                "receipt_id": "authority-1",
                "decision_token_id": "decision-1",
                "decision_id": "policy-1",
                "action": "companion.capture.append",
                "write_class": "vault_capture_append",
                "actor": "companion.capture",
                "resource": "Inbox/inbox.md",
                "outcome": "applied",
                "operation": "append_note",
                "adapter": "fs_vault",
                "state_owner": "knowledge",
                "source_receipt_ref": "fs_vault:append_note:Inbox/inbox.md",
                "fallback_used": False,
                "recorded_at": "2026-09-04T20:00:01Z",
                "trace_id": trace_id,
                "contract_version": "governed_write_protocol.v0",
            },
        },
    }


@dataclass
class _Response:
    status_code: int
    payload: Any
    headers: dict[str, str] | None = None

    def json(self) -> Any:
        return self.payload

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}


class _Operations:
    def __init__(self, response: _Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _call(self, name: str, **kwargs: Any) -> _Response:
        self.calls.append((name, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def ask(self, **kwargs: Any) -> _Response:
        return self._call("ask", **kwargs)

    def capture(self, **kwargs: Any) -> _Response:
        return self._call("capture", **kwargs)

    def retrieve(self, **kwargs: Any) -> _Response:
        return self._call("retrieve", **kwargs)

    def read_note(self, **kwargs: Any) -> _Response:
        return self._call("read_note", **kwargs)

    def health(self, **kwargs: Any) -> _Response:
        return self._call("health", **kwargs)


def test_server_exposes_exact_contracted_tool_set() -> None:
    server = MimerMcpServer(_Operations(_Response(200, {})))

    tools = server.list_tools()

    assert [tool.name for tool in tools] == [
        "mimer.ask",
        "mimer.capture",
        "mimer.retrieve",
        "mimer.read_note",
        "mimer.health",
    ]
    assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
    assert "vault" not in {tool.name for tool in tools}


def test_loopback_factory_refuses_networked_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        MimerMcpServer.for_loopback("http://mimer.example.test:8000")


def test_loopback_factory_disables_environment_proxy_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_client(**kwargs: Any) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr("app.mimer_mcp.server.httpx.Client", fake_client)

    MimerMcpServer.for_loopback()

    assert seen["trust_env"] is False


def test_model_backed_operations_use_configured_outer_read_deadline() -> None:
    seen: dict[str, dict[str, Any]] = {}

    class _TimeoutRecordingClient:
        def post(self, path: str, **kwargs: Any) -> _Response:
            seen[path] = kwargs
            return _Response(200, {})

        def get(self, path: str, **kwargs: Any) -> _Response:
            seen[path] = kwargs
            return _Response(200, {})

    operations = _GovernedMimerHttpOperations(
        _TimeoutRecordingClient(), runtime_read_deadline_seconds=90.0
    )
    operations.ask(question="where?", trace_id="ask-trace")
    operations.capture(text="remember this", trace_id="capture-trace")
    operations.retrieve(query="where?", trace_id="retrieve-trace")
    operations.read_note(note_path="inbox.md", artifact_id=None, trace_id="note-trace")
    operations.health(trace_id="health-trace")

    assert seen["/api/ask"]["timeout"].read == 90.0
    assert seen["/api/companion/capture"]["timeout"].read == 90.0
    assert seen["/search"]["timeout"].read == 10.0
    assert seen["/api/artifacts/note"]["timeout"].read == 10.0
    assert seen["/healthz"]["timeout"].read == 10.0

    class _DelayedHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib handler protocol
            body_length = int(self.headers.get("content-length", "0"))
            self.rfile.read(body_length)
            time.sleep(0.05)
            body = b"{}"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    http_server = ThreadingHTTPServer(("127.0.0.1", 0), _DelayedHandler)
    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{http_server.server_port}",
        timeout=httpx.Timeout(0.01),
    )
    try:
        delayed_operations = _GovernedMimerHttpOperations(client)
        assert delayed_operations.ask(question="where?", trace_id="ask-trace").status_code == 200
        assert delayed_operations.capture(text="remember this", trace_id="capture-trace").status_code == 200
    finally:
        client.close()
        http_server.shutdown()
        http_server.server_close()
        server_thread.join(timeout=1)


def test_runtime_read_deadline_rejects_bounds_that_can_expire_first() -> None:
    class _TimeoutRecordingClient:
        def post(self, path: str, **kwargs: Any) -> _Response:
            return _Response(200, {})

        def get(self, path: str, **kwargs: Any) -> _Response:
            return _Response(200, {})

    with pytest.raises(ValueError, match="longer than 60 seconds"):
        _GovernedMimerHttpOperations(
            _TimeoutRecordingClient(), runtime_read_deadline_seconds=60.0
        )


def test_capture_stall_is_ambiguous_and_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _GovernedMimerHttpOperations,
        "_RUNTIME_MANAGED_TIMEOUT",
        httpx.Timeout(0.01, connect=10.0, write=10.0, pool=10.0),
    )
    requests: list[str] = []

    class _StalledHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib handler protocol
            requests.append(self.path)
            body_length = int(self.headers.get("content-length", "0"))
            self.rfile.read(body_length)
            time.sleep(0.2)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    http_server = ThreadingHTTPServer(("127.0.0.1", 0), _StalledHandler)
    http_server.daemon_threads = True
    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{http_server.server_port}",
        timeout=httpx.Timeout(0.01),
    )
    try:
        result = MimerMcpServer(_GovernedMimerHttpOperations(client)).call_tool(
            "mimer.capture", {"text": "x", "trace_id": "capture-trace"}
        )
    finally:
        client.close()
        http_server.shutdown()
        http_server.server_close()
        server_thread.join(timeout=1)

    assert result.error == {
        "error": "capture_ambiguous",
        "state": "not_acknowledged",
        "message": "Capture response was not acknowledged; the append may have landed. Verify before retrying.",
        "retryable": False,
        "trace_id": "capture-trace",
    }
    assert requests == ["/api/companion/capture"]


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("response lost"), httpx.ReadError("connection lost")])
def test_capture_transport_loss_is_ambiguous_and_non_retryable(failure: httpx.HTTPError) -> None:
    operations = _Operations(failure)

    result = MimerMcpServer(operations).call_tool(
        "mimer.capture", {"text": "x", "trace_id": "capture-trace"}
    )

    assert result.error == {
        "error": "capture_ambiguous",
        "state": "not_acknowledged",
        "message": "Capture response was not acknowledged; the append may have landed. Verify before retrying.",
        "retryable": False,
        "trace_id": "capture-trace",
    }
    assert len(operations.calls) == 1


def test_read_tools_delegate_to_existing_client_contract() -> None:
    payload = {"sources": [{"uuid": "u-1"}], "trace_id": "trace-1"}
    operations = _Operations(_Response(200, payload))
    server = MimerMcpServer(operations)

    assert server.call_tool("mimer.ask", {"question": "where?", "trace_id": "t-ask"}).content == payload
    assert server.call_tool("mimer.retrieve", {"query": "where?", "trace_id": "t-find"}).content == payload
    assert server.call_tool("mimer.read_note", {"note_path": "inbox.md", "artifact_id": "u-1"}).content == payload
    assert server.call_tool("mimer.health").content == payload
    assert operations.calls[:2] == [
        ("ask", {"question": "where?", "trace_id": "t-ask"}),
        ("retrieve", {"query": "where?", "trace_id": "t-find"}),
    ]
    assert operations.calls[2][0] == "read_note"
    assert operations.calls[2][1]["trace_id"]
    assert operations.calls[3][0] == "health"
    assert operations.calls[3][1]["trace_id"]


def test_capture_preserves_governed_receipt_at_production_callsite() -> None:
    capture = _complete_capture()
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json=capture)

    client = httpx.Client(
        base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(handler)
    )
    result = MimerMcpServer(_GovernedMimerHttpOperations(client)).call_tool(
        "mimer.capture", {"text": "remember this", "trace_id": "trace-capture"}
    )

    assert result.is_error is False
    assert result.content == capture
    assert observed[0].url.path == "/api/companion/capture"
    assert observed[0].headers["x-trace-id"] == "trace-capture"
    assert json.loads(observed[0].content) == {"text": "remember this"}


def test_capture_failures_never_retry_or_fallback_to_filesystem() -> None:
    failure_payloads = [
        (409, {"detail": {"error": "writeguard_blocked"}}),
        (409, {"state": "vault_selection_required", "reason": "no_vault_bound"}),
        (422, {"detail": {"error": "empty_capture"}}),
        (500, {"detail": {"error": "authority_receipt_persistence_failed", "state": "not_acknowledged"}}),
    ]
    for status, payload in failure_payloads:
        operations = _Operations(_Response(status, payload))
        result = MimerMcpServer(operations).call_tool("mimer.capture", {"text": "x"})
        assert result.error and result.error["status_code"] == status
        assert result.error["detail"] == payload
        assert result.error["trace_id"]
        assert len(operations.calls) == 1
        assert operations.calls[0][0] == "capture"

    timeout_operations = _Operations(httpx.ReadTimeout("response lost"))
    timeout = MimerMcpServer(timeout_operations).call_tool("mimer.capture", {"text": "x"})
    assert timeout.error and timeout.error["error"] == "capture_ambiguous"
    assert timeout.error["state"] == "not_acknowledged"
    assert timeout.error["retryable"] is False
    assert len(timeout_operations.calls) == 1


def test_capture_2xx_without_complete_governed_receipt_fails_closed() -> None:
    operations = _Operations(
        _Response(200, {"outcome": "written", "trace_id": "trace-capture"})
    )

    result = MimerMcpServer(operations).call_tool("mimer.capture", {"text": "x"})

    assert result.error and result.error["error"] == "invalid_governed_capture_response"
    assert result.error["trace_id"] == "trace-capture"
    assert len(operations.calls) == 1


def test_capture_2xx_with_mismatched_governed_bindings_fails_closed() -> None:
    capture = _complete_capture()
    capture["governed_write"]["authority_receipt"]["decision_token_id"] = "other-token"
    operations = _Operations(_Response(200, capture))

    result = MimerMcpServer(operations).call_tool("mimer.capture", {"text": "x"})

    assert result.error and result.error["error"] == "invalid_governed_capture_response"
    assert len(operations.calls) == 1


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("action", lambda capture: capture["governed_write"]["policy_decision"].update(action="other")),
        ("actor", lambda capture: capture["governed_write"]["decision_token"].update(actor="other")),
        ("resource", lambda capture: capture["governed_write"]["authority_receipt"].update(resource="other.md")),
        ("operation", lambda capture: capture["governed_write"]["authority_receipt"].update(operation="other")),
        ("state_owner", lambda capture: capture["governed_write"]["authority_receipt"].update(state_owner="other")),
        ("source_receipt_ref", lambda capture: capture["governed_write"]["authority_receipt"].update(source_receipt_ref="other")),
        ("fallback_used", lambda capture: capture["governed_write"]["authority_receipt"].update(fallback_used=True)),
        ("policy_contract_version", lambda capture: capture["governed_write"]["policy_decision"].update(contract_version="other")),
        ("token_contract_version", lambda capture: capture["governed_write"]["decision_token"].update(contract_version="other")),
        ("contract_version", lambda capture: capture["governed_write"]["authority_receipt"].update(contract_version="other")),
        ("outbound_trace", lambda capture: capture.update(trace_id="other-trace")),
        ("note_path", lambda capture: capture.update(note_path="other.md")),
    ],
)
def test_capture_2xx_with_wrong_invocation_binding_fails_closed(
    label: str, mutate: Any
) -> None:
    capture = _complete_capture()
    mutate(capture)
    operations = _Operations(_Response(200, capture))

    result = MimerMcpServer(operations).call_tool(
        "mimer.capture", {"text": "x", "trace_id": "trace-capture"}
    )

    assert result.error and result.error["error"] == "invalid_governed_capture_response", label
    assert len(operations.calls) == 1


def test_each_operation_gets_trace_correlation_even_when_response_has_no_body_trace() -> None:
    operations = _Operations(_Response(200, {"healthy": True}, {"x-trace-id": "runtime-trace"}))

    result = MimerMcpServer(operations).call_tool("mimer.health")

    assert operations.calls[0][0] == "health"
    assert operations.calls[0][1]["trace_id"]
    assert result.trace_id == "runtime-trace"
    assert result.as_dict()["_meta"] == {"trace_id": "runtime-trace"}
