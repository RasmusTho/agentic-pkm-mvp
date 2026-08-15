from __future__ import annotations

import ast
from pathlib import Path


def _unordered_state_lock_lines(source: str) -> list[int]:
    tree = ast.parse(source)
    acquisition = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_acquire"
    )
    violations: list[int] = []

    def visit(node: ast.AST, *, ownership_fenced: bool) -> None:
        if isinstance(node, ast.With):
            contexts = [ast.unparse(item.context_expr) for item in node.items]
            fenced = ownership_fenced
            for context in contexts:
                if "_state_locked" in context and not fenced:
                    violations.append(node.lineno)
                if "active_binding_fence" in context:
                    fenced = True
            for statement in node.body:
                visit(statement, ownership_fenced=fenced)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, ownership_fenced=ownership_fenced)

    visit(acquisition, ownership_fenced=False)
    return violations


def test_production_callers_take_the_ownership_fence_before_the_binding_lease() -> None:
    source = Path("app/instance/binding_effect_lease.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert _unordered_state_lock_lines(source) == []

    for name in ("shared_effect", "exclusive_change"):
        assert "self._acquire" in ast.unparse(methods[name])

    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"acquire_shared", "acquire_exclusive"}
        for node in ast.walk(tree)
    )

    inverted = """
class Example:
    def _acquire(self):
        with self._state_locked('binding-a'), self.active_binding_fence('binding-a'):
            self._mutate()
"""
    assert _unordered_state_lock_lines(inverted)
