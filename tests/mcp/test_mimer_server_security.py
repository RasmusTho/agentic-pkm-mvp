from __future__ import annotations

import asyncio
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest

from app.mimer_mcp.transport import MimerMcpTransportConfig, parse_config


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
    runner = tmp_path / "deny_sockets.py"
    runner.write_text(
        "import socket, sys\n"
        "sys.path.insert(0, '.')\n"
        "from app.mimer_mcp.transport import main\n"
        "_socket = socket.socket\n"
        "def deny_network(family=socket.AF_INET, *args, **kwargs):\n"
        "    if family != socket.AF_UNIX: raise RuntimeError('network socket forbidden')\n"
        "    return _socket(family, *args, **kwargs)\n"
        "socket.socket = deny_network\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )

    async def negotiate() -> list[str]:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(runner), "--transport", "stdio"],
            cwd=".",
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
