"""Checked-in sealed inventory for future GOV revocation producers."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


GOV_REVOCATION_INVENTORY_SCHEMA = "agentic-pkm.gov-revocation-producers.v1"
_CANONICAL_BOUNDARY_DEFINITION_DIGESTS = {
    "_KnownBinding": "f18a5e2845440bf446103154e5026afa12bfd044a3146580ac01c386f8313f8b",
    "RegistryBindingAuthorizer.__setattr__": "82735f84d023d6fa7579b01b314d84eca1413f05c29fdd2f8e5468f6b6c2a5c0",
    "RegistryBindingAuthorizer.__init__": "3bbb4bb8ff2adf8790bd7730685e0f0e2a28ba5420c91ebbabc7d4a65cb55cbc",
    "RegistryBindingAuthorizer.set_binding": "d2692318e9fc1b22f5401059a49547a70f452e89910752faeea2f13056c280ca",
    "RegistryBindingAuthorizer.authorize": "b7b0e7cd424fab2c465f9816e7a3b2048379ce5e8cb98947997fc326a93db3ba",
}


@dataclass(frozen=True)
class GovRevocationProducerEvidence:
    name: str
    ownership_fence: bool
    exclusive_binding_lease: bool


def _canonical_boundary_definitions(tree: ast.Module) -> dict[str, list[ast.AST]]:
    definitions: dict[str, list[ast.AST]] = {
        name: [] for name in _CANONICAL_BOUNDARY_DEFINITION_DIGESTS
    }
    for statement in tree.body:
        if isinstance(statement, ast.ClassDef) and statement.name == "_KnownBinding":
            definitions[statement.name].append(statement)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name in definitions:
                definitions[statement.name].append(statement)
        elif isinstance(statement, ast.ClassDef) and statement.name == "RegistryBindingAuthorizer":
            for member in statement.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = f"RegistryBindingAuthorizer.{member.name}"
                    if name in definitions:
                        definitions[name].append(member)
    return definitions


def _canonical_boundary_shape_is_exact(tree: ast.Module) -> bool:
    definitions = _canonical_boundary_definitions(tree)
    for name, expected_digest in _CANONICAL_BOUNDARY_DEFINITION_DIGESTS.items():
        nodes = definitions[name]
        if len(nodes) != 1:
            return False
        digest = hashlib.sha256(ast.dump(nodes[0], include_attributes=False).encode()).hexdigest()
        if digest != expected_digest:
            return False
    return True


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


class _RevocationVisitor(ast.NodeVisitor):
    def __init__(self, module: str, *, postponed_annotations: bool) -> None:
        self.module = module
        self.postponed_annotations = postponed_annotations
        self.scope: list[str] = []
        self.direct_entrypoint_references: set[int] = set()
        self.producers: dict[str, GovRevocationProducerEvidence] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self.scope.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        if not self.postponed_annotations:
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ):
                if argument.annotation is not None:
                    self.visit(argument.annotation)
            for optional_argument in (node.args.vararg, node.args.kwarg):
                if optional_argument is not None and optional_argument.annotation is not None:
                    self.visit(optional_argument.annotation)
            if node.returns is not None:
                self.visit(node.returns)
        self.scope.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        if not self.postponed_annotations:
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ):
                if argument.annotation is not None:
                    self.visit(argument.annotation)
            for optional_argument in (node.args.vararg, node.args.kwarg):
                if optional_argument is not None and optional_argument.annotation is not None:
                    self.visit(optional_argument.annotation)
            if node.returns is not None:
                self.visit(node.returns)
        self.scope.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def _record_sealed_producer(self) -> None:
        if self.module == "app/governance/binding_authority" and ".".join(self.scope) in {
            "RegistryBindingAuthorizer.__init__",
            "RegistryBindingAuthorizer.set_binding",
        }:
            return
        scope = ".".join(self.scope) or "<module>"
        name = f"{self.module}:{scope}"
        self.producers[name] = GovRevocationProducerEvidence(
            name=name,
            ownership_fence=False,
            exclusive_binding_lease=False,
        )

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if (
            node.attr
            in {
                "set_binding",
                "RegistryBindingAuthorizer",
                "_known",
                "_RegistryBindingAuthorizer__known",
            }
            and id(node) not in self.direct_entrypoint_references
        ):
            self._record_sealed_producer()
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if (
            isinstance(node.ctx, ast.Load)
            and node.id
            in {
                "RegistryBindingAuthorizer",
                "_REVOCATION_CAPABILITY_SECRET",
                "_RevocationCapability",
            }
            and id(node) not in self.direct_entrypoint_references
        ):
            self._record_sealed_producer()
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if any(
            (
                item.name == "RegistryBindingAuthorizer"
                and item.asname not in {None, "RegistryBindingAuthorizer"}
            )
            or item.name
            in {
                "_test_revocation_capability",
                "_REVOCATION_CAPABILITY_SECRET",
                "_RevocationCapability",
            }
            for item in node.names
        ):
            self._record_sealed_producer()

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        revoked = next((item.value for item in node.keywords if item.arg == "revoked"), None)
        expanded_keywords = any(item.arg is None for item in node.keywords)
        definitely_empty = isinstance(
            revoked, (ast.Set, ast.List, ast.Tuple, ast.Dict)
        ) and not getattr(revoked, "elts", getattr(revoked, "keys", ()))
        definitely_false = isinstance(revoked, ast.Constant) and revoked.value is False
        recognized_entrypoint = name in {"set_binding", "RegistryBindingAuthorizer"}
        possible_direct_revocation = recognized_entrypoint and (
            expanded_keywords
            or (revoked is not None and not definitely_empty and not definitely_false)
        )
        possible_indirect_revocation = (
            not recognized_entrypoint
            and revoked is not None
            and not definitely_empty
            and not definitely_false
        )
        dynamic_entrypoint = name in {
            "getattr",
            "__getattribute__",
            "methodcaller",
            "attrgetter",
        } and any(
            isinstance(argument, ast.Constant)
            and argument.value in {"set_binding", "RegistryBindingAuthorizer"}
            for argument in node.args
        )
        capability_entrypoint = name == "_test_revocation_capability" or any(
            item.arg == "_revocation_capability" for item in node.keywords
        )
        if (
            possible_direct_revocation
            or possible_indirect_revocation
            or dynamic_entrypoint
            or capability_entrypoint
        ):
            self._record_sealed_producer()

        if recognized_entrypoint:
            self.direct_entrypoint_references.add(id(node.func))
        try:
            self.generic_visit(node)
        finally:
            self.direct_entrypoint_references.discard(id(node.func))


def discover_gov_revocation_producer_evidence(
    app_root: Path,
) -> Mapping[str, GovRevocationProducerEvidence]:
    """Derive the production revocation mutation-seam population from source."""

    discovered: dict[str, GovRevocationProducerEvidence] = {}
    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = path.relative_to(app_root.parent).with_suffix("").as_posix()
        postponed_annotations = any(
            isinstance(statement, ast.ImportFrom)
            and statement.module == "__future__"
            and any(item.name == "annotations" for item in statement.names)
            for statement in tree.body
        )
        visitor = _RevocationVisitor(module, postponed_annotations=postponed_annotations)
        visitor.visit(tree)
        if module == "app/governance/binding_authority" and not _canonical_boundary_shape_is_exact(
            tree
        ):
            name = f"{module}:<canonical-boundary-shape>"
            visitor.producers[name] = GovRevocationProducerEvidence(
                name=name,
                ownership_fence=False,
                exclusive_binding_lease=False,
            )
        for name, evidence in visitor.producers.items():
            previous = discovered.get(name)
            if previous is not None and previous != evidence:
                raise ValueError(f"conflicting GOV revocation evidence for {name}")
            discovered[name] = evidence
    return discovered


def discover_gov_revocation_producers(app_root: Path) -> frozenset[str]:
    return frozenset(discover_gov_revocation_producer_evidence(app_root))


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


def validate_gov_revocation_coverage(document: Mapping[str, Any], *, app_root: Path) -> None:
    validate_gov_revocation_inventory(document)
    declared = {
        str(item["name"]): item
        for item in document["producers"]  # type: ignore[index]
    }
    discovered = discover_gov_revocation_producer_evidence(app_root)
    if set(declared) != set(discovered):
        raise ValueError(
            "GOV revocation inventory differs from source mutation seams: "
            f"missing={sorted(set(discovered) - set(declared))}, "
            f"stale={sorted(set(declared) - set(discovered))}"
        )
    for name, evidence in discovered.items():
        entry = declared[name]
        if (
            entry.get("ownership_fence") is not evidence.ownership_fence
            or entry.get("exclusive_binding_lease") is not evidence.exclusive_binding_lease
            or not evidence.ownership_fence
            or not evidence.exclusive_binding_lease
        ):
            raise ValueError(
                f"GOV revocation producer {name} lacks source-proved ownership/exclusive fencing"
            )


def load_gov_revocation_inventory(path: Path) -> Mapping[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("GOV revocation producer inventory must be a mapping")
    validate_gov_revocation_inventory(document)
    return document


__all__ = [
    "discover_gov_revocation_producers",
    "discover_gov_revocation_producer_evidence",
    "GovRevocationProducerEvidence",
    "load_gov_revocation_inventory",
    "validate_gov_revocation_coverage",
    "validate_gov_revocation_inventory",
]
