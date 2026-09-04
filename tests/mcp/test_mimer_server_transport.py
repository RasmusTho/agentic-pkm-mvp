from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SIDECAR_ROOT = Path(__file__).resolve().parents[2] / "mimer-mcp-sidecar"
sys.path.insert(0, str(SIDECAR_ROOT))

from mimer_mcp_sidecar.semantic import McpToolResult


class _SemanticServer:
    def list_tools(self):
        from app.mimer_mcp.server import MimerMcpServer

        # The transport discovers its fixed contract from the semantic layer.
        return MimerMcpServer.for_loopback().list_tools()

    def call_tool(self, name: str, arguments: dict[str, object]) -> McpToolResult:
        return McpToolResult(content={"tool": name, "arguments": arguments}, trace_id="trace-test")


def test_stdio_transport_lifecycle_negotiates_and_shuts_down_cleanly(tmp_path: Path) -> None:
    runner = tmp_path / "sidecar.py"
    runner.write_text(
        "import asyncio, sys\n"
        f"sys.path.insert(0, {str(SIDECAR_ROOT)!r})\n"
        "from mimer_mcp_sidecar.semantic import McpToolResult, MimerMcpServer\n"
        "from mimer_mcp_sidecar.transport import MimerMcpTransportConfig, serve_stdio\n"
        "class Semantic:\n"
        "  def list_tools(self): return MimerMcpServer.for_loopback().list_tools()\n"
        "  def call_tool(self, name, arguments): return McpToolResult(content={'ok': True}, trace_id='trace-test')\n"
        "asyncio.run(serve_stdio(MimerMcpTransportConfig(), lambda _: Semantic()))\n",
        encoding="utf-8",
    )

    async def negotiate_then_eof() -> list[str]:
        parameters = StdioServerParameters(command=sys.executable, args=[str(runner)], cwd=".")
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [tool.name for tool in tools.tools]

    assert asyncio.run(negotiate_then_eof()) == [
        "mimer.ask", "mimer.capture", "mimer.retrieve", "mimer.read_note", "mimer.health"
    ]


def test_client_spawned_restart_restores_stdio_without_replay(tmp_path: Path) -> None:
    runner = tmp_path / "sidecar.py"
    capture_log = tmp_path / "captures.log"
    runner.write_text(
        "import asyncio, os, sys\n"
        f"sys.path.insert(0, {str(SIDECAR_ROOT)!r})\n"
        "from mimer_mcp_sidecar.semantic import McpToolResult, MimerMcpServer\n"
        "from mimer_mcp_sidecar.transport import MimerMcpTransportConfig, serve_stdio\n"
        "class Semantic:\n"
        "  def list_tools(self): return MimerMcpServer.for_loopback().list_tools()\n"
        "  def call_tool(self, name, arguments):\n"
        "    if name == 'mimer.capture':\n"
        "      open(os.environ['CAPTURE_LOG'], 'a').write('capture\\n')\n"
        "      open(os.environ['CAPTURE_ENTERED'], 'w').write('entered')\n"
        "      import time; time.sleep(60)\n"
        "    return McpToolResult(content={'ok': True}, trace_id='trace-test')\n"
        "asyncio.run(serve_stdio(MimerMcpTransportConfig(), lambda _: Semantic()))\n",
        encoding="utf-8",
    )

    controller = tmp_path / "controller.py"
    entered = tmp_path / "capture-entered"
    controller.write_text(
        "import asyncio, sys\n"
        "from mcp.client.session import ClientSession\n"
        "from mcp.client.stdio import StdioServerParameters, stdio_client\n"
        "async def run():\n"
        "  async with stdio_client(StdioServerParameters(command=sys.executable, args=[sys.argv[1]], env={'CAPTURE_LOG': sys.argv[2], 'CAPTURE_ENTERED': sys.argv[3]})) as streams:\n"
        "    async with ClientSession(*streams) as session:\n"
        "      await session.initialize(); await session.call_tool('mimer.capture', {'text':'once'})\n"
        "asyncio.run(run())\n",
        encoding="utf-8",
    )

    process = __import__("subprocess").Popen(
        [sys.executable, str(controller), str(runner), str(capture_log), str(entered)],
        cwd=".", env={**os.environ, "PYTHONPATH": str(SIDECAR_ROOT)},
    )
    deadline = time.monotonic() + 10
    while not entered.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert entered.exists(), "capture did not enter the unacknowledged in-flight state"
    process.terminate()
    process.wait(timeout=10)

    async def session_call() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(runner)],
            cwd=".",
            env={"CAPTURE_LOG": str(capture_log)},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                await session.list_tools()

    asyncio.run(session_call())
    assert capture_log.read_text(encoding="utf-8") == "capture\n"
