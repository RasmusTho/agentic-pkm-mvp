"""Hermetic composed acceptance journey for the installed Mimer MCP sidecar."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading

SIDECAR = Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"


def _entrypoint(tmp_path: Path) -> Path:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = venv / "bin" / "pip"
    subprocess.run(
        [str(pip), "install", "--requirement", str(SIDECAR / "requirements.txt")], check=True
    )
    subprocess.run([str(pip), "install", "--no-deps", str(SIDECAR)], check=True)
    return venv / "bin" / "mimer-mcp"


def _call(
    process: subprocess.Popen[str],
    request_id: int,
    name: str,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    assert process.stdin and process.stdout
    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        + "\n"
    )
    process.stdin.flush()
    return json.loads(process.stdout.readline())


def _start(entrypoint: Path, base_url: str) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [str(entrypoint), "--base-url", base_url],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin and process.stdout
    process.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "hermetic", "version": "1"},
                },
            }
        )
        + "\n"
    )
    process.stdin.flush()
    assert json.loads(process.stdout.readline())["id"] == 1
    process.stdin.write(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
    )
    process.stdin.flush()
    return process


def _payload(response: dict[str, object]) -> dict[str, object]:
    result = response["result"]
    return json.loads(result["content"][0]["text"])


def _server() -> tuple[ThreadingHTTPServer, list[str]]:
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def _send(self, value: object, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self) -> None:
            calls.append(self.path)
            if self.path.startswith("/healthz"):
                self._send({"status": "ok"})
            elif self.path.startswith("/search"):
                self._send({"results": [{"source_vault": "v", "note_path": "Inbox/inbox.md"}]})
            elif self.path.startswith("/api/artifacts/note"):
                self._send({"note_path": "Inbox/inbox.md", "content": "note"})
            else:
                self._send({"error": "forbidden"}, 404)

        def do_POST(self) -> None:
            calls.append(self.path)
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            if self.path == "/api/ask":
                self._send({"answer": "grounded", "sources": []})
            elif self.path == "/api/companion/capture":
                if body["text"] == "blocked":
                    self._send({"detail": {"error": "writeguard_blocked"}}, 409)
                    return
                trace = self.headers["x-trace-id"]
                stamp = "2026-09-05T00:00:00Z"
                p = {
                    "decision_id": "d",
                    "action": "companion.capture.append",
                    "write_class": "vault_capture_append",
                    "actor": "companion.capture",
                    "resource": "Inbox/inbox.md",
                    "reason": "allowed",
                    "issued_at": stamp,
                    "source": "WriteGuard",
                    "contract_version": "governed_write_protocol.v0",
                }
                t = {**p, "token_id": "t", "valid": True}
                r = {
                    **p,
                    "receipt_id": "r",
                    "decision_token_id": "t",
                    "outcome": "applied",
                    "operation": "append_note",
                    "adapter": "fs_vault",
                    "state_owner": "knowledge",
                    "source_receipt_ref": "fs_vault:append_note:Inbox/inbox.md",
                    "fallback_used": False,
                    "recorded_at": stamp,
                    "trace_id": trace,
                }
                self._send(
                    {
                        "outcome": "written",
                        "note_path": "Inbox/inbox.md",
                        "operation": "append_note",
                        "adapter": "fs_vault",
                        "captured_at": stamp,
                        "trace_id": trace,
                        "events_emitted": [],
                        "governed_write": {
                            "policy_decision": {**p, "status": "approved"},
                            "decision_token": t,
                            "authority_receipt": r,
                        },
                    }
                )
            else:
                self._send({"error": "forbidden"}, 404)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler), calls


def test_composed_mimer_mcp_journey(tmp_path: Path) -> None:
    runtime, calls = _server()
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    process = _start(_entrypoint(tmp_path), f"http://127.0.0.1:{runtime.server_port}")
    try:
        assert process.stdin and process.stdout
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
        )
        process.stdin.flush()
        tool_names = [
            x["name"] for x in json.loads(process.stdout.readline())["result"]["tools"]
        ]
        assert tool_names == [
            "mimer.ask",
            "mimer.capture",
            "mimer.retrieve",
            "mimer.read_note",
            "mimer.health",
        ]
        assert "mimer.vault.write" not in tool_names
        assert "mimer.receipt.read" not in tool_names
        for i, name, args in [
            (3, "mimer.health", {}),
            (4, "mimer.retrieve", {"query": "q"}),
            (5, "mimer.read_note", {"note_path": "Inbox/inbox.md"}),
            (6, "mimer.ask", {"question": "q"}),
        ]:
            assert "result" in _call(process, i, name, args)
        response = _call(process, 7, "mimer.capture", {"text": "once", "trace_id": "trace-accept"})
        assert response["result"]["isError"] is False, response
        capture = _payload(response)
        assert capture["result"]["governed_write"]["authority_receipt"]["receipt_id"] == "r"
    finally:
        process.terminate()
        process.wait(timeout=10)
        runtime.shutdown()
        runtime.server_close()
    assert set(calls) >= {
        "/healthz",
        "/search?q=q",
        "/api/artifacts/note?note_path=Inbox%2Finbox.md",
        "/api/ask",
        "/api/companion/capture",
    }


def test_composed_journey_preserves_write_boundary_and_failure(tmp_path: Path) -> None:
    runtime, calls = _server()
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    process = _start(_entrypoint(tmp_path), f"http://127.0.0.1:{runtime.server_port}")
    try:
        response = _call(process, 2, "mimer.capture", {"text": "blocked"})
        assert response["result"]["isError"] is True
        assert calls.count("/api/companion/capture") == 1
        process.stdin.close()
        process.wait(timeout=10)
    finally:
        runtime.shutdown()
        runtime.server_close()


def test_restart_recovers_without_capture_replay(tmp_path: Path) -> None:
    runtime, calls = _server()
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    entry = _entrypoint(tmp_path)
    first = _start(entry, f"http://127.0.0.1:{runtime.server_port}")
    _call(first, 2, "mimer.capture", {"text": "once"})
    first.terminate()
    first.wait(timeout=10)
    second = _start(entry, f"http://127.0.0.1:{runtime.server_port}")
    try:
        assert "result" in _call(second, 3, "mimer.health", {})
        assert second.stdin and second.stdout
        second.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}})
            + "\n"
        )
        second.stdin.flush()
        assert [
            tool["name"] for tool in json.loads(second.stdout.readline())["result"]["tools"]
        ] == [
            "mimer.ask",
            "mimer.capture",
            "mimer.retrieve",
            "mimer.read_note",
            "mimer.health",
        ]
        assert calls.count("/api/companion/capture") == 1
    finally:
        second.terminate()
        second.wait(timeout=10)
        runtime.shutdown()
        runtime.server_close()
