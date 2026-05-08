from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, Set

REPO_ROOT = Path(__file__).resolve().parents[2]

HIGH_LEVEL_ROOTS = (
    REPO_ROOT / "app" / "agents",
    REPO_ROOT / "app" / "api",
    REPO_ROOT / "app" / "services",
)

FORBIDDEN_MODULE_PREFIXES = (
    "app.llm.embeddings",
    "app.index.embeddings",
    "app.retrieval.rerank.provider",
)

# Intentional seams that may import low-level modules directly.
ALLOWLISTED_IMPORTERS = {
    "app/components/",
}


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
            for alias in node.names:
                if alias.name != "*":
                    modules.add(f"{node.module}.{alias.name}")
    return modules


def _is_forbidden_target(module: str) -> bool:
    return any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for forbidden in FORBIDDEN_MODULE_PREFIXES
    )


def _is_allowlisted_importer(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    return any(rel.startswith(prefix) for prefix in ALLOWLISTED_IMPORTERS)


def _format_violation(importer: Path, target: str) -> str:
    importer_rel = importer.relative_to(REPO_ROOT).as_posix()
    return f"{importer_rel} imports forbidden module {target}"


def test_high_level_layers_do_not_import_forbidden_low_level_modules_directly() -> None:
    violations: list[str] = []
    for root in HIGH_LEVEL_ROOTS:
        for path in _iter_py_files(root):
            if _is_allowlisted_importer(path):
                continue
            for module in _imports(path):
                if _is_forbidden_target(module):
                    violations.append(_format_violation(path, module))

    assert not violations, (
        "High-level modules must use component/facade seams instead of low-level internals.\n"
        + "\n".join(violations)
    )


def test_allowlist_scope_covers_component_adapter_seams_only() -> None:
    assert ALLOWLISTED_IMPORTERS == {
        "app/components/",
    }


def test_violation_message_contains_importer_and_forbidden_target() -> None:
    importer = REPO_ROOT / "app" / "agents" / "panel_agent" / "runtime.py"
    target = "app.llm.embeddings"
    message = _format_violation(importer, target)
    assert "app/agents/panel_agent/runtime.py" in message
    assert "app.llm.embeddings" in message
