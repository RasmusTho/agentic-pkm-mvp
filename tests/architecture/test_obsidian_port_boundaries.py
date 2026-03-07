from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]


def _iter_py_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if p.is_file()]


def _all_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            calls.add(fn.id)
        elif isinstance(fn, ast.Attribute):
            calls.add(fn.attr)
    return calls


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


def test_note_locator_construction_is_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_calls = {
        REPO_ROOT / "app" / "knowledge" / "locators.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_calls:
                continue
            if "NoteLocator" in _all_calls(path):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct NoteLocator(...) construction is forbidden outside app/knowledge/locators.py: "
        f"{offenders}"
    )


def test_obsidian_vault_name_env_is_read_only_in_vault_identity() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_paths = {
        REPO_ROOT / "app" / "knowledge" / "vault_identity.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_paths:
                continue
            raw = path.read_text(encoding="utf-8")
            if "OBSIDIAN_VAULT_NAME" in raw:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "OBSIDIAN_VAULT_NAME should be resolved only via app/knowledge/vault_identity.py: "
        f"{offenders}"
    )


def test_advanced_uri_builder_imports_are_constrained() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_importers = {
        REPO_ROOT / "app" / "services" / "inbox.py",
        REPO_ROOT / "scripts" / "fs_watcher.py",
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_importers:
                continue
            imports = _imports(path)
            if "app.knowledge.references" in imports:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "build_obsidian_advanced_uri usage should stay in approved boundary modules: "
        f"{offenders}"
    )
