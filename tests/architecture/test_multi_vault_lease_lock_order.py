from __future__ import annotations

import ast
from pathlib import Path


def test_production_callers_take_the_ownership_fence_before_the_binding_lease() -> None:
    source = Path("app/instance/binding_effect_lease.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    acquisition = methods["_acquire"]
    with_nodes = [node for node in ast.walk(acquisition) if isinstance(node, ast.With)]
    assert any(
        "active_binding_fence" in ast.unparse(item.context_expr)
        and any("_state_locked" in ast.unparse(child) for child in ast.walk(node))
        for node in with_nodes
        for item in node.items
    )

    for name in ("shared_effect", "exclusive_change"):
        assert "self._acquire" in ast.unparse(methods[name])

    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"acquire_shared", "acquire_exclusive"}
        for node in ast.walk(tree)
    )
