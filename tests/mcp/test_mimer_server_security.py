from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest

SIDECAR_DISTRIBUTION = Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"
sys.path.insert(0, str(SIDECAR_DISTRIBUTION))
from mimer_mcp_sidecar.transport import MimerMcpTransportConfig, parse_config


def _installed_entrypoint(tmp_path: Path) -> Path:
    venv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True
    )
    subprocess.run(
        [str(venv / "bin" / "pip"), "install", "--no-deps", str(SIDECAR_DISTRIBUTION)],
        check=True,
    )
    return venv / "bin" / "mimer-mcp"


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
    arguments: list[str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_config(arguments)


def test_stdio_production_entrypoint_opens_no_network_listener(tmp_path) -> None:
    entrypoint = _installed_entrypoint(tmp_path)
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

    async def negotiate() -> list[str]:
        parameters = StdioServerParameters(
            command=str(entrypoint), args=["--transport", "stdio"],
            env={**os.environ, "PYTHONPATH": str(probe)},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]

    assert asyncio.run(negotiate()) == [
        "mimer.ask",
        "mimer.capture",
        "mimer.retrieve",
        "mimer.read_note",
        "mimer.health",
    ]

    with pytest.raises(ValueError, match="loopback"):
        MimerMcpTransportConfig(base_url="http://192.0.2.1:8000").validate()
