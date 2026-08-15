"""P1 static contract tests for the dev/test/prod startup redesign."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "DEV_TEST_PROD_STARTUP_REDESIGN"
README = (SPEC / "README.md").read_text()
FIXTURE = ROOT / "tests" / "fixtures" / "startup_redesign" / "channel_manifest.valid.json"


def test_kernel_contract_names_every_invariant() -> None:
    for invariant in range(1, 10):
        assert f"**K{invariant}:**" in README


def test_manifest_fixture_is_secret_free() -> None:
    manifest = json.loads(FIXTURE.read_text())
    assert set(manifest) >= {
        "schema_version", "channel", "intent", "compose_project", "artifact",
        "identities", "llm_policy", "gateway", "secret_references",
    }
    assert manifest["intent"] == "promotion"
    assert manifest["artifact"]["image_index_digest"].startswith("sha256:")
    assert manifest["secret_references"]
    assert not any("secret" in key and key != "secret_references" for key in manifest)
    serialized = json.dumps(manifest).lower()
    assert "password" not in serialized and "token" not in serialized


def test_operation_contract_names_truthful_terminal_phases() -> None:
    assert "failed_after_migration" in README
    assert "PASS" in README
    assert "fails closed" in README
