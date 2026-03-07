from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IMPORT_RULES_PATH = REPO_ROOT / "tests" / "architecture" / "test_import_rules.py"
OBSIDIAN_BOUNDARIES_PATH = REPO_ROOT / "tests" / "architecture" / "test_obsidian_port_boundaries.py"

EXPECTED_FORBIDDEN = {
    "test_high_level_imports_use_components_entrypoints": {
        "app.llm.embeddings",
        "app.index.embeddings",
        "app.search.embeddings",
        "app.retrieval.rerank",
        "app.retrieval.rerank.provider",
        "app.search.rerank",
    },
    "test_high_level_llm_access_uses_fabric": {
        "app.llm.adapter",
        "app.llm.embeddings",
        "app.services.llm",
    },
}


def _load_module(path: Path) -> ast.Module:
    if not path.exists():
        raise AssertionError(f"Missing architecture test at {path}")
    return ast.parse(path.read_text(encoding="utf-8"))


def _find_function(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Expected {name} in {IMPORT_RULES_PATH}")


def _path_from_expr(expr: ast.AST) -> Path | None:
    if isinstance(expr, ast.Name) and expr.id == "REPO_ROOT":
        return REPO_ROOT
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return Path(expr.value)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _path_from_expr(expr.left)
        right = _path_from_expr(expr.right)
        if left is None or right is None:
            return None
        return left / right
    return None


def _extract_paths(func: ast.FunctionDef, name: str) -> list[Path]:
    for node in func.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    value = node.value
                    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                        paths: list[Path] = []
                        for elt in value.elts:
                            path = _path_from_expr(elt)
                            if path is None:
                                raise AssertionError(
                                    f"Unable to parse {name} entry in {func.name}"
                                )
                            paths.append(path)
                        return paths
                    raise AssertionError(f"Expected {name} to be a list/set in {func.name}")
    raise AssertionError(f"Missing {name} in {func.name}")


def _extract_str_set(func: ast.FunctionDef, name: str) -> set[str]:
    for node in func.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        value = ast.literal_eval(node.value)
                    except Exception as exc:
                        raise AssertionError(f"Unable to parse {name} in {func.name}: {exc}") from exc
                    if not isinstance(value, (set, list, tuple)):
                        raise AssertionError(f"Expected {name} to be a set/list in {func.name}")
                    items = {str(item) for item in value}
                    return items
    raise AssertionError(f"Missing {name} in {func.name}")


def test_import_boundary_tests_dont_allow_escape_hatches() -> None:
    """
    Ensure architecture tests don't have escape hatches.

    Validates that:
    - scan_roots and allow_subpaths don't overlap
    - forbidden patterns haven't been weakened
    - new "temporary" exceptions aren't added

    See: docs/ARCHITECTURE.md §Agent Implementation Pattern
    """
    module = _load_module(IMPORT_RULES_PATH)
    text = IMPORT_RULES_PATH.read_text(encoding="utf-8")
    if "temporary" in text.lower():
        raise AssertionError(
            "Architecture tests must not add temporary exceptions; remove 'temporary' markers."
        )

    for func_name, expected_forbidden in EXPECTED_FORBIDDEN.items():
        func = _find_function(module, func_name)
        scan_roots = set(_extract_paths(func, "scan_roots"))
        allow_subpaths = set(_extract_paths(func, "allow_subpaths"))
        overlap = scan_roots & allow_subpaths
        if overlap:
            overlap_paths = [str(path.relative_to(REPO_ROOT)) for path in sorted(overlap, key=str)]
            raise AssertionError(
                f"scan_roots and allow_subpaths overlap in {func_name}: {overlap_paths}"
            )
        forbidden = _extract_str_set(func, "forbidden")
        missing = expected_forbidden - forbidden
        if missing:
            raise AssertionError(
                f"Forbidden patterns weakened in {func_name}; missing: {sorted(missing)}"
            )


def test_obsidian_boundary_guardrails_dont_allow_escape_hatches() -> None:
    module = _load_module(OBSIDIAN_BOUNDARIES_PATH)
    text = OBSIDIAN_BOUNDARIES_PATH.read_text(encoding="utf-8")
    if "temporary" in text.lower():
        raise AssertionError(
            "Obsidian boundary tests must not add temporary exceptions; remove 'temporary' markers."
        )

    expected_note_locator_allow = {
        REPO_ROOT / "app" / "knowledge" / "locators.py",
    }
    expected_vault_env_allow = {
        REPO_ROOT / "app" / "knowledge" / "vault_identity.py",
    }
    expected_uri_importers_allow = {
        REPO_ROOT / "app" / "services" / "inbox.py",
        REPO_ROOT / "scripts" / "fs_watcher.py",
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
    }
    expected_adapters_importers_allow = {
        REPO_ROOT / "app" / "knowledge" / "__init__.py",
        REPO_ROOT / "app" / "knowledge" / "service.py",
    }

    note_func = _find_function(module, "test_note_locator_construction_is_centralized")
    note_allow = set(_extract_paths(note_func, "allow_calls"))
    assert note_allow == expected_note_locator_allow

    env_func = _find_function(module, "test_obsidian_vault_name_env_is_read_only_in_vault_identity")
    env_allow = set(_extract_paths(env_func, "allow_paths"))
    assert env_allow == expected_vault_env_allow

    uri_func = _find_function(module, "test_advanced_uri_builder_imports_are_constrained")
    uri_allow = set(_extract_paths(uri_func, "allow_importers"))
    assert uri_allow == expected_uri_importers_allow

    adapters_func = _find_function(module, "test_knowledge_adapters_are_resolved_only_via_service_boundary")
    adapters_allow = set(_extract_paths(adapters_func, "allow_importers"))
    assert adapters_allow == expected_adapters_importers_allow
