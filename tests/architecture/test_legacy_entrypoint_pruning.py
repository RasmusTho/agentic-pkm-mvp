from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = [REPO_ROOT / "app", REPO_ROOT / "tests", REPO_ROOT / "scripts"]
FORBIDDEN_IMPORTS = {
    "app._legacy.main",
    "app._legacy.deps",
    "app._legacy.models",
    "app._legacy.settings",
    "app._legacy.capture",
    "app._legacy.capture.capture_indexer",
    "app._legacy.capture.capture_ingest",
    "app._legacy.capture.capture_sink",
    "app._legacy.capture.capture_writer",
    "app._legacy.services",
    "app._legacy.services.policy",
    "app.api.agent",
    "app.api.items",
    "app.api.ingest",
    "app.api.interesting",
    "app.api.search",
    "app.api.ui",
    "app.api.routers.dashboard",
    "app.api.routers.interesting",
    "app.cli.capture_ingest",
    "app.legacy_http",
    "app.ports.sink",
    "app.ports.pg_sink",
    "app.services.capture_sink",
    "app.services.capture_writer",
    "app.services.capture_indexer",
    "app.services.policy",
}


def _iter_py_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*.py") if path.is_file()]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_removed_legacy_entrypoints_are_not_imported() -> None:
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        for path in _iter_py_files(root):
            hits = sorted(_imports(path) & FORBIDDEN_IMPORTS)
            if hits:
                rel_path = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel_path}: {', '.join(hits)}")
    assert not offenders, (
        "Removed legacy API entrypoints must not be reintroduced as dependencies: "
        f"{offenders}"
    )
