"""Product chat routes must name models through the shared registry.

Embedding identity remains an independent subsystem and is intentionally not
scanned here. A compatibility alias, if one is needed, must be added to the
small reviewed allowlist below and covered by the relevant route test.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.components.settings.models_loader import load_models


REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_CHAT_SOURCES = (
    "app/agents/qa/agent.py",
    "app/chat/reflection_conversation.py",
    "app/cli/health.py",
    "app/components/llm/fabric.py",
    "app/components/llm/router.py",
    "app/components/reasoning/facade.py",
    "app/eval/llm_client.py",
    "app/planner/provider.py",
    "app/reasoning/provider.py",
    "app/services/llm.py",
)
EXPLICIT_CHAT_MODEL_ALIASES: frozenset[str] = frozenset()
_MODEL_ID = re.compile(
    r"(?<![A-Za-z0-9])(?:gpt-[A-Za-z0-9][A-Za-z0-9._:-]*"
    r"|claude-[A-Za-z0-9][A-Za-z0-9._:-]*"
    r"|deepseek-[A-Za-z0-9][A-Za-z0-9._:-]*"
    r"|llama[0-9][A-Za-z0-9._:-]*)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _product_runtime_model_ids() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for relative_path in PRODUCT_CHAT_SOURCES:
        path = REPO_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.update(
                    (model_id, relative_path)
                    for model_id in _MODEL_ID.findall(node.value)
                )
    return found


def test_product_runtime_model_ids_are_registry_backed() -> None:
    registered_chat_models = {
        descriptor.model
        for descriptor in load_models().values()
        if descriptor.kind == "chat"
    }
    unregistered = sorted(
        (model_id, path)
        for model_id, path in _product_runtime_model_ids()
        if model_id not in registered_chat_models
        and model_id not in EXPLICIT_CHAT_MODEL_ALIASES
    )

    assert not unregistered, (
        "Product chat model IDs must come from registered descriptors; add only a "
        "reviewed compatibility alias to EXPLICIT_CHAT_MODEL_ALIASES: "
        f"{unregistered}"
    )
