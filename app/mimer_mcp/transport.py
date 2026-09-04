"""B1 stdio-only wire transport for the external Mimer MCP adapter.

This module intentionally has no HTTP-server imports or socket operations.  It
adapts the five already-governed semantic tools to the SDK's client-spawned
stdio lifecycle and retains no request or capture state across process exits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

from mcp import types
from mcp.server import InitializationOptions, NotificationOptions, Server
from mcp.server.stdio import stdio_server

from .server import McpToolResult, MimerMcpServer

_LOG = logging.getLogger("app.mimer_mcp")
_ALLOWED_TRANSPORT = "stdio"
_DEFAULT_BASE_URL = "http://127.0.0.1:8000"


@dataclass(frozen=True)
class MimerMcpTransportConfig:
    """Fail-closed configuration for ADR-0061 B1/C1.

    ``transport`` is intentionally a field rather than a future extensibility
    hook: every value other than ``stdio`` is rejected before SDK construction.
    Network listener and authentication inputs are rejected instead of ignored.
    """

    transport: str = _ALLOWED_TRANSPORT
    base_url: str = _DEFAULT_BASE_URL
    bind: str | None = None
    port: int | None = None
    tls_cert: str | None = None
    tls_key: str | None = None
    auth_token: str | None = None

    def validate(self) -> None:
        if self.transport != _ALLOWED_TRANSPORT:
            raise ValueError("Mimer MCP v1 supports only the stdio transport")
        if any(value is not None for value in (self.bind, self.port, self.tls_cert, self.tls_key, self.auth_token)):
            raise ValueError("Mimer MCP stdio transport rejects network, TLS, and auth configuration")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Mimer MCP v1 requires a loopback HTTP API endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Mimer MCP loopback endpoint must not carry credentials or URL options")


def _tool_definitions(semantic: MimerMcpServer) -> list[types.Tool]:
    return [
        types.Tool(
            name=tool.name,
            description=tool.description,
            inputSchema=tool.input_schema,
        )
        for tool in semantic.list_tools()
    ]


def _result_content(result: McpToolResult) -> list[types.TextContent]:
    payload: Mapping[str, Any] | dict[str, Any]
    if result.is_error:
        payload = result.error or {"error": "unknown"}
    else:
        payload = {"result": result.content}
    if result.trace_id:
        payload = {**payload, "trace_id": result.trace_id}
    return [types.TextContent(type="text", text=json.dumps(payload, separators=(",", ":"), default=str))]


def create_stdio_server(semantic: MimerMcpServer) -> Server:
    """Create the SDK server with only the delivered five semantic tools."""

    server = Server("mimer-mcp", version="1")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return _tool_definitions(semantic)

    @server.call_tool(validate_input=True)
    async def call_tool(name: str, arguments: Mapping[str, Any]) -> types.CallToolResult:
        result = semantic.call_tool(name, arguments)
        if name == "mimer.health":
            _LOG.info(
                "mimer_mcp_health transport=stdio readiness=%s dependency=%s",
                "degraded" if result.is_error else "ready",
                "loopback_http",
            )
        return types.CallToolResult(content=_result_content(result), isError=result.is_error)

    return server


async def serve_stdio(
    config: MimerMcpTransportConfig,
    semantic_factory: Callable[[str], MimerMcpServer] = MimerMcpServer.for_loopback,
) -> None:
    """Run one client-spawned stdio server until the client closes its streams."""

    config.validate()
    semantic = semantic_factory(config.base_url)
    server = create_stdio_server(semantic)
    try:
        async with stdio_server() as (read_stream, write_stream):
            _LOG.info("mimer_mcp_started transport=stdio readiness=ready dependency=loopback_http")
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="mimer-mcp",
                    server_version="1",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    finally:
        _LOG.info("mimer_mcp_stopped transport=stdio")


def parse_config(argv: Sequence[str] | None = None) -> MimerMcpTransportConfig:
    """Parse only the accepted B1 inputs; rejected switches fail before startup."""

    import argparse

    parser = argparse.ArgumentParser(prog="python -m app.mimer_mcp")
    parser.add_argument("--transport", default=_ALLOWED_TRANSPORT)
    parser.add_argument("--base-url", default=_DEFAULT_BASE_URL)
    parser.add_argument("--bind")
    parser.add_argument("--port", type=int)
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    parser.add_argument("--auth-token")
    parsed = parser.parse_args(argv)
    config = MimerMcpTransportConfig(**vars(parsed))
    config.validate()
    return config


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint; diagnostics go to stderr via standard logging."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        config = parse_config(argv)
    except (SystemExit, ValueError) as exc:
        if isinstance(exc, SystemExit):
            raise
        _LOG.error("mimer_mcp_configuration_rejected reason=%s", exc)
        return 2
    asyncio.run(serve_stdio(config))
    return 0
