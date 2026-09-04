"""Standalone Mimer MCP sidecar semantic package.

The package deliberately exposes the protocol-neutral semantic adapter without
loading the MCP SDK.  The SDK transport is loaded only by the console entrypoint.
"""

from .semantic import McpToolDefinition, McpToolResult, MimerMcpServer

__all__ = ["McpToolDefinition", "McpToolResult", "MimerMcpServer"]
