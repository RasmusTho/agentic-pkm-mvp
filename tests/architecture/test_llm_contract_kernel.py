from __future__ import annotations

import ast
from pathlib import Path

import pytest

import app.llm_contract as kernel
from app.llm_contract import SchemaValidationError, validate_schema_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
KERNEL_ROOT = REPO_ROOT / "app" / "llm_contract"


def test_kernel_imports_no_runtime_module() -> None:
    imported: set[str] = set()
    for path in KERNEL_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not {module for module in imported if module == "app" or module.startswith("app.")}


def test_kernel_exposes_exactly_the_adr0063_contracts() -> None:
    required_exports = {
        "ADAPTER_FAILURE_CLASSES",
        "FALLBACK_REQUIREMENTS",
        "AdapterResult",
        "FallbackRequirement",
        "IndependenceRequirement",
        "ModelAccessIntent",
        "ModelAccessResolver",
        "ModelCapabilities",
        "ModelCapabilityRequirements",
        "ModelResolutionRequest",
        "ModelTurnAdapter",
        "ResolvedModelAccess",
        "SchemaValidationError",
        "SchemaValidator",
        "validate_adapter_failure_class",
        "validate_resolved_group",
        "validate_schema_payload",
    }
    assert required_exports <= set(kernel.__all__)
    assert kernel.FALLBACK_REQUIREMENTS == frozenset(
        {
            "fallback_forbidden",
            "fallback_same_identity",
            "fallback_compatible_identity",
            "fallback_policy_selected",
            "human_decision_required",
        }
    )
    assert kernel.ADAPTER_FAILURE_CLASSES == frozenset(
        {
            "command_exit_nonzero",
            "command_timeout",
            "stdout_empty",
            "stdout_oversize",
            "stdout_unavailable",
            "output_contains_allowed_environment",
            "unexpected_adapter_error",
            "credential_unavailable",
            "session_expired",
        }
    )

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    assert validate_schema_payload("answer.v1", schema, {"answer": "bounded"}) == {
        "answer": "bounded"
    }
    with pytest.raises(SchemaValidationError, match="answer.v1"):
        validate_schema_payload("answer.v1", schema, {"unexpected": True})
