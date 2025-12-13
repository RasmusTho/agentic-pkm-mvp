from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Set

REPO_ROOT = Path(__file__).resolve().parents[2]


def _iter_py_files(root: Path) -> Iterable[Path]:
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


def test_agents_avoid_ingest_fs_and_watcher_boundaries() -> None:
    """Agents should not reach into watcher/filesystem internals; use Stores/tools instead."""
    forbidden_prefixes = {"app.ingest.vault_alpha", "app.ingest.vault_root", "app.watcher", "watchfiles"}
    offenders: list[Path] = []
    for path in _iter_py_files(REPO_ROOT / "app" / "agents"):
        imports = _imports(path)
        if any(mod == fp or mod.startswith(fp + ".") for fp in forbidden_prefixes for mod in imports):
            offenders.append(path)
    assert not offenders, (
        "Agent modules should depend on Stores/tools, not watcher/filesystem internals: "
        f"{[str(p.relative_to(REPO_ROOT)) for p in offenders]}"
    )


def test_panel_agent_runtime_does_not_import_watcher() -> None:
    """PanelAgent runtime should not bypass watcher/tool boundaries."""
    panel_root = REPO_ROOT / "app" / "agents" / "panel_agent"
    offenders: list[Path] = []
    for path in _iter_py_files(panel_root):
        imports = _imports(path)
        if "app.watcher" in imports or "watchfiles" in imports:
            offenders.append(path)
    assert not offenders, (
        "PanelAgent must stay within agent/tool boundaries; remove watcher/file imports from: "
        f"{[str(p.relative_to(REPO_ROOT)) for p in offenders]}"
    )
