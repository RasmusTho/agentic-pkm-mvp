from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _iter_py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if p.is_file()]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
    return modules


def test_api_routes_avoid_direct_psycopg():
    api_root = REPO_ROOT / "app" / "api"
    allowed = {api_root / "routes" / "search.py"}
    offenders = []
    for path in _iter_py_files(api_root):
        if path in allowed:
            continue
        imports = _imports(path)
        if "psycopg" in imports:
            offenders.append(path)
    assert not offenders, f"API routes should use stores/resolvers, not direct psycopg imports: {offenders}"


def test_agents_do_not_depend_on_fastapi():
    agents_root = REPO_ROOT / "app" / "agents"
    offenders = []
    for path in _iter_py_files(agents_root):
        imports = _imports(path)
        if "fastapi" in imports or "starlette" in imports:
            offenders.append(path)
    assert not offenders, f"Agent modules should stay server-agnostic; found FastAPI imports in: {offenders}"
