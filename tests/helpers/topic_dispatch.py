"""AST helpers for keeping worker topic-coverage tests aligned."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any


def enumerate_topic_comparators(
    source: str,
    module_ns: Mapping[str, Any],
) -> list[str]:
    """Resolve topic constants and string literals in a dispatch if/elif chain."""
    tree = ast.parse(source)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)

    comparators: list[ast.expr] = []

    def _walk_if_chain(node: ast.stmt) -> None:
        if not isinstance(node, ast.If):
            return
        test = node.test
        if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "topic":
            if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
                raise AssertionError(
                    "dispatch table uses an unsupported topic comparison; "
                    "extend enumerate_topic_comparators so the topic cannot ship uncovered."
                )
            comparators.extend(test.comparators)
        for stmt in node.orelse:
            _walk_if_chain(stmt)

    for stmt in func_def.body:
        _walk_if_chain(stmt)

    resolved: list[str] = []
    for comparator in comparators:
        if isinstance(comparator, ast.Constant):
            assert isinstance(comparator.value, str), (
                "dispatch table compares topic against a non-string literal "
                f"{comparator.value!r}"
            )
            resolved.append(comparator.value)
        elif isinstance(comparator, ast.Name):
            name = comparator.id
            assert name in module_ns, f"dispatch table references undefined name {name!r}"
            value = module_ns[name]
            assert isinstance(value, str), f"dispatch table constant {name!r} is not a string topic"
            resolved.append(value)
        else:  # pragma: no cover - guards against an unrecognized comparator form
            raise AssertionError(
                "dispatch table compares topic against an unsupported node "
                f"{type(comparator).__name__}; extend enumerate_topic_comparators "
                "so the topic cannot ship uncovered."
            )
    return resolved
