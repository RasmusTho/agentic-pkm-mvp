from __future__ import annotations

import ast
from pathlib import Path


def test_sidecar_dependency_import_filesystem_credential_and_route_boundaries() -> None:
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
