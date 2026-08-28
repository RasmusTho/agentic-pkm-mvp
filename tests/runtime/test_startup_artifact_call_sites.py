"""Startup-redesign production call-site proofs and deferred skeletons."""

from __future__ import annotations

import hashlib
import ast
import json
import subprocess
import sys

from pathlib import Path

import pytest
import yaml

from app.release_channels.channel_manifest import (
    ArtifactRenderError,
    create_promotion_candidate,
    render_channel_manifest,
)
from app.release_channels.ordinary_boot import (
    OrdinaryBootJournalError,
    run_ordinary_boot,
)


SKELETON = Path(__file__).read_text()


def test_future_runtime_call_sites_are_explicitly_deferred() -> None:
    """P1 proves deferral posture; later slices must replace these skeletons."""
    assert SKELETON.count("\n@pytest.mark.xfail(strict=True") == 2
    assert SKELETON.count("\n    raise NotImplementedError") == 2
    assert "production call-site proof" in SKELETON


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_FIXTURE = ROOT / "tests" / "fixtures" / "startup_redesign" / "channel_manifest.valid.json"
DIGEST = "sha256:" + "b" * 64


def _move_platform_image_to_database(compose: dict[str, object]) -> None:
    services = compose["services"]
    services["database"]["image"] = services["api"]["image"]
    services["api"]["image"] = f"ghcr.io/example/other@sha256:{'d' * 64}"


def _promotion_manifest() -> dict[str, object]:
    manifest = json.loads(MANIFEST_FIXTURE.read_text(encoding="utf-8"))
    manifest["channel"] = "prod"
    manifest["compose_project"] = "pkm-prod"
    manifest["identities"]["database"] = "prod-db-v1"
    manifest["identities"]["vault"] = "prod-vault-v1"
    manifest["gateway"]["identity"] = "prod-gateway-v1"
    manifest["secret_references"] = ["keychain://agentic-pkm/prod/runtime"]
    return manifest


def _promotion_compose() -> dict[str, object]:
    return {
        "services": {
            "api": {
                "image": f"ghcr.io/example/pkm-app@{DIGEST}",
                "read_only": True,
                "volumes": [
                    {
                        "type": "volume",
                        "source": "prod-vault-v1",
                        "target": "/app/vault",
                    }
                ],
            },
            "database": {
                "image": f"ghcr.io/example/postgres@sha256:{'e' * 64}",
                "volumes": [
                    {
                        "type": "volume",
                        "source": "prod-db-v1",
                        "target": "/var/lib/postgresql/data",
                    }
                ],
            },
        },
        "volumes": {
            "prod-db-v1": {},
            "prod-vault-v1": {},
        },
        "x-startup-identities": {
            "database": "prod-db-v1",
            "vault": "prod-vault-v1",
            "config": "sha256:" + "c" * 64,
            "migration": "alembic:head-example",
        },
    }


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda compose: compose["services"]["api"].update(build="."), "build_forbidden"),
        (
            lambda compose: compose["services"]["api"]["volumes"].append(".:/app"),
            "source_bind_forbidden",
        ),
        (
            lambda compose: compose["services"]["api"]["volumes"].append("/Users:/Users:rw"),
            "broad_writable_mount_forbidden",
        ),
        (
            lambda compose: compose["services"]["api"].update(
                image="ghcr.io/example/pkm-app:latest"
            ),
            "digest_required",
        ),
        (
            lambda compose: compose["services"]["api"].update(
                image="${APP_IMAGE:-ghcr.io/example/pkm-app:latest}"
            ),
            "fallback_forbidden",
        ),
        (
            lambda compose: compose["x-startup-identities"].update(
                database="promotion-test-db-v1"
            ),
            "resource_identity_mismatch",
        ),
        (
            lambda compose: compose["services"]["api"].update(
                environment={"DATABASE_URL": "postgresql://app:secret@prod-db/app"}
            ),
            "secret_value_forbidden",
        ),
        (
            lambda compose: compose["services"]["api"].update(
                command=["run", "opaque-inline-value"]
            ),
            "compose_service_field_forbidden",
        ),
        (
            lambda compose: compose["services"]["api"]["volumes"][0].update(
                source="promotion-test-vault-v1"
            ),
            "resource_identity_mismatch",
        ),
        (
            lambda compose: compose["services"]["api"]["volumes"].append(
                "/var/lib/docker/volumes/prod-vault-v1/_data:/tmp:ro"
            ),
            "promotion_bind_forbidden",
        ),
        (
            lambda compose: compose["volumes"].update(opaque_inline_value={}),
            "promotion_volume_forbidden",
        ),
        (
            lambda compose: compose["services"].update(
                {
                    "opaque-inline-value": {
                        "image": f"ghcr.io/example/sidecar@sha256:{'f' * 64}",
                        "volumes": [],
                    }
                }
            ),
            "compose_service_set_forbidden",
        ),
        (
            lambda compose: compose["services"]["api"]["volumes"][0].update(
                opaque_inline_value="secret"
            ),
            "invalid_mount",
        ),
        (
            lambda compose: compose["services"]["api"]["volumes"].__setitem__(
                0,
                "prod-vault-v1:/app/vault:ro:opaque-inline-value",
            ),
            "invalid_mount",
        ),
        (_move_platform_image_to_database, "platform_digest_missing"),
    ],
)
def test_promotion_render_is_digest_only(mutation, error_code: str) -> None:
    """The production renderer accepts exact digests and rejects mutable inputs."""
    manifest = _promotion_manifest()
    compose = _promotion_compose()

    rendered = render_channel_manifest(
        manifest,
        compose,
        channel="prod",
        mode="promotion",
        intent="promotion",
    )
    assert rendered["promotion_eligible"] is True
    assert rendered["artifact_graph"]["platform_image"] == (
        f"ghcr.io/example/pkm-app@{DIGEST}"
    )
    assert rendered["artifact_graph"]["compose_identity"].startswith("sha256:")
    candidate = create_promotion_candidate(rendered, manifest)
    assert candidate["channel"] == "prod"
    assert candidate["candidate_identity"].startswith("sha256:")

    mutation(compose)
    with pytest.raises(ArtifactRenderError) as exc_info:
        render_channel_manifest(
            manifest,
            compose,
            channel="prod",
            mode="promotion",
            intent="promotion",
        )
    assert exc_info.value.code == error_code


def test_promotion_test_resources_are_bound_to_the_channel_manifest() -> None:
    """A truthful extension cannot mask a prod resource in promotion-test."""
    manifest = _promotion_manifest()
    manifest["channel"] = "promotion-test"
    manifest["compose_project"] = "pkm-promotion-test"
    manifest["identities"]["database"] = "promotion-test-db-v1"
    manifest["identities"]["vault"] = "promotion-test-vault-v1"
    manifest["gateway"]["identity"] = "promotion-test-gateway-v1"
    manifest["secret_references"] = [
        "keychain://agentic-pkm/promotion-test/runtime"
    ]
    compose = _promotion_compose()
    compose["x-startup-identities"] = dict(manifest["identities"])
    compose["services"]["api"]["volumes"][0]["source"] = "promotion-test-vault-v1"
    compose["services"]["database"]["volumes"][0]["source"] = "promotion-test-db-v1"
    compose["volumes"]["promotion-test-vault-v1"] = compose["volumes"].pop(
        "prod-vault-v1"
    )
    compose["volumes"]["promotion-test-db-v1"] = compose["volumes"].pop("prod-db-v1")

    rendered = render_channel_manifest(
        manifest,
        compose,
        channel="promotion-test",
        mode="promotion",
        intent="promotion",
    )
    assert rendered["promotion_eligible"] is True

    compose["services"]["api"]["volumes"][0]["source"] = "prod-vault-v1"
    compose["volumes"]["prod-vault-v1"] = {}
    with pytest.raises(ArtifactRenderError) as exc_info:
        render_channel_manifest(
            manifest,
            compose,
            channel="promotion-test",
            mode="promotion",
            intent="promotion",
        )
    assert exc_info.value.code == "resource_identity_mismatch"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (lambda manifest: manifest.update(compose_project="pkm-wrong"), "compose_project_mismatch"),
        (lambda manifest: manifest.update(llm_policy="anything"), "llm_policy"),
        (lambda manifest: manifest["gateway"].update(port=True), "gateway_port"),
        (lambda manifest: manifest["gateway"].update(extra="value"), "gateway_shape"),
        (
            lambda manifest: manifest["gateway"].update(identity="promotion-test-gateway-v1"),
            "gateway_identity",
        ),
        (
            lambda manifest: manifest.update(
                secret_references=["keychain://agentic-pkm/promotion-test/runtime"]
            ),
            "secret_reference_channel",
        ),
    ],
)
def test_promotion_admission_validates_the_complete_frozen_manifest(
    mutation,
    error_code: str,
) -> None:
    manifest = _promotion_manifest()
    mutation(manifest)

    with pytest.raises(ArtifactRenderError) as exc_info:
        render_channel_manifest(
            manifest,
            _promotion_compose(),
            channel="prod",
            mode="promotion",
            intent="promotion",
        )
    assert exc_info.value.code == error_code


def test_local_source_cannot_create_promotion_candidate(tmp_path: Path) -> None:
    """The real CLI marks local source non-promotable and admission refuses it."""
    manifest = _promotion_manifest()
    manifest["channel"] = "dev"
    manifest["mode"] = "local-source"
    manifest["intent"] = "ordinary-boot"
    manifest["compose_project"] = "pkm-dev"
    manifest["identities"]["database"] = "dev-db-v1"
    manifest["identities"]["vault"] = "dev-vault-v1"
    manifest["gateway"]["identity"] = "dev-gateway-v1"
    manifest["secret_references"] = ["keychain://agentic-pkm/dev/runtime"]
    manifest["artifact"]["dirty_state"] = "dirty"
    manifest["artifact"]["promotion_eligible"] = False
    compose = yaml.safe_load(
        (ROOT / "docker-compose.app-bind.yml").read_text(encoding="utf-8")
    )
    assert compose["services"]["api"]["volumes"] == ["./:/app"]
    assert "x-startup-identities" not in compose
    manifest_path = tmp_path / "manifest.json"
    compose_path = tmp_path / "compose.yml"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    compose_path.write_text(yaml.safe_dump(compose), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.release_channels.channel_manifest",
            "render",
            "--manifest",
            str(manifest_path),
            "--compose",
            str(compose_path),
            "--channel",
            "dev",
            "--mode",
            "local-source",
            "--intent",
            "ordinary-boot",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    rendered = json.loads(proc.stdout)
    assert rendered["promotion_eligible"] is False
    assert rendered["artifact_graph"]["source_identity"].endswith(":dirty")

    with pytest.raises(ArtifactRenderError) as exc_info:
        create_promotion_candidate(rendered, manifest)
    assert exc_info.value.code == "local_source_not_promotable"


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        (
            lambda rendered: rendered["artifact_graph"].update(
                platform_image="ghcr.io/example/pkm-app:latest"
            ),
            "render_binding_mismatch",
        ),
        (
            lambda rendered: rendered["compose"]["services"]["api"].update(build="."),
            "build_forbidden",
        ),
    ],
)
def test_promotion_candidate_revalidates_immutable_render(
    mutation,
    error_code: str,
) -> None:
    """Candidate admission cannot trust a caller-supplied render envelope."""
    rendered = render_channel_manifest(
        _promotion_manifest(),
        _promotion_compose(),
        channel="prod",
        mode="promotion",
        intent="promotion",
    )
    mutation(rendered)

    with pytest.raises(ArtifactRenderError) as exc_info:
        create_promotion_candidate(rendered, _promotion_manifest())
    assert exc_info.value.code == error_code


def test_promotion_candidate_refuses_coherent_forged_render() -> None:
    """Recomputed caller hashes cannot replace independent manifest authority."""
    manifest = _promotion_manifest()
    rendered = render_channel_manifest(
        manifest,
        _promotion_compose(),
        channel="prod",
        mode="promotion",
        intent="promotion",
    )
    forged_image = "evil.example/other@" + "sha256:" + "d" * 64
    rendered["compose"]["services"]["api"]["image"] = forged_image
    canonical_compose = json.dumps(
        rendered["compose"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    rendered["artifact_graph"]["compose_identity"] = (
        "sha256:" + hashlib.sha256(canonical_compose).hexdigest()
    )
    rendered["artifact_graph"]["platform_image"] = forged_image

    with pytest.raises(ArtifactRenderError) as exc_info:
        create_promotion_candidate(rendered, manifest)
    assert exc_info.value.code == "platform_digest_missing"


def test_promotion_render_refuses_malformed_compose_without_partial_output(
    tmp_path: Path,
) -> None:
    """Malformed Compose input returns one typed refusal and no render artifact."""
    manifest_path = tmp_path / "manifest.json"
    compose_path = tmp_path / "compose.yml"
    manifest_path.write_text(json.dumps(_promotion_manifest()), encoding="utf-8")
    compose_path.write_text("services: [", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.release_channels.channel_manifest",
            "render",
            "--manifest",
            str(manifest_path),
            "--compose",
            str(compose_path),
            "--channel",
            "prod",
            "--mode",
            "promotion",
            "--intent",
            "promotion",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert json.loads(proc.stderr)["error"] == "compose_unreadable"


def _ordinary_boot_manifest() -> dict[str, object]:
    manifest = _promotion_manifest()
    manifest["intent"] = "ordinary-boot"
    manifest["llm_policy"] = "declared-optional"
    return manifest


def _compatible_dependencies(manifest: dict[str, object]) -> dict[str, object]:
    artifact = manifest["artifact"]
    identities = manifest["identities"]
    gateway = manifest["gateway"]
    assert isinstance(artifact, dict)
    assert isinstance(identities, dict)
    assert isinstance(gateway, dict)
    return {
        "artifact": {
            "status": "available",
            "identity": f"{artifact['repository']}@{artifact['platform_digest']}",
        },
        "config": {"status": "available", "identity": identities["config"]},
        "database": {"status": "available", "identity": identities["database"]},
        "gateway": {"status": "available", "identity": gateway["identity"]},
        "llm": {"status": "unavailable"},
        "schema": {"status": "available", "identity": identities["migration"]},
        "vault": {"status": "available", "identity": identities["vault"]},
    }


def _journal_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_ordinary_boot_has_no_mutation_calls(tmp_path: Path) -> None:
    """The production doctor calls only resolver checks and its terminal journal."""
    from app.release_channels import ordinary_boot

    source = Path(ordinary_boot.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert imported_roots.isdisjoint({"docker", "subprocess"})
    forbidden_calls = {
        "build",
        "bootstrap_builderops",
        "create_promotion_candidate",
        "ingest",
        "migrate",
        "provision_ollama",
        "pull",
        "restructure_vault",
        "set_pin",
        "start_writer",
    }
    called_names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert called_names.isdisjoint(forbidden_calls)

    journal_path = tmp_path / "ordinary-boot.jsonl"
    result = run_ordinary_boot(
        _ordinary_boot_manifest(),
        _promotion_compose(),
        _compatible_dependencies(_ordinary_boot_manifest()),
        operation_id="boot-001",
        journal_path=journal_path,
    )

    assert result["terminal_phase"] == "ORDINARY_BOOT_PASS"
    assert result["writers_permitted"] is True
    assert result["mutation_evidence"] is False
    assert list(tmp_path.iterdir()) == [journal_path]
    assert _journal_rows(journal_path) == [result]

    replay = run_ordinary_boot(
        _ordinary_boot_manifest(),
        _promotion_compose(),
        _compatible_dependencies(_ordinary_boot_manifest()),
        operation_id="boot-001",
        journal_path=journal_path,
    )
    assert replay == result
    assert _journal_rows(journal_path) == [result]


def test_ordinary_boot_dependency_policy(tmp_path: Path) -> None:
    """Required absence fails closed; degraded absence stays exact and replay-safe."""
    manifest = _ordinary_boot_manifest()
    observations = _compatible_dependencies(manifest)
    journal_path = tmp_path / "ordinary-boot.jsonl"

    degraded = run_ordinary_boot(
        manifest,
        _promotion_compose(),
        observations,
        operation_id="boot-degraded",
        journal_path=journal_path,
    )
    assert degraded["terminal_phase"] == "ORDINARY_BOOT_PASS"
    assert degraded["writers_permitted"] is True
    assert {entry["name"]: entry["classification"] for entry in degraded["dependencies"]}[
        "llm"
    ] == "degraded_unavailable"

    missing_required = _compatible_dependencies(manifest)
    missing_required["schema"] = {"status": "unavailable"}
    refused = run_ordinary_boot(
        manifest,
        _promotion_compose(),
        missing_required,
        operation_id="boot-required-missing",
        journal_path=journal_path,
    )
    classifications = {
        entry["name"]: entry["classification"] for entry in refused["dependencies"]
    }
    assert refused["terminal_phase"] == "PRE_MUTATION_FAILURE"
    assert refused["reason_code"] == "required_dependency_unavailable"
    assert refused["writers_permitted"] is False
    assert refused["mutation_evidence"] is False
    assert classifications["schema"] == "required_unavailable"
    assert len(_journal_rows(journal_path)) == 2

    changed_replay = _compatible_dependencies(manifest)
    changed_replay["vault"] = {"status": "unavailable"}
    with pytest.raises(OrdinaryBootJournalError, match="operation_conflict"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            changed_replay,
            operation_id="boot-degraded",
            journal_path=journal_path,
        )
    assert len(_journal_rows(journal_path)) == 2


@pytest.mark.xfail(strict=True, reason="STARTUP-04 receipt-validator production call site is not implemented")
def test_prod_receipt_validator_is_invoked_before_activation() -> None:
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="STARTUP-04 promotion-test receipt writer call site is not implemented")
def test_promotion_test_writes_one_durable_terminal_receipt() -> None:
    raise NotImplementedError
