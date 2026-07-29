from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import urllib.request

import pytest

import llm_contract as kernel
from llm_contract import SchemaValidationError, validate_schema_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
KERNEL_ROOT = REPO_ROOT / "llm_contract"


def test_kernel_imports_no_runtime_module(tmp_path: Path) -> None:
    imported: set[str] = set()
    for path in KERNEL_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not {module for module in imported if module == "app" or module.startswith("app.")}

    env = os.environ.copy()
    env.pop("LLM_PROVIDER", None)
    env["LLM_PROVIDER_ENFORCE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = """
import json
import os
import socket
import sys
import urllib.request

sys.path.append(sys.argv[1])
egress_attempts = []

def block_egress(*args, **kwargs):
    egress_attempts.append(repr(args))
    raise AssertionError("neutral-kernel import attempted network egress")

socket.socket.connect = block_egress
socket.socket.connect_ex = block_egress
socket.socket.sendto = block_egress
socket.create_connection = block_egress
urllib.request.urlopen = block_egress

before = dict(os.environ)
before_app_modules = {
    name for name in sys.modules if name == "app" or name.startswith("app.")
}
import llm_contract
after = dict(os.environ)
new_app_modules = {
    name
    for name in sys.modules
    if (name == "app" or name.startswith("app.")) and name not in before_app_modules
}
print(json.dumps({
    "preexisting_app_modules": sorted(before_app_modules),
    "env_unchanged": before == after,
    "kernel_loaded": "llm_contract" in sys.modules,
    "provider_config_loaded": "app.config.llm" in sys.modules,
    "unexpected_app_modules": sorted(new_app_modules),
    "egress_attempts": egress_attempts,
}))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            code,
            sysconfig.get_paths()["purelib"],
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "preexisting_app_modules": [],
        "env_unchanged": True,
        "kernel_loaded": True,
        "provider_config_loaded": False,
        "unexpected_app_modules": [],
        "egress_attempts": [],
    }
    assert list(tmp_path.iterdir()) == []


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


def test_schema_validation_rejects_non_local_refs_without_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retrieval_attempts: list[str] = []

    def _record_retrieval(url: str, *args: object, **kwargs: object) -> None:
        retrieval_attempts.append(url)
        raise AssertionError("schema validation attempted external retrieval")

    monkeypatch.setattr(urllib.request, "urlopen", _record_retrieval)
    schema = {
        "type": "object",
        "properties": {
            "answer": {"$ref": "https://schemas.example.invalid/answer.json"}
        },
    }

    with pytest.raises(SchemaValidationError, match="non-local.*\\$ref"):
        validate_schema_payload("answer.v1", schema, {"answer": "bounded"})

    assert retrieval_attempts == []


def test_schema_validation_allows_resolvable_local_refs_and_normalizes_missing_refs() -> None:
    schema = {
        "$defs": {
            "answer": {
                "type": "string",
            }
        },
        "type": "object",
        "properties": {
            "answer": {"$ref": "#/$defs/answer"},
        },
        "required": ["answer"],
    }

    assert validate_schema_payload("answer.v1", schema, {"answer": "bounded"}) == {
        "answer": "bounded"
    }

    missing_ref_schema = {
        "type": "object",
        "properties": {
            "answer": {"$ref": "#/$defs/missing"},
        },
    }
    with pytest.raises(
        SchemaValidationError,
        match="unresolvable local schema reference",
    ):
        validate_schema_payload(
            "missing-ref.v1",
            missing_ref_schema,
            {"answer": "bounded"},
        )
