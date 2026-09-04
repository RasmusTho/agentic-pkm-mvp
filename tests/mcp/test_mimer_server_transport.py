from __future__ import annotations

import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import subprocess
import sys
import threading

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


SIDECAR_DISTRIBUTION = Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"


def _installed_entrypoint(tmp_path: Path) -> Path:
    venv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True
    )
    pip = venv / "bin" / "pip"
    subprocess.run([str(pip), "install", "--no-deps", str(SIDECAR_DISTRIBUTION)], check=True)
    return venv / "bin" / "mimer-mcp"


def test_stdio_transport_lifecycle_negotiates_and_shuts_down_cleanly(tmp_path: Path) -> None:
    entrypoint = _installed_entrypoint(tmp_path)

    async def negotiate_then_eof() -> list[str]:
        parameters = StdioServerParameters(command=str(entrypoint), args=["--transport", "stdio"])
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]

    assert asyncio.run(negotiate_then_eof()) == [
        "mimer.ask", "mimer.capture", "mimer.retrieve", "mimer.read_note", "mimer.health"
    ]


def _request(process: subprocess.Popen[str], payload: dict[str, object]) -> dict[str, object]:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    assert line, process.stderr.read() if process.stderr is not None else "sidecar exited"
    response = json.loads(line)
    assert isinstance(response, dict)
    return response


def _notify(process: subprocess.Popen[str], payload: dict[str, object]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()


def test_client_spawned_restart_restores_stdio_without_replay(tmp_path: Path) -> None:
    entrypoint = _installed_entrypoint(tmp_path)
    capture_started = threading.Event()
    capture_release = threading.Event()
    capture_finished = threading.Event()
    captures: list[bytes] = []

    class MimerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            assert self.path == "/healthz"
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_POST(self) -> None:  # noqa: N802
            assert self.path == "/api/companion/capture"
            captures.append(self.rfile.read(int(self.headers["content-length"])))
            capture_started.set()
            assert capture_release.wait(timeout=10)
            capture_finished.set()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(b'{"outcome":"written"}')
            except BrokenPipeError:
                pass

        def log_message(self, *_: object) -> None:
            return

    runtime = ThreadingHTTPServer(("127.0.0.1", 0), MimerHandler)
    runtime_thread = threading.Thread(target=runtime.serve_forever, daemon=True)
    runtime_thread.start()
    base_url = f"http://127.0.0.1:{runtime.server_port}"
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    first = subprocess.Popen(
        [str(entrypoint), "--base-url", base_url], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        assert _request(first, initialize)["id"] == 1
        _notify(first, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert first.stdin is not None
        first.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "mimer.capture", "arguments": {"text": "once"}}}) + "\n")
        first.stdin.flush()
        assert capture_started.wait(timeout=10), "capture did not enter the unacknowledged in-flight state"
        os.killpg(first.pid, signal.SIGTERM)
        first.wait(timeout=10)
        assert first.poll() is not None
        children = subprocess.run(["pgrep", "-P", str(first.pid)], capture_output=True, text=True)
        assert children.returncode == 1 and children.stdout.strip() == ""
        capture_release.set()
        assert capture_finished.wait(timeout=10), "interrupted capture request survived process termination"

        second = subprocess.Popen(
            [str(entrypoint), "--base-url", base_url], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        try:
            assert _request(second, initialize)["id"] == 1
            _notify(second, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            assert _request(second, {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})["id"] == 3
            assert second.stdin is not None
            second.stdin.close()
            second.wait(timeout=10)
        finally:
            if second.poll() is None:
                os.killpg(second.pid, signal.SIGTERM)
                second.wait(timeout=10)
    finally:
        capture_release.set()
        runtime.shutdown()
        runtime.server_close()
    assert [json.loads(capture) for capture in captures] == [{"text": "once"}]
