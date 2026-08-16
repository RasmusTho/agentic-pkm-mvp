"""P1 static contract tests for the dev/test/prod startup redesign."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "DEV_TEST_PROD_STARTUP_REDESIGN"
README = (SPEC / "README.md").read_text()
FIXTURE = ROOT / "tests" / "fixtures" / "startup_redesign" / "channel_manifest.valid.json"


def test_kernel_contract_names_every_invariant() -> None:
    for invariant in range(1, 10):
        assert re.search(
            rf"\|\s*\*\*K{invariant}\*\*\s*\|\s*`[a-z_]+`\s*\|",
            README,
        ), f"K{invariant} must have a structured enforcement phase"


SENSITIVE_FIELD = re.compile(
    r"(?:secret|password|token|credential|private[_-]?key|api[_-]?key|access[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
SECRET_REFERENCE = re.compile(r"(?:keychain|vault|secret)://[A-Za-z0-9._/-]+\Z")


def _assert_secret_free(value: object, *, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "secret_references":
                assert isinstance(child, list) and child, f"{child_path} must be a non-empty list"
                for reference in child:
                    assert isinstance(reference, str), f"{child_path} must contain strings"
                    assert SECRET_REFERENCE.fullmatch(reference), f"invalid secret reference: {child_path}"
                continue
            assert not SENSITIVE_FIELD.search(key), f"sensitive field is not allowed: {child_path}"
            _assert_secret_free(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_secret_free(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        assert not SENSITIVE_FIELD.search(value), f"sensitive value is not allowed: {path}"


def test_manifest_fixture_is_secret_free() -> None:
    manifest = json.loads(FIXTURE.read_text())
    assert set(manifest) >= {
        "schema_version", "channel", "intent", "compose_project", "artifact",
        "identities", "llm_policy", "gateway", "secret_references",
    }
    assert manifest["intent"] == "promotion"
    assert manifest["artifact"]["image_index_digest"].startswith("sha256:")
    _assert_secret_free(manifest)


def test_operation_contract_names_truthful_terminal_phases() -> None:
    for phase in ("PRE_MUTATION_FAILURE", "FAILED_AFTER_MIGRATION", "ACTIVATION_FAILURE", "PASS"):
        assert f"`{phase}`" in README
