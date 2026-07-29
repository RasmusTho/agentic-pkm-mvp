from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import llm_contract as kernel
from llm_contract import SchemaValidationError, validate_schema_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
KERNEL_ROOT = REPO_ROOT / "llm_contract"


def test_kernel_imports_no_runtime_module() -> None:
    """Static and dynamic proof that `llm_contract` never touches `app`.

    This is the direct regression test for the 2026-07-29 change-control
    correction on issue #4290: `app/__init__.py` runs Product LLM provider
    enforcement (env reads, module-global mutation, and a RuntimeError under
    `LLM_PROVIDER_ENFORCE=1` with no provider) before any `app.*` child can be
    imported. A kernel that imported an `app.*` module would trigger that
    enforcement path merely by being imported. Two checks:

    1. AST scan — no `import app` / `from app...` appears anywhere in the
       kernel source, regardless of whether it would execute at import time.
    2. Fresh-subprocess check — actually importing `llm_contract` in a clean
       process, with `LLM_PROVIDER_ENFORCE=1` set and no `LLM_PROVIDER`,
       proves the import neither loads `app`/`app.*` into `sys.modules`, nor
       mutates the environment, nor writes a filesystem artifact. Under
       enforce mode, an `app.*` import would raise — so this is the exact
       failure mode the correction exists to prevent.
    """
    imported: set[str] = set()
    for path in KERNEL_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert not {module for module in imported if module == "app" or module.startswith("app.")}

    # sys.path is extended in-code (sys.path.insert), not via a PYTHONPATH
    # env var override: on this repo's dev machines a non-empty PYTHONPATH
    # observably changes which of two candidate site-packages directories a
    # Homebrew-framework Python resolves (a harness quirk unrelated to the
    # kernel), which would make this test flaky for reasons that have
    # nothing to do with the invariant under test.
    probe = (
        "import sys, json, os\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "pre_env = dict(os.environ)\n"
        "import llm_contract\n"
        "app_loaded = any(m == 'app' or m.startswith('app.') for m in sys.modules)\n"
        "env_changed = pre_env != dict(os.environ)\n"
        "print(json.dumps({'app_loaded': app_loaded, 'env_changed': env_changed}))\n"
    )

    with tempfile.TemporaryDirectory() as tmp_cwd:
        # Inherit the parent interpreter's environment (so this subprocess
        # resolves site-packages/user-site the same way the parent pytest
        # process does across machines) and override only what the probe
        # itself cares about: enforcement on, no configured provider.
        env = dict(os.environ)
        env.pop("LLM_PROVIDER", None)
        env["LLM_PROVIDER_ENFORCE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=tmp_cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"fresh-process import of llm_contract failed under "
            f"LLM_PROVIDER_ENFORCE=1 with no provider "
            f"(stdout={result.stdout!r}, stderr={result.stderr!r})"
        )
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["app_loaded"] is False, (
            "importing llm_contract must not load app or any app.* module"
        )
        assert payload["env_changed"] is False, (
            "importing llm_contract must not mutate the process environment"
        )

        artifacts = list(Path(tmp_cwd).iterdir())
        assert artifacts == [], (
            f"importing llm_contract must create no filesystem artifact in cwd: {artifacts}"
        )


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
