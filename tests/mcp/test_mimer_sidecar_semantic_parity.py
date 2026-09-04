"""Parity proof for the #3368 semantic adapter after its A2 relocation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"))
from mimer_mcp_sidecar.semantic import MimerMcpServer as SidecarServer
from app.mimer_mcp.server import MimerMcpServer as CompatibilityServer


@dataclass
class _Response:
    status_code: int
    payload: Any

    def json(self) -> Any:
        return self.payload


class _Operations:
    def __init__(self, response: _Response | Exception) -> None:
        self.response = response
        self.calls: list[str] = []

    def _call(self, name: str, **_: Any) -> _Response:
        self.calls.append(name)
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


def _receipt(trace_id: str) -> dict[str, Any]:
    return {
        "outcome": "written", "note_path": "Inbox/inbox.md", "operation": "append_note",
        "adapter": "fs_vault", "captured_at": "2026-09-04T20:00:00Z", "trace_id": trace_id,
        "events_emitted": [],
        "governed_write": {
            "policy_decision": {"decision_id": "p", "status": "approved", "action": "companion.capture.append", "write_class": "vault_capture_append", "actor": "companion.capture", "resource": "Inbox/inbox.md", "reason": "allowed", "issued_at": "now", "source": "WriteGuard", "contract_version": "governed_write_protocol.v0"},
            "decision_token": {"token_id": "t", "decision_id": "p", "action": "companion.capture.append", "write_class": "vault_capture_append", "actor": "companion.capture", "resource": "Inbox/inbox.md", "issued_at": "now", "valid": True, "contract_version": "governed_write_protocol.v0"},
            "authority_receipt": {"receipt_id": "r", "decision_token_id": "t", "decision_id": "p", "action": "companion.capture.append", "write_class": "vault_capture_append", "actor": "companion.capture", "resource": "Inbox/inbox.md", "outcome": "applied", "operation": "append_note", "adapter": "fs_vault", "state_owner": "knowledge", "source_receipt_ref": "fs_vault:append_note:Inbox/inbox.md", "fallback_used": False, "recorded_at": "now", "trace_id": trace_id, "contract_version": "governed_write_protocol.v0"},
        },
    }


def test_standalone_sidecar_is_single_implementation_with_v1_parity() -> None:
    assert CompatibilityServer is SidecarServer
    assert [tool.as_dict() for tool in CompatibilityServer(_Operations(_Response(200, {}))).list_tools()] == [
        tool.as_dict() for tool in SidecarServer(_Operations(_Response(200, {}))).list_tools()
    ]

    trace_id = "trace-parity"
    operations = _Operations(_Response(200, _receipt(trace_id)))
    result = CompatibilityServer(operations).call_tool("mimer.capture", {"text": "x", "trace_id": trace_id})
    assert result.is_error is False and result.content == _receipt(trace_id)
    assert result.trace_id == trace_id and operations.calls == ["capture"]

    invalid = _Operations(_Response(200, {"outcome": "written", "trace_id": trace_id}))
    assert CompatibilityServer(invalid).call_tool("mimer.capture", {"text": "x", "trace_id": trace_id}).is_error
    assert invalid.calls == ["capture"]

    timeout = _Operations(httpx.ReadTimeout("lost acknowledgement"))
    error = CompatibilityServer(timeout).call_tool("mimer.capture", {"text": "x", "trace_id": trace_id})
    assert error.error and error.error["error"] == "timeout" and error.trace_id == trace_id
    assert timeout.calls == ["capture"]
