from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _function_node(path: str, qualified_name: str) -> ast.FunctionDef:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    parts = qualified_name.split(".")
    nodes: list[ast.AST] = list(tree.body)
    for part in parts:
        matching = [
            node
            for node in nodes
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
            and node.name == part
        ]
        assert len(matching) == 1, f"{path}:{qualified_name} is not uniquely defined"
        selected = matching[0]
        nodes = list(selected.body)
    assert isinstance(selected, ast.FunctionDef)
    return selected


def _called_names(path: str, qualified_name: str) -> set[str]:
    function = _function_node(path, qualified_name)
    names: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _call_keywords(
    path: str,
    qualified_name: str,
    called_name: str,
) -> set[str]:
    function = _function_node(path, qualified_name)
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if name == called_name:
            return {keyword.arg for keyword in node.keywords if keyword.arg is not None}
    raise AssertionError(f"{path}:{qualified_name} does not call {called_name}")


def test_product_llm_execution_seams_preserve_provider_enforcement() -> None:
    """Bounded census of Product seams that can select or execute a model provider.

    Reporting-only health/doctor/settings readers and explicit mock CLI defaults
    are intentionally excluded: they do not execute a provider. Every real
    execution seam below must either enforce through the shared configuration
    helper, delegate to the canonical router/fabric, or carry an explicit
    already-resolved provider override.
    """

    shared_guard_seams = {
        ("app/config/llm.py", "get_provider"): "ensure_provider",
        ("app/services/llm.py", "call_llm"): "ensure_provider",
        ("app/components/llm/router.py", "LLMRouter.__init__"): "ensure_provider",
        ("app/reasoning/provider.py", "_execution_provider"): "ensure_provider",
        ("app/llm/adapter.py", "_prov"): "get_provider",
        ("app/llm/embeddings.py", "_provider"): "get_provider",
        ("app/llm/embeddings.py", "get_primary_provider"): "get_provider",
    }
    for (path, function), required_call in shared_guard_seams.items():
        assert required_call in _called_names(path, function), (
            f"{path}:{function} must call {required_call}"
        )

    canonical_delegates = {
        ("app/components/llm/fabric.py", "get_chat_client"): "LLMRouter",
        ("app/agents/qa/agent.py", "_call_llm"): "get_chat_client",
        ("app/planner/provider.py", "LLMPlanner.plan"): "get_chat_client",
        (
            "app/reasoning/provider.py",
            "_call_chat_with_route",
        ): "get_chat_client",
        (
            "app/chat/reflection_conversation.py",
            "_call_reflection_llm",
        ): "call_llm",
    }
    for (path, function), required_call in canonical_delegates.items():
        assert required_call in _called_names(path, function), (
            f"{path}:{function} must delegate to {required_call}"
        )

    assert "provider_override" in _call_keywords(
        "app/components/llm/fabric.py",
        "ChatClient.chat",
        "call_llm",
    )
    embedding_calls = _called_names(
        "app/components/embeddings/legacy.py",
        "resolve_embedding_identity",
    )
    assert {"get_embedding_provider", "get_primary_provider"} <= embedding_calls
