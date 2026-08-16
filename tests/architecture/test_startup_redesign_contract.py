"""P1 static contract tests for the dev/test/prod startup redesign."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "DEV_TEST_PROD_STARTUP_REDESIGN"
README = (SPEC / "README.md").read_text()
FIXTURE = ROOT / "tests" / "fixtures" / "startup_redesign" / "channel_manifest.valid.json"
RECEIPT_FIXTURE = ROOT / "tests" / "fixtures" / "startup_redesign" / "promotion_receipt.valid.json"


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
    "schema_version", "channel", "mode", "intent", "compose_project", "artifact",
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
    if manifest["mode"] == "local-source":
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
    assert manifest["mode"] in {"local-source", "promotion"}
    assert manifest["intent"] in {"ordinary-boot", "promotion"}
    if manifest["mode"] == "local-source":
        assert manifest["channel"] in {"dev", "local-test"}
        assert manifest["intent"] == "ordinary-boot"
    else:
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
    assert type(gateway["port"]) is int and 1 <= gateway["port"] <= 65535
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
        "schema_version", "channel", "mode", "intent", "compose_project", "artifact",
        "identities", "llm_policy", "gateway", "secret_references",
    }
    assert manifest["intent"] == "promotion"
    assert manifest["mode"] == "promotion"
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


def test_manifest_schema_rejects_boolean_gateway_port() -> None:
    manifest = json.loads(FIXTURE.read_text())
    manifest["gateway"]["port"] = True
    with pytest.raises(AssertionError):
        _assert_manifest_shape(manifest)


def test_manifest_schema_rejects_local_source_on_promotion_channels() -> None:
    manifest = json.loads(FIXTURE.read_text())
    manifest["mode"] = "local-source"
    manifest["intent"] = "ordinary-boot"
    manifest["artifact"]["dirty_state"] = "clean"
    manifest["artifact"]["promotion_eligible"] = False
    for channel in ("promotion-test", "prod"):
        manifest["channel"] = channel
        with pytest.raises(AssertionError):
            _assert_manifest_shape(manifest)


def test_manifest_schema_represents_ordinary_boot_by_mode() -> None:
    manifest = json.loads(FIXTURE.read_text())
    manifest["intent"] = "ordinary-boot"
    _assert_manifest_shape(manifest)


def test_operation_contract_names_truthful_terminal_phases() -> None:
    for phase in (
        "PRE_MUTATION_FAILURE", "FAILED_AFTER_MIGRATION", "ACTIVATION_FAILURE", "PASS",
        "ORDINARY_BOOT_PASS",
    ):
        assert f"`{phase}`" in README
    assert "takes precedence over any later activation/health failure" in README
    assert "without any migration/schema mutation" in README
    assert "A journal attempt alone is not migration" in README
    assert "successful read-only" in README


def test_receipt_contract_names_binding_freshness_and_revocation() -> None:
    for field in (
        "receipt_version", "receipt_id", "outcome", "artifact_digest", "config_identity",
        "test_identity", "vault_identity", "schema_identity", "required_checks", "issued_at",
        "fresh_until",
    ):
        assert f"`{field}`" in README
    assert "content-addressed" in README
    assert "exactly equal the versioned external policy" in README
    assert "`receipt_id` excluded" in README
    assert "machine-readable" in README and "promotion-receipt-registry.v1" in README


RECEIPT_FIELDS = {
    "receipt_version", "receipt_id", "outcome", "artifact_digest", "config_identity",
    "test_identity", "vault_identity", "schema_identity", "required_checks", "issued_at",
    "fresh_until", "issuer_id", "issuer_signature",
}
EXPECTED_RECEIPT_CHECKS = ["migration", "readiness", "schema", "smoke", "ui", "version"]
REGISTRY_FIXTURE = ROOT / "tests" / "fixtures" / "startup_redesign" / "promotion_receipt_registry.valid.json"


def _receipt_digest_body(receipt: dict[str, object]) -> bytes:
    body = {key: value for key, value in receipt.items() if key != "receipt_id"}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _assert_receipt_schema(
    receipt: dict[str, object],
    registry: dict[str, object] | None,
    *,
    now: str,
    expected_manifest: dict[str, str],
) -> None:
    if registry is None:
        raise AssertionError("revocation/issuer registry lookup must fail closed")
    assert set(receipt) == RECEIPT_FIELDS
    assert receipt["receipt_version"] == "promotion-receipt.v1"
    assert receipt["outcome"] in {"PASS", "FAIL"}
    assert isinstance(receipt["receipt_id"], str)
    assert receipt["receipt_id"] == "sha256:" + hashlib.sha256(_receipt_digest_body(receipt)).hexdigest()
    assert receipt["required_checks"] == EXPECTED_RECEIPT_CHECKS
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["artifact_digest"])
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["config_identity"])
    for field in ("artifact_digest", "config_identity", "vault_identity", "schema_identity"):
        assert receipt[field] == expected_manifest[field]
    assert all(isinstance(receipt[field], str) and re.fullmatch(r"[A-Za-z0-9._:-]+", receipt[field]) for field in ("test_identity", "vault_identity", "schema_identity"))
    assert receipt["issuer_id"] == "promotion-test-issuer"
    assert receipt["issuer_signature"] == "sig:v1:promotion-test-issuer:attestation"
    assert isinstance(receipt["issued_at"], str) and receipt["issued_at"].endswith("Z")
    assert isinstance(receipt["fresh_until"], str) and receipt["fresh_until"].endswith("Z")
    assert receipt["issued_at"] <= now < receipt["fresh_until"]
    assert registry["registry_version"] == "promotion-receipt-registry.v1"
    entry = registry["entries"][receipt["receipt_id"]]
    assert entry["issuer_id"] == receipt["issuer_id"]
    assert entry["issuer_signature"] == receipt["issuer_signature"]
    assert entry["status"] == "issued"
    _assert_secret_free(receipt)


def test_promotion_receipt_fixture_has_machine_readable_schema() -> None:
    receipt = json.loads(RECEIPT_FIXTURE.read_text())
    registry = json.loads(REGISTRY_FIXTURE.read_text())
    expected = {"artifact_digest": receipt["artifact_digest"], "config_identity": receipt["config_identity"], "vault_identity": receipt["vault_identity"], "schema_identity": receipt["schema_identity"]}
    _assert_receipt_schema(receipt, registry, now="2026-08-16T12:00:00Z", expected_manifest=expected)


def test_promotion_receipt_schema_rejects_tampering_stale_checks_and_revocation() -> None:
    receipt = json.loads(RECEIPT_FIXTURE.read_text())
    registry = json.loads(REGISTRY_FIXTURE.read_text())
    tampered = dict(receipt)
    tampered["config_identity"] = "sha256:" + "c" * 64
    with pytest.raises(AssertionError):
        _assert_receipt_schema(tampered, registry, now="2026-08-16T12:00:00Z", expected_manifest=receipt)

    incomplete = dict(receipt)
    incomplete["required_checks"] = ["smoke"]
    with pytest.raises(AssertionError):
        _assert_receipt_schema(incomplete, registry, now="2026-08-16T12:00:00Z", expected_manifest=receipt)

    revoked = json.loads(json.dumps(registry))
    revoked["entries"][receipt["receipt_id"]]["status"] = "revoked"
    with pytest.raises(AssertionError):
        _assert_receipt_schema(receipt, revoked, now="2026-08-16T12:00:00Z", expected_manifest=receipt)

    stale = json.loads(RECEIPT_FIXTURE.read_text())
    with pytest.raises(AssertionError):
        _assert_receipt_schema(stale, registry, now="2026-08-18T00:00:00Z", expected_manifest=receipt)

    wrong_manifest = json.loads(RECEIPT_FIXTURE.read_text())
    wrong_manifest["artifact_digest"] = "sha256:" + "c" * 64
    with pytest.raises(AssertionError):
        wrong_manifest["receipt_id"] = "sha256:" + hashlib.sha256(_receipt_digest_body(wrong_manifest)).hexdigest()
        _assert_receipt_schema(wrong_manifest, registry, now="2026-08-16T12:00:00Z", expected_manifest=receipt)

    secret_bearing = json.loads(RECEIPT_FIXTURE.read_text())
    secret_bearing["vault_identity"] = "admin:hunter2"
    with pytest.raises(AssertionError):
        secret_bearing["receipt_id"] = "sha256:" + hashlib.sha256(_receipt_digest_body(secret_bearing)).hexdigest()
        _assert_receipt_schema(secret_bearing, registry, now="2026-08-16T12:00:00Z", expected_manifest=receipt)

    with pytest.raises(AssertionError):
        _assert_receipt_schema(receipt, None, now="2026-08-16T12:00:00Z", expected_manifest=receipt)
