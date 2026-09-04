from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SIDECAR_DISTRIBUTION = Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"


def _installed_entrypoint(tmp_path: Path) -> Path:
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    subprocess.run(
        [
            str(venv / "bin" / "pip"), "install", "--requirement",
            str(SIDECAR_DISTRIBUTION / "requirements.txt"),
        ],
        check=True,
    )
    subprocess.run(
        [str(venv / "bin" / "pip"), "install", "--no-deps", str(SIDECAR_DISTRIBUTION)],
        check=True,
    )
    return venv / "bin" / "mimer-mcp"


@pytest.fixture(scope="module")
def installed_entrypoint(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _installed_entrypoint(tmp_path_factory.mktemp("mimer-mcp-sidecar"))


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--transport", "streamable-http"], "only the stdio transport"),
        (["--bind", "0.0.0.0"], "rejects network"),
        (["--port", "8080"], "rejects network"),
        (["--tls-cert", "cert.pem"], "rejects network"),
        (["--auth-token", "secret"], "rejects network"),
    ],
)
def test_network_transport_and_listener_configuration_are_rejected(
    installed_entrypoint: Path, arguments: list[str], message: str
) -> None:
    result = subprocess.run(
        [str(installed_entrypoint), *arguments], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert message in result.stderr


def _request(process: subprocess.Popen[str], payload: dict[str, object]) -> dict[str, object]:
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()
    line = process.stdout.readline()
    assert line, process.stderr.read() if process.stderr is not None else "sidecar exited"
    response = json.loads(line)
    assert isinstance(response, dict)
    return response


def test_stdio_production_entrypoint_opens_no_network_listener(
    tmp_path: Path, installed_entrypoint: Path
) -> None:
    entrypoint = installed_entrypoint
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "sitecustomize.py").write_text(
        "import socket\n"
        "_socket = socket.socket\n"
        "class NoListener(_socket):\n"
        "  def bind(self, *args, **kwargs): raise AssertionError('listener bind forbidden')\n"
        "  def listen(self, *args, **kwargs): raise AssertionError('listener listen forbidden')\n"
        "socket.socket = NoListener\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [str(entrypoint), "--transport", "stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": str(probe)},
    )
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    }
    try:
        assert _request(process, initialize)["id"] == 1
        assert process.stdin is not None
        process.stdin.close()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
