from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys


def test_sidecar_dependency_import_filesystem_credential_and_route_boundaries() -> None:
    sidecar = Path("mimer-mcp-sidecar")
    sources = {
        path: path.read_text(encoding="utf-8")
        for path in sidecar.rglob("*.py")
    }
    assert sources, "the standalone sidecar package must exist"
    source = "\n".join(sources.values())
    manifest = (sidecar / "pyproject.toml").read_text(encoding="utf-8")
    lock = (sidecar / "requirements.txt").read_text(encoding="utf-8")
    tree = ast.parse(source)
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

    assert not any(name == "app" or name.startswith("app.") for name in imports)
    assert not any(name.startswith("app.knowledge") for name in imports)
    assert not any(name.startswith("app.governance") for name in imports)
    assert not any(name in {"pathlib", "os", "subprocess"} for name in imports)
    forbidden = (
        "vault_tools",
        "write_ops",
        "from app.governance",
        "open(",
        "Path(",
        "environ",
        "Authorization",
        "vault/",
    )
    assert not any(token in source for token in forbidden)
    assert 'mimer-mcp = "mimer_mcp_sidecar.transport:main"' in manifest
    assert "mcp>=1.29,<2" in manifest and "httpx>=0.27,<1" in manifest
    assert "app" not in manifest and "app" not in lock
    routes = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("/")
    }
    assert routes == {
        "/api/ask",
        "/api/companion/capture",
        "/search",
        "/api/artifacts/note",
        "/healthz",
    }


def test_core_only_wheel_imports_mimer_mcp_compatibility_without_sidecar(tmp_path: Path) -> None:
    """A core installation must not import or discover the optional sidecar."""
    target = tmp_path / "core-wheel"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), "."],
        check=True,
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    result = subprocess.run(
        [sys.executable, "-c", "import app.mimer_mcp; import app.mimer_mcp.server; print('ok')"],
        check=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(target)},
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "ok"
