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
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
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


def test_knowledge_adapters_are_resolved_only_via_service_boundary() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_importers = {
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "service.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_importers:
                continue
            imports = _imports(path)
            if "app.knowledge.adapters" in imports:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct app.knowledge.adapters imports are forbidden outside the service boundary: "
        f"{offenders}"
    )


def test_vault_note_writes_use_knowledge_port_helpers() -> None:
    guarded_files = {
        REPO_ROOT / "app" / "agents" / "note_hygiene" / "agent.py",
        REPO_ROOT / "app" / "settings" / "compiler.py",
        REPO_ROOT / "app" / "settings" / "writeback.py",
        REPO_ROOT / "app" / "settings" / "yggdrasil_scaffolder.py",
        REPO_ROOT / "app" / "vault" / "layout.py",
    }
    offenders: list[str] = []
    for path in guarded_files:
        if "write_text" in _all_calls(path):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Guarded vault-facing modules must not call Path.write_text directly; route writes via KnowledgePort helpers: "
        f"{offenders}"
    )


def test_knowledge_port_resolution_is_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_paths = {
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "service.py",
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_paths:
                continue
            raw = path.read_text(encoding="utf-8")
            if "resolve_knowledge_port" in raw:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct resolve_knowledge_port usage is forbidden outside app/knowledge; "
        "use app.knowledge.write_ops helpers instead: "
        f"{offenders}"
    )


def test_absolute_locator_conversion_is_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_paths = {
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "locators.py",
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_paths:
                continue
            raw = path.read_text(encoding="utf-8")
            if "make_note_locator_from_absolute" in raw:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct make_note_locator_from_absolute usage is forbidden outside app/knowledge; "
        "use app.knowledge.write_ops helpers instead: "
        f"{offenders}"
    )


def test_locator_module_imports_are_centralized() -> None:
    scan_roots = [REPO_ROOT / "app", REPO_ROOT / "scripts"]
    allow_importers = {
        REPO_ROOT / "app" / "knowledge" / "adapters.py",
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "locators.py",
        REPO_ROOT / "app" / "knowledge" / "write_ops.py",
    }
    offenders: list[str] = []
    for root in scan_roots:
        for path in _iter_py_files(root):
            if path in allow_importers:
                continue
            imports = _imports(path)
            if "app.knowledge.locators" in imports:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "Direct app.knowledge.locators imports are forbidden outside app/knowledge; "
        "use app.knowledge.write_ops helpers instead: "
        f"{offenders}"
    )


def test_legacy_fs_watcher_has_no_direct_vault_note_writes() -> None:
    watcher_path = REPO_ROOT / "scripts" / "fs_watcher.py"
    tree = ast.parse(watcher_path.read_text(encoding="utf-8"))
    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "write_text":
            offenders.append(node.lineno)
    assert not offenders, (
        "Legacy fs watcher must write notes via VaultPort adapter methods, not direct Path.write_text: "
        f"{offenders}"
    )
