"""Hermetic composed acceptance journey for the installed Mimer MCP sidecar."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import threading
import tomllib

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
import app.api.routes.capture as capture_module
from app.write_guard import WritesBlockedError
from tests.api._vault_test_helpers import bind_initialized_vault

SIDECAR = Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"


def _entrypoint(tmp_path: Path) -> Path:
    installed = tmp_path / "installed-sidecar"
    package_root = installed / "site-packages"
    shutil.copytree(SIDECAR / "mimer_mcp_sidecar", package_root / "mimer_mcp_sidecar")

    project = tomllib.loads((SIDECAR / "pyproject.toml").read_text(encoding="utf-8"))
    target = project["project"]["scripts"]["mimer-mcp"]
    module, function = target.split(":", 1)
    launcher = installed / "bin" / "mimer-mcp"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "#!/usr/bin/env python3\n"
        f"from {module} import {function}\n"
        f"raise SystemExit({function}())\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


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
    env = os.environ.copy()
    python_path = str(entrypoint.parent.parent / "site-packages")
    if env.get("PYTHONPATH"):
        python_path = os.pathsep.join((python_path, env["PYTHONPATH"]))
    env["PYTHONPATH"] = python_path
    process = subprocess.Popen(
        [str(entrypoint), "--base-url", base_url],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
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


def _successful_result(response: dict[str, object]) -> dict[str, object]:
    assert "error" not in response, response
    result = response["result"]
    assert isinstance(result, dict)
    assert result.get("isError") is False, response
    return result


def _payload(response: dict[str, object]) -> dict[str, object]:
    result = _successful_result(response)
    return json.loads(result["content"][0]["text"])


def _server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ThreadingHTTPServer, list[str], Path]:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    bind_initialized_vault(monkeypatch, vault, store_dir=tmp_path)
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    inbox = vault / "Inbox" / "inbox.md"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text("# Test inbox\n\nA real runtime note.\n", encoding="utf-8")
    api_client = TestClient(app, raise_server_exceptions=False)
    calls: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def _send(self, value: object, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def _forward(self, method: str, body: bytes | None = None) -> None:
            calls.append(self.path)
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() in {"content-type", "x-trace-id"}
            }
            response = api_client.request(method, self.path, content=body, headers=headers)
            try:
                payload = response.json()
            except ValueError:
                payload = {"detail": response.text}
            self._send(payload, response.status_code)

        def do_GET(self) -> None:
            self._forward("GET")

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            self._forward("POST", self.rfile.read(length))

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler), calls, vault


def test_composed_mimer_mcp_journey(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, calls, vault = _server(tmp_path, monkeypatch)
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
            _successful_result(_call(process, i, name, args))
        response = _call(process, 7, "mimer.capture", {"text": "once", "trace_id": "trace-accept"})
        capture = _payload(response)
        receipt_id = capture["result"]["governed_write"]["authority_receipt"]["receipt_id"]
        assert isinstance(receipt_id, str) and receipt_id
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
    assert "once" in (vault / "Inbox" / "inbox.md").read_text(encoding="utf-8")


def test_composed_journey_preserves_write_boundary_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _blocked(action: str) -> None:
        raise WritesBlockedError(state="safe_mode", reason="test lock", action=action)

    monkeypatch.setattr(capture_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", _blocked)
    runtime, calls, vault = _server(tmp_path, monkeypatch)
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    process = _start(_entrypoint(tmp_path), f"http://127.0.0.1:{runtime.server_port}")
    try:
        response = _call(process, 2, "mimer.capture", {"text": "blocked"})
        assert response["result"]["isError"] is True
        assert response["result"]["content"]
        assert calls.count("/api/companion/capture") == 1
        process.stdin.close()
        process.wait(timeout=10)
    finally:
        runtime.shutdown()
        runtime.server_close()
    assert "blocked" not in (vault / "Inbox" / "inbox.md").read_text(encoding="utf-8")


def test_restart_recovers_without_capture_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, calls, vault = _server(tmp_path, monkeypatch)
    thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    thread.start()
    entry = _entrypoint(tmp_path)
    first = _start(entry, f"http://127.0.0.1:{runtime.server_port}")
    _call(first, 2, "mimer.capture", {"text": "once"})
    first.terminate()
    first.wait(timeout=10)
    second = _start(entry, f"http://127.0.0.1:{runtime.server_port}")
    try:
        _successful_result(_call(second, 3, "mimer.health", {}))
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
    assert "once" in (vault / "Inbox" / "inbox.md").read_text(encoding="utf-8")
