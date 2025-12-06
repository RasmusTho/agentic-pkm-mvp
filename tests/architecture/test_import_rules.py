from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Set

REPO_ROOT = Path(__file__).resolve().parents[2]


def _iter_py_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if p.is_file()]


def _imports(path: Path) -> Set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_api_routes_do_not_use_psycopg_directly() -> None:
    """API layer should not talk to psycopg directly; use Stores/Outbox/services."""
    api_root = REPO_ROOT / "app" / "api"
    allowlist = {
        REPO_ROOT / "app" / "api" / "routes" / "search.py",  # legacy dependency until refactored
    }
    offenders: list[Path] = []
    for path in _iter_py_files(api_root):
        if path in allowlist:
            continue
        imports = _imports(path)
        if any(mod.startswith("psycopg") for mod in imports):
            offenders.append(path)
    assert not offenders, (
        "API routes should use Stores/Outbox/services, not direct psycopg access: "
        f"{[str(p.relative_to(REPO_ROOT)) for p in offenders]}"
    )


def test_agents_do_not_depend_on_fastapi() -> None:
    """Agents should be server-agnostic; no FastAPI/Starlette imports."""
    agents_root = REPO_ROOT / "app" / "agents"
    offenders: list[Path] = []
    for path in _iter_py_files(agents_root):
        imports = _imports(path)
        if "fastapi" in imports or "starlette" in imports:
            offenders.append(path)
    assert not offenders, (
        "Agent modules should stay server-agnostic; found FastAPI/Starlette imports in: "
        f"{[str(p.relative_to(REPO_ROOT)) for p in offenders]}"
    )
