"""Checked-in sealed inventory for future GOV revocation producers."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


GOV_REVOCATION_INVENTORY_SCHEMA = "agentic-pkm.gov-revocation-producers.v1"


@dataclass(frozen=True)
class GovRevocationProducerEvidence:
    name: str
    ownership_fence: bool
    exclusive_binding_lease: bool


@dataclass(frozen=True)
class _EnteredContext:
    name: str
    binding_expression: str | None


def _binding_expression(call: ast.Call) -> str | None:
    expression: ast.expr | None = call.args[0] if call.args else None
    if expression is None:
        expression = next(
            (
                item.value
                for item in call.keywords
                if item.arg in {"binding_id", "vault_binding_id"}
            ),
            None,
        )
    return (
        ast.dump(expression, annotate_fields=True, include_attributes=False)
        if expression is not None
        else None
    )


def _entered_context(expression: ast.expr) -> _EnteredContext | None:
    if not isinstance(expression, ast.Call):
        return None
    function = expression.func
    if isinstance(function, ast.Attribute):
        return _EnteredContext(function.attr, _binding_expression(expression))
    if isinstance(function, ast.Name):
        return _EnteredContext(function.id, _binding_expression(expression))
    return None


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _contains_entrypoint_reference(expression: ast.AST) -> bool:
    """Find a revocation-capable reference without treating a direct call as an alias."""

    if isinstance(expression, ast.Attribute) and expression.attr == "set_binding":
        return True
    if isinstance(expression, ast.Name) and expression.id == "RegistryBindingAuthorizer":
        return True
    if isinstance(expression, ast.Call):
        return _call_name(expression) in {"getattr", "methodcaller"} and any(
            isinstance(argument, ast.Constant) and argument.value == "set_binding"
            for argument in expression.args
        )
    return any(_contains_entrypoint_reference(child) for child in ast.iter_child_nodes(expression))


class _RevocationVisitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        self.with_contexts: list[list[_EnteredContext]] = []
        self.producers: dict[str, GovRevocationProducerEvidence] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        self.scope.append(node.name)
        entered_contexts = self.with_contexts
        self.with_contexts = []
        for statement in node.body:
            self.visit(statement)
        self.with_contexts = entered_contexts
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        self.scope.append(node.name)
        entered_contexts = self.with_contexts
        self.with_contexts = []
        for statement in node.body:
            self.visit(statement)
        self.with_contexts = entered_contexts
        self.scope.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        self.visit(node.args)
        entered_contexts = self.with_contexts
        self.with_contexts = []
        self.visit(node.body)
        self.with_contexts = entered_contexts

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:  # noqa: N802
        entered_contexts = self.with_contexts
        self.with_contexts = []
        self.generic_visit(node)
        self.with_contexts = entered_contexts

    def _record(self, evidence: GovRevocationProducerEvidence) -> None:
        previous = self.producers.get(evidence.name)
        if previous is not None:
            # A producer function with one fenced and one unfenced seam is
            # unfenced as a whole; inventory cannot bless only the safe call.
            evidence = GovRevocationProducerEvidence(
                name=evidence.name,
                ownership_fence=(previous.ownership_fence and evidence.ownership_fence),
                exclusive_binding_lease=(
                    previous.exclusive_binding_lease and evidence.exclusive_binding_lease
                ),
            )
        self.producers[evidence.name] = evidence

    def _record_unsafe_reference(self) -> None:
        scope = ".".join(self.scope) or "<module>"
        self._record(
            GovRevocationProducerEvidence(
                name=f"{self.module}:{scope}",
                ownership_fence=False,
                exclusive_binding_lease=False,
            )
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        if _contains_entrypoint_reference(node.value):
            self._record_unsafe_reference()
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if node.value is not None and _contains_entrypoint_reference(node.value):
            self._record_unsafe_reference()
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
        if _contains_entrypoint_reference(node.value):
            self._record_unsafe_reference()
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        if node.value is not None and _contains_entrypoint_reference(node.value):
            self._record_unsafe_reference()
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if any(
            item.name == "RegistryBindingAuthorizer"
            and item.asname not in {None, "RegistryBindingAuthorizer"}
            for item in node.names
        ):
            self._record_unsafe_reference()

    def visit_With(self, node: ast.With) -> None:
        contexts: list[_EnteredContext] = []
        self.with_contexts.append(contexts)
        for item in node.items:
            self.visit(item.context_expr)
            entered = _entered_context(item.context_expr)
            if entered is not None:
                contexts.append(entered)
        for statement in node.body:
            self.visit(statement)
        self.with_contexts.pop()

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        contexts: list[_EnteredContext] = []
        self.with_contexts.append(contexts)
        for item in node.items:
            self.visit(item.context_expr)
            entered = _entered_context(item.context_expr)
            if entered is not None:
                contexts.append(entered)
        for statement in node.body:
            self.visit(statement)
        self.with_contexts.pop()

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        revoked = next((item.value for item in node.keywords if item.arg == "revoked"), None)
        expanded_keywords = any(item.arg is None for item in node.keywords)
        is_mutation = name == "set_binding" and revoked is not None
        is_seed = name == "RegistryBindingAuthorizer" and revoked is not None
        definitely_empty = isinstance(
            revoked, (ast.Set, ast.List, ast.Tuple, ast.Dict)
        ) and not getattr(revoked, "elts", getattr(revoked, "keys", ()))
        definitely_false = isinstance(revoked, ast.Constant) and revoked.value is False
        possible_recognized_revocation = (
            name in {"set_binding", "RegistryBindingAuthorizer"} and expanded_keywords
        )
        possible_indirect_revocation = (
            name not in {"set_binding", "RegistryBindingAuthorizer", "_KnownBinding"}
            and revoked is not None
            and not definitely_empty
            and not definitely_false
        )
        passes_entrypoint_reference = any(
            _contains_entrypoint_reference(argument)
            for argument in (
                *node.args,
                *(item.value for item in node.keywords),
            )
        )
        if possible_indirect_revocation or passes_entrypoint_reference:
            self._record_unsafe_reference()
        if (
            (is_mutation or is_seed or possible_recognized_revocation)
            and not definitely_empty
            and not definitely_false
        ):
            scope = ".".join(self.scope) or "<module>"
            producer_name = f"{self.module}:{scope}"
            mutation_binding = _binding_expression(node) if is_mutation else None
            if is_seed and isinstance(revoked, (ast.Set, ast.List, ast.Tuple)):
                if len(revoked.elts) == 1:
                    mutation_binding = ast.dump(
                        revoked.elts[0], annotate_fields=True, include_attributes=False
                    )
            active_contexts = [context for group in self.with_contexts for context in group]
            ownership_indexes = [
                index
                for index, context in enumerate(active_contexts)
                if context.name == "active_binding_fence"
                and context.binding_expression is not None
                and context.binding_expression == mutation_binding
            ]
            exclusive_indexes = [
                index
                for index, context in enumerate(active_contexts)
                if context.name == "exclusive_change"
                and context.binding_expression is not None
                and context.binding_expression == mutation_binding
            ]
            ownership_fence = bool(ownership_indexes)
            first_ownership = min(ownership_indexes, default=-1)
            ordered_exclusive = (
                first_ownership >= 0
                and bool(exclusive_indexes)
                and all(exclusive_index > first_ownership for exclusive_index in exclusive_indexes)
            )
            evidence = GovRevocationProducerEvidence(
                name=producer_name,
                ownership_fence=ownership_fence,
                exclusive_binding_lease=ordered_exclusive,
            )
            self._record(evidence)
        self.generic_visit(node)


def discover_gov_revocation_producer_evidence(
    app_root: Path,
) -> Mapping[str, GovRevocationProducerEvidence]:
    """Derive the production revocation mutation-seam population from source."""

    discovered: dict[str, GovRevocationProducerEvidence] = {}
    for path in sorted(app_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = path.relative_to(app_root.parent).with_suffix("").as_posix()
        visitor = _RevocationVisitor(module)
        visitor.visit(tree)
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
