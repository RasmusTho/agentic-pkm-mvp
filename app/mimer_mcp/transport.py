"""Lazy compatibility entrypoint for the standalone Mimer MCP sidecar.

Core Mimer deliberately does not depend on the MCP SDK.  Install and invoke
the ``mimer-mcp`` sidecar distribution for wire transport support.
"""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    try:
        from mimer_mcp_sidecar.transport import main as sidecar_main
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Mimer MCP transport is supplied by the standalone mimer-mcp-sidecar distribution"
        ) from exc
    return sidecar_main(argv)
