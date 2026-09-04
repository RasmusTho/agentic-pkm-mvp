from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import httpx
import pytest

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
    assert timeout.error and timeout.error["error"] == "timeout"
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
