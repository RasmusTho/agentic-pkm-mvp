"""P1 static contract tests for the dev/test/prod startup redesign."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

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
MANIFEST_FIELDS = {
    "schema_version", "channel", "intent", "compose_project", "artifact",
    "identities", "llm_policy", "gateway", "secret_references",
}
ARTIFACT_FIELDS = {"repository", "image_index_digest", "platform_digest", "source_sha"}
LOCAL_ARTIFACT_FIELDS = ARTIFACT_FIELDS | {"dirty_state", "promotion_eligible"}
IDENTITY_FIELDS = {"database", "vault", "config", "migration"}
GATEWAY_FIELDS = {"port", "identity"}
HEX_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
CHANNEL_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
MIGRATION_IDENTITY = re.compile(r"alembic:[A-Za-z0-9._-]+\Z")
COMPOSE_PROJECT = re.compile(r"pkm-[a-z0-9-]+\Z")
REPOSITORY = re.compile(r"ghcr\.io/[A-Za-z0-9._/-]+\Z")


def _assert_manifest_shape(manifest: dict[str, object]) -> None:
    assert set(manifest) == MANIFEST_FIELDS
    artifact = manifest["artifact"]
    identities = manifest["identities"]
    gateway = manifest["gateway"]
    assert isinstance(artifact, dict)
    if manifest["intent"] == "local-source":
        assert set(artifact) == LOCAL_ARTIFACT_FIELDS
        assert artifact["dirty_state"] in {"clean", "dirty"}
        assert artifact["promotion_eligible"] is False
    else:
        assert set(artifact) == ARTIFACT_FIELDS
    assert isinstance(identities, dict) and set(identities) == IDENTITY_FIELDS
    assert isinstance(gateway, dict) and set(gateway) == GATEWAY_FIELDS
    assert isinstance(manifest["secret_references"], list)
    assert manifest["schema_version"] == "channel-manifest.v1"
    assert manifest["channel"] in {"dev", "local-test", "promotion-test", "prod"}
    assert manifest["intent"] in {"local-source", "ordinary-boot", "promotion"}
    if manifest["intent"] == "local-source":
        assert manifest["channel"] in {"dev", "local-test"}
    elif manifest["intent"] == "promotion":
        assert manifest["channel"] in {"promotion-test", "prod"}
    assert isinstance(manifest["compose_project"], str) and COMPOSE_PROJECT.fullmatch(manifest["compose_project"])
    assert isinstance(manifest["artifact"], dict)
    assert REPOSITORY.fullmatch(manifest["artifact"]["repository"])
    assert HEX_DIGEST.fullmatch(manifest["artifact"]["image_index_digest"])
    assert HEX_DIGEST.fullmatch(manifest["artifact"]["platform_digest"])
    assert SOURCE_SHA.fullmatch(manifest["artifact"]["source_sha"])
    assert isinstance(identities["database"], str) and CHANNEL_IDENTITY.fullmatch(identities["database"])
    assert isinstance(identities["vault"], str) and CHANNEL_IDENTITY.fullmatch(identities["vault"])
    assert isinstance(identities["config"], str) and HEX_DIGEST.fullmatch(identities["config"])
    assert isinstance(identities["migration"], str) and MIGRATION_IDENTITY.fullmatch(identities["migration"])
    assert manifest["llm_policy"] in {"declared-required", "declared-optional", "disabled"}
    assert isinstance(gateway["port"], int) and 1 <= gateway["port"] <= 65535
    assert isinstance(gateway["identity"], str) and CHANNEL_IDENTITY.fullmatch(gateway["identity"])


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
        assert "@" not in value and "://" not in value, f"credential-bearing URI is not allowed: {path}"
        assert not re.search(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]*", value), f"API key is not allowed: {path}"


def test_manifest_fixture_is_secret_free() -> None:
    manifest = json.loads(FIXTURE.read_text())
    assert set(manifest) >= {
        "schema_version", "channel", "intent", "compose_project", "artifact",
        "identities", "llm_policy", "gateway", "secret_references",
    }
    assert manifest["intent"] == "promotion"
    assert manifest["artifact"]["image_index_digest"].startswith("sha256:")
    _assert_manifest_shape(manifest)
    _assert_secret_free(manifest)


def test_manifest_schema_rejects_unvalidated_sensitive_fields() -> None:
    manifest = json.loads(FIXTURE.read_text())
    manifest["auth"] = "Bearer sk-live-example"
    with pytest.raises(AssertionError):
        _assert_manifest_shape(manifest)

    manifest = json.loads(FIXTURE.read_text())
    manifest["identities"]["database"] = "admin:hunter2"
    with pytest.raises(AssertionError):
        _assert_manifest_shape(manifest)

    manifest = json.loads(FIXTURE.read_text())
    manifest["identities"]["config"] = "config-value"
    with pytest.raises(AssertionError):
        _assert_manifest_shape(manifest)

    manifest = json.loads(FIXTURE.read_text())
    manifest["identities"]["migration"] = "admin:hunter2"
    with pytest.raises(AssertionError):
        _assert_manifest_shape(manifest)

    manifest = json.loads(FIXTURE.read_text())
    manifest["gateway"]["identity"] = "admin:hunter2"
    with pytest.raises(AssertionError):
        _assert_manifest_shape(manifest)


def test_manifest_schema_rejects_local_source_on_promotion_channels() -> None:
    manifest = json.loads(FIXTURE.read_text())
    manifest["intent"] = "local-source"
    manifest["artifact"]["dirty_state"] = "clean"
    manifest["artifact"]["promotion_eligible"] = False
    for channel in ("promotion-test", "prod"):
        manifest["channel"] = channel
        with pytest.raises(AssertionError):
            _assert_manifest_shape(manifest)


def test_operation_contract_names_truthful_terminal_phases() -> None:
    for phase in ("PRE_MUTATION_FAILURE", "FAILED_AFTER_MIGRATION", "ACTIVATION_FAILURE", "PASS"):
        assert f"`{phase}`" in README
    assert "takes precedence over any later activation/health failure" in README
    assert "without any migration/schema mutation" in README
    assert "A journal attempt alone is not migration" in README
