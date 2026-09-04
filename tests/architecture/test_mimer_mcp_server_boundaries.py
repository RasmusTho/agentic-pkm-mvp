from __future__ import annotations

import ast
from pathlib import Path


def test_external_server_does_not_import_internal_vault_tools() -> None:
    tree = ast.parse(Path("app/mimer_mcp/server.py").read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert "app.mcp.vault_tools" not in imports
    assert not any(name.startswith("app.orchestrator") for name in imports)
    assert not any(name.startswith("app.knowledge") for name in imports)


def test_stdio_transport_has_no_core_runtime_or_filesystem_authority() -> None:
    tree = ast.parse(Path("app/mimer_mcp/transport.py").read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert "app.api" not in imports
    assert not any(name.startswith("app.knowledge") for name in imports)
    assert not any(name.startswith("app.governance") for name in imports)
    assert "pathlib" not in imports
    assert "os" not in imports
