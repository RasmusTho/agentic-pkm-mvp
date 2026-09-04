from __future__ import annotations

import asyncio

from mcp import types

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


def test_client_spawned_restart_restores_stdio_without_replay() -> None:
    first = create_stdio_server(_SemanticServer())  # type: ignore[arg-type]
    second = create_stdio_server(_SemanticServer())  # type: ignore[arg-type]
    assert first is not second
