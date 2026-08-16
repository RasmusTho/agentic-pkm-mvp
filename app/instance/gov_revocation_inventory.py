"""Checked-in sealed inventory for future GOV revocation producers."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Mapping


GOV_REVOCATION_INVENTORY_SCHEMA = "agentic-pkm.gov-revocation-producers.v1"


class _RevocationVisitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        self.producers: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else ""
        )
        revoked = next((item.value for item in node.keywords if item.arg == "revoked"), None)
        is_mutation = name == "set_binding" and revoked is not None
        is_seed = name == "RegistryBindingAuthorizer" and revoked is not None
        definitely_empty = (
            isinstance(revoked, (ast.Set, ast.List, ast.Tuple, ast.Dict))
            and not getattr(revoked, "elts", getattr(revoked, "keys", ()))
        )
        definitely_false = isinstance(revoked, ast.Constant) and revoked.value is False
        if (is_mutation or is_seed) and not definitely_empty and not definitely_false:
            scope = ".".join(self.scope) or "<module>"
            self.producers.add(f"{self.module}:{scope}")
        self.generic_visit(node)


def discover_gov_revocation_producers(app_root: Path) -> frozenset[str]:
    """Derive the production revocation mutation-seam population from source."""

    discovered: set[str] = set()
    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = path.relative_to(app_root.parent).with_suffix("").as_posix()
        visitor = _RevocationVisitor(module)
        visitor.visit(tree)
        discovered.update(visitor.producers)
    return frozenset(discovered)


def validate_gov_revocation_inventory(document: Mapping[str, Any]) -> None:
    if document.get("schema") != GOV_REVOCATION_INVENTORY_SCHEMA:
        raise ValueError("unknown GOV revocation producer inventory schema")
    producers = document.get("producers")
    if not isinstance(producers, list):
        raise ValueError("GOV revocation producers must be a list")
    for producer in producers:
        if not isinstance(producer, dict) or not isinstance(producer.get("name"), str):
            raise ValueError("GOV revocation producer entry is malformed")
        if producer.get("enabled") is not True:
            raise ValueError("inventory entries describe enabled producers only")
        if producer.get("ownership_fence") is not True:
            raise ValueError("enabled GOV revocation producer lacks the ownership fence")
        if producer.get("exclusive_binding_lease") is not True:
            raise ValueError("enabled GOV revocation producer lacks the exclusive binding lease")


def validate_gov_revocation_coverage(
    document: Mapping[str, Any], *, app_root: Path
) -> None:
    validate_gov_revocation_inventory(document)
    declared = {str(item["name"]) for item in document["producers"]}  # type: ignore[index]
    discovered = set(discover_gov_revocation_producers(app_root))
    if declared != discovered:
        raise ValueError(
            "GOV revocation inventory differs from source mutation seams: "
            f"missing={sorted(discovered - declared)}, stale={sorted(declared - discovered)}"
        )


def load_gov_revocation_inventory(path: Path) -> Mapping[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("GOV revocation producer inventory must be a mapping")
    validate_gov_revocation_inventory(document)
    return document


__all__ = [
    "discover_gov_revocation_producers",
    "load_gov_revocation_inventory",
    "validate_gov_revocation_coverage",
    "validate_gov_revocation_inventory",
]
