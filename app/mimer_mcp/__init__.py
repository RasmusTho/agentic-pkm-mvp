"""Compatibility namespace for the separately installed Mimer MCP sidecar."""

from __future__ import annotations

from typing import Any

__all__ = ["MimerMcpServer", "McpToolResult"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from . import server

    return getattr(server, name)
