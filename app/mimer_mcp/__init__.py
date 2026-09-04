"""Protocol-neutral external Mimer MCP semantic adapter.

The wire/process package is deliberately owned by MIMER-MCP-03.  This package
only maps the five accepted MCP operations to Mimer's governed HTTP contract.
"""

from .server import MimerMcpServer, McpToolResult

__all__ = ["MimerMcpServer", "McpToolResult"]
