"""Lazy compatibility imports for the standalone Mimer MCP sidecar.

The implementation is packaged only in ``mimer-mcp-sidecar``.  This module
keeps legacy semantic imports working in a source checkout without introducing
the MCP SDK or a second implementation into the core runtime package.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType


def _semantic_module() -> ModuleType:
    try:
        return importlib.import_module("mimer_mcp_sidecar.semantic")
    except ModuleNotFoundError as exc:
        if exc.name != "mimer_mcp_sidecar":
            raise
    source_root = Path(__file__).parents[2] / "mimer-mcp-sidecar"
    if not source_root.is_dir():
        raise RuntimeError("The standalone mimer-mcp-sidecar package is unavailable")
    sys.path.insert(0, str(source_root))
    return importlib.import_module("mimer_mcp_sidecar.semantic")


_semantic = _semantic_module()
McpToolDefinition = _semantic.McpToolDefinition
McpToolResult = _semantic.McpToolResult
MimerMcpServer = _semantic.MimerMcpServer
_GovernedMimerHttpOperations = _semantic._GovernedMimerHttpOperations
httpx = _semantic.httpx

__all__ = ["McpToolDefinition", "McpToolResult", "MimerMcpServer"]
