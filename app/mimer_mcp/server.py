"""Lazy compatibility imports for the standalone Mimer MCP sidecar.

The implementation is packaged only in ``mimer-mcp-sidecar``.  This module
keeps legacy semantic imports working in a source checkout without introducing
the MCP SDK or a second implementation into the core runtime package.
"""

from __future__ import annotations

import importlib
from typing import Any


def _semantic_module() -> Any:
    try:
        return importlib.import_module("mimer_mcp_sidecar.semantic")
    except ModuleNotFoundError as exc:
        if exc.name != "mimer_mcp_sidecar":
            raise
        raise RuntimeError(
            "Mimer MCP semantics require the separately installed mimer-mcp-sidecar distribution"
        ) from exc


__all__ = ["McpToolDefinition", "McpToolResult", "MimerMcpServer"]  # noqa: F822


def __getattr__(name: str) -> Any:
    if name not in {*__all__, "_GovernedMimerHttpOperations", "httpx"}:
        raise AttributeError(name)
    return getattr(_semantic_module(), name)
