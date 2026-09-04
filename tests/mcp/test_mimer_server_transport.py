from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.mimer_mcp.server import McpToolResult
from app.mimer_mcp.transport import create_stdio_server


class _SemanticServer:
    def list_tools(self):
        from app.mimer_mcp.server import MimerMcpServer

        # The transport discovers its fixed contract from the semantic layer.
        return MimerMcpServer.for_loopback().list_tools()

    def call_tool(self, name: str, arguments: dict[str, object]) -> McpToolResult:
        return McpToolResult(content={"tool": name, "arguments": arguments}, trace_id="trace-test")


def test_stdio_transport_lifecycle_negotiates_and_shuts_down_cleanly() -> None:
    server = create_stdio_server(_SemanticServer())  # type: ignore[arg-type]

    async def verify() -> None:
        handler = server.request_handlers[types.ListToolsRequest]
        result = await handler(types.ListToolsRequest(method="tools/list"))
        assert [tool.name for tool in result.root.tools] == [
            "mimer.ask",
            "mimer.capture",
            "mimer.retrieve",
            "mimer.read_note",
            "mimer.health",
        ]

    asyncio.run(verify())


def test_client_spawned_restart_restores_stdio_without_replay(tmp_path: Path) -> None:
    runner = tmp_path / "sidecar.py"
    capture_log = tmp_path / "captures.log"
    runner.write_text(
        "import asyncio, os, sys\n"
        "sys.path.insert(0, '.')\n"
        "from app.mimer_mcp.server import McpToolResult, MimerMcpServer\n"
        "from app.mimer_mcp.transport import MimerMcpTransportConfig, serve_stdio\n"
        "class Semantic:\n"
        "  def list_tools(self): return MimerMcpServer.for_loopback().list_tools()\n"
        "  def call_tool(self, name, arguments):\n"
        "    if name == 'mimer.capture': open(os.environ['CAPTURE_LOG'], 'a').write('capture\\n')\n"
        "    return McpToolResult(content={'ok': True}, trace_id='trace-test')\n"
        "asyncio.run(serve_stdio(MimerMcpTransportConfig(), lambda _: Semantic()))\n",
        encoding="utf-8",
    )

    async def session_call(capture: bool) -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(runner)],
            cwd=".",
            env={"CAPTURE_LOG": str(capture_log)},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                if capture:
                    response = await session.call_tool("mimer.capture", {"text": "once"})
                    assert response.isError is False
                else:
                    await session.list_tools()

    asyncio.run(session_call(capture=True))
    asyncio.run(session_call(capture=False))
    assert capture_log.read_text(encoding="utf-8") == "capture\n"
