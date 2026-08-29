"""Startup-redesign production call-site proofs and deferred skeletons."""

from __future__ import annotations

import base64
import hashlib
import ast
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.release_channels.channel_manifest import (
    ArtifactRenderError,
    create_promotion_candidate,
    render_channel_manifest,
)
from app.release_channels.ordinary_boot import (
    OrdinaryBootJournalError,
    run_ordinary_boot,
)
from app.release_channels.promotion_receipt import (
    PROD_REPOSITORY_URL,
    PromotionReceiptError,
    build_promotion_test_check_report,
    prepare_prod_activation,
    write_promotion_test_terminal_receipt,
)


SKELETON = Path(__file__).read_text()


def test_startup_04_runtime_call_sites_are_not_deferred() -> None:
    """P4 replaces both strict-xfail skeletons with production-path proof."""
    tree = ast.parse(SKELETON)
    strict_xfails = [
        decorator
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "xfail"
        and any(
            keyword.arg == "strict"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
    ]
    not_implemented_raises = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "NotImplementedError"
    ]
    assert strict_xfails == []
    assert not_implemented_raises == []


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_FIXTURE = ROOT / "tests" / "fixtures" / "startup_redesign" / "channel_manifest.valid.json"
PROMOTION_SOURCE_SHA = subprocess.check_output(
    ["git", "rev-parse", "HEAD"],
    cwd=ROOT,
    text=True,
).strip()
PROMOTION_BASELINE_SHA = subprocess.check_output(
    ["git", "rev-parse", "origin/main"],
    cwd=ROOT,
    text=True,
).strip()
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


def _ordinary_boot_operation_id(label: str) -> str:
    return "ob-" + hashlib.sha256(label.encode("utf-8")).hexdigest()[:32]


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
        operation_id=_ordinary_boot_operation_id("boot-001"),
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
        operation_id=_ordinary_boot_operation_id("boot-001"),
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
        operation_id=_ordinary_boot_operation_id("boot-degraded"),
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
        operation_id=_ordinary_boot_operation_id("boot-required-missing"),
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

    incompatible_required = _compatible_dependencies(manifest)
    incompatible_required["vault"] = {
        "status": "available",
        "identity": "prod-vault-wrong",
    }
    incompatible = run_ordinary_boot(
        manifest,
        _promotion_compose(),
        incompatible_required,
        operation_id=_ordinary_boot_operation_id("boot-required-incompatible"),
        journal_path=journal_path,
    )
    incompatible_classes = {
        entry["name"]: entry["classification"]
        for entry in incompatible["dependencies"]
    }
    assert incompatible["terminal_phase"] == "PRE_MUTATION_FAILURE"
    assert incompatible["reason_code"] == "required_dependency_incompatible"
    assert incompatible["writers_permitted"] is False
    assert incompatible_classes["vault"] == "required_incompatible"
    assert "prod-vault-wrong" not in journal_path.read_text(encoding="utf-8")

    changed_replay = _compatible_dependencies(manifest)
    changed_replay["vault"] = {"status": "unavailable"}
    with pytest.raises(OrdinaryBootJournalError, match="operation_conflict"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            changed_replay,
            operation_id=_ordinary_boot_operation_id("boot-degraded"),
            journal_path=journal_path,
        )
    assert len(_journal_rows(journal_path)) == 3

    secret_manifest = _ordinary_boot_manifest()
    secret_manifest["channel"] = "sk-private-channel"
    invalid = run_ordinary_boot(
        secret_manifest,
        _promotion_compose(),
        {},
        operation_id=_ordinary_boot_operation_id("boot-invalid-resolution"),
        journal_path=journal_path,
    )
    assert invalid["channel"] == "unresolved"
    assert invalid["terminal_phase"] == "PRE_MUTATION_FAILURE"
    assert invalid["reason_code"].startswith("compatibility_resolution_failed:")
    assert "sk-private-channel" not in journal_path.read_text(encoding="utf-8")


def test_ordinary_boot_replay_reestablishes_file_and_directory_durability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache-visible row is never replay authority until both fsync fences pass."""
    from app.release_channels import ordinary_boot

    manifest = _ordinary_boot_manifest()
    journal_path = tmp_path / "ordinary-boot.jsonl"
    real_fsync = ordinary_boot.os.fsync
    fsync_calls = 0

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("injected file fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(ordinary_boot.os, "fsync", fail_first_fsync)
    with pytest.raises(OrdinaryBootJournalError, match="journal_io_failure"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            _compatible_dependencies(manifest),
            operation_id=_ordinary_boot_operation_id("boot-fsync-recovery"),
            journal_path=journal_path,
        )
    monkeypatch.setattr(ordinary_boot.os, "fsync", real_fsync)

    parent_fsync_calls = 0
    real_parent_fsync = ordinary_boot._fsync_parent_directory

    def record_parent_fsync(parent_descriptor: int) -> None:
        nonlocal parent_fsync_calls
        parent_fsync_calls += 1
        real_parent_fsync(parent_descriptor)

    monkeypatch.setattr(ordinary_boot, "_fsync_parent_directory", record_parent_fsync)
    replay = run_ordinary_boot(
        manifest,
        _promotion_compose(),
        _compatible_dependencies(manifest),
        operation_id=_ordinary_boot_operation_id("boot-fsync-recovery"),
        journal_path=journal_path,
    )
    assert replay["writers_permitted"] is True
    assert parent_fsync_calls == 1
    assert len(_journal_rows(journal_path)) == 1

    directory_journal = tmp_path / "ordinary-boot-directory-fsync.jsonl"
    directory_fsync_calls = 0

    def fail_first_parent_fsync(parent_descriptor: int) -> None:
        nonlocal directory_fsync_calls
        directory_fsync_calls += 1
        if directory_fsync_calls == 1:
            raise OSError("injected directory fsync failure")
        real_parent_fsync(parent_descriptor)

    monkeypatch.setattr(ordinary_boot, "_fsync_parent_directory", fail_first_parent_fsync)
    with pytest.raises(OrdinaryBootJournalError, match="journal_io_failure"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            _compatible_dependencies(manifest),
            operation_id=_ordinary_boot_operation_id("boot-directory-fsync-recovery"),
            journal_path=directory_journal,
        )
    recovered = run_ordinary_boot(
        manifest,
        _promotion_compose(),
        _compatible_dependencies(manifest),
        operation_id=_ordinary_boot_operation_id("boot-directory-fsync-recovery"),
        journal_path=directory_journal,
    )
    assert recovered["writers_permitted"] is True
    assert directory_fsync_calls == 2
    assert len(_journal_rows(directory_journal)) == 1


def test_ordinary_boot_partial_write_is_never_terminal_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A torn append stays indeterminate and can never replay as PASS."""
    from app.release_channels import ordinary_boot

    manifest = _ordinary_boot_manifest()
    journal_path = tmp_path / "ordinary-boot.jsonl"
    real_write = ordinary_boot.os.write
    write_calls = 0

    def tear_then_fail(descriptor: int, data: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            return real_write(descriptor, data[: len(data) // 2])
        raise OSError("injected torn journal write")

    monkeypatch.setattr(ordinary_boot.os, "write", tear_then_fail)
    with pytest.raises(OrdinaryBootJournalError, match="journal_io_failure"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            _compatible_dependencies(manifest),
            operation_id=_ordinary_boot_operation_id("boot-torn-write"),
            journal_path=journal_path,
        )
    monkeypatch.setattr(ordinary_boot.os, "write", real_write)

    with pytest.raises(OrdinaryBootJournalError, match="journal_corrupt"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            _compatible_dependencies(manifest),
            operation_id=_ordinary_boot_operation_id("boot-torn-write"),
            journal_path=journal_path,
        )


def test_ordinary_boot_rejects_unsafe_journal_targets_without_external_writes(
    tmp_path: Path,
) -> None:
    """Symlink, hardlink, and FIFO targets cannot escape the journal boundary."""
    manifest = _ordinary_boot_manifest()
    observations = _compatible_dependencies(manifest)

    symlink_target = tmp_path / "symlink-target.txt"
    symlink_target.write_text("external-symlink-bytes", encoding="utf-8")
    symlink_journal = tmp_path / "symlink.jsonl"
    symlink_journal.symlink_to(symlink_target)
    with pytest.raises(OrdinaryBootJournalError, match="unsafe_journal_target"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            observations,
            operation_id=_ordinary_boot_operation_id("boot-symlink-refusal"),
            journal_path=symlink_journal,
        )
    assert symlink_target.read_text(encoding="utf-8") == "external-symlink-bytes"

    hardlink_target = tmp_path / "hardlink-target.jsonl"
    hardlink_target.write_text("external-hardlink-bytes", encoding="utf-8")
    hardlink_journal = tmp_path / "hardlink.jsonl"
    os.link(hardlink_target, hardlink_journal)
    with pytest.raises(OrdinaryBootJournalError, match="unsafe_journal_target"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            observations,
            operation_id=_ordinary_boot_operation_id("boot-hardlink-refusal"),
            journal_path=hardlink_journal,
        )
    assert hardlink_target.read_text(encoding="utf-8") == "external-hardlink-bytes"

    fifo_journal = tmp_path / "fifo.jsonl"
    os.mkfifo(fifo_journal)
    with pytest.raises(OrdinaryBootJournalError, match="unsafe_journal_target"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            observations,
            operation_id=_ordinary_boot_operation_id("boot-fifo-refusal"),
            journal_path=fifo_journal,
        )

    shared_parent = tmp_path / "shared-parent"
    shared_parent.mkdir()
    shared_parent.chmod(0o777)
    shared_journal = shared_parent / "ordinary-boot.jsonl"
    try:
        with pytest.raises(
            OrdinaryBootJournalError,
            match="unsafe_journal_parent_permissions",
        ):
            run_ordinary_boot(
                manifest,
                _promotion_compose(),
                observations,
                operation_id=_ordinary_boot_operation_id("boot-shared-parent-refusal"),
                journal_path=shared_journal,
            )
        assert not shared_journal.exists()
    finally:
        shared_parent.chmod(0o700)


def test_ordinary_boot_detects_named_path_replacement_before_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A swapped name never turns the opened inode into terminal authority."""
    from app.release_channels import ordinary_boot

    manifest = _ordinary_boot_manifest()
    journal_path = tmp_path / "replace.jsonl"
    moved_journal = tmp_path / "opened-inode.jsonl"
    external_bytes = b"external-replacement-bytes"
    real_revalidate = ordinary_boot._revalidate_journal_target
    revalidation_calls = 0

    def replace_before_terminal_revalidation(
        path: Path,
        *,
        parent_descriptor: int,
        journal_descriptor: int,
    ) -> None:
        nonlocal revalidation_calls
        revalidation_calls += 1
        if revalidation_calls == 2:
            path.rename(moved_journal)
            path.write_bytes(external_bytes)
        real_revalidate(
            path,
            parent_descriptor=parent_descriptor,
            journal_descriptor=journal_descriptor,
        )

    monkeypatch.setattr(
        ordinary_boot,
        "_revalidate_journal_target",
        replace_before_terminal_revalidation,
    )
    with pytest.raises(OrdinaryBootJournalError, match="unsafe_journal_target"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            _compatible_dependencies(manifest),
            operation_id=_ordinary_boot_operation_id("boot-path-replacement"),
            journal_path=journal_path,
        )
    assert journal_path.read_bytes() == external_bytes
    assert moved_journal.read_bytes().endswith(b"\n")


def test_ordinary_boot_rejects_secret_pattern_operation_ids_without_echo(
    tmp_path: Path,
) -> None:
    manifest = _ordinary_boot_manifest()
    manifest_path = tmp_path / "manifest.json"
    compose_path = tmp_path / "compose.json"
    dependencies_path = tmp_path / "dependencies.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    compose_path.write_text(json.dumps(_promotion_compose()), encoding="utf-8")
    dependencies_path.write_text(
        json.dumps(_compatible_dependencies(manifest)),
        encoding="utf-8",
    )
    secret_operation_ids = (
        "".join(("s", "k-", "private-token")),
        "".join(("g", "hp_", "0123456789abcdefghijklmnopqrstuvwxyz")),
        "".join(("github_", "pat_", "0123456789abcdefghijklmnopqrstuvwxyz")),
        "".join(("AK", "IA", "0123456789ABCDEF")),
        "".join(("eyJ", "hbGciOiJIUzI1NiJ9", ".payload.signature")),
    )
    for index, secret_operation_id in enumerate(secret_operation_ids):
        journal_path = tmp_path / f"secret-id-{index}.jsonl"
        with pytest.raises(OrdinaryBootJournalError, match="invalid_operation_id") as exc_info:
            run_ordinary_boot(
                manifest,
                _promotion_compose(),
                _compatible_dependencies(manifest),
                operation_id=secret_operation_id,
                journal_path=journal_path,
            )
        assert secret_operation_id not in str(exc_info.value)
        assert not journal_path.exists()

        proc = subprocess.run(
            _ordinary_boot_cli_command(
                manifest_path,
                compose_path,
                dependencies_path,
                journal_path,
                secret_operation_id,
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2
        assert secret_operation_id not in proc.stdout
        assert secret_operation_id not in proc.stderr
        assert not journal_path.exists()

    valid_operation_id = _ordinary_boot_operation_id("redacted-conflict")
    conflict_journal = tmp_path / "conflict-redaction.jsonl"
    run_ordinary_boot(
        manifest,
        _promotion_compose(),
        _compatible_dependencies(manifest),
        operation_id=valid_operation_id,
        journal_path=conflict_journal,
    )
    incompatible = _compatible_dependencies(manifest)
    incompatible["schema"] = {"status": "unavailable"}
    with pytest.raises(OrdinaryBootJournalError, match="operation_conflict") as exc_info:
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            incompatible,
            operation_id=valid_operation_id,
            journal_path=conflict_journal,
        )
    assert valid_operation_id not in str(exc_info.value)


@pytest.mark.parametrize(
    ("input_name", "damage", "reason_code"),
    [
        ("manifest", "missing", "compatibility_resolution_failed:manifest_unreadable"),
        ("manifest", "malformed", "compatibility_resolution_failed:manifest_unreadable"),
        ("manifest", "invalid_utf8", "compatibility_resolution_failed:manifest_unreadable"),
        ("manifest", "non_finite", "compatibility_resolution_failed:manifest_invalid_shape"),
        ("manifest", "huge_integer", "compatibility_resolution_failed:manifest_invalid_shape"),
        ("manifest", "parser_huge_integer", "compatibility_resolution_failed:manifest_unreadable"),
        ("manifest", "duplicate_key", "compatibility_resolution_failed:manifest_unreadable"),
        ("compose", "missing", "compatibility_resolution_failed:compose_unreadable"),
        ("compose", "malformed", "compatibility_resolution_failed:compose_unreadable"),
        ("compose", "invalid_utf8", "compatibility_resolution_failed:compose_unreadable"),
        ("compose", "recursive_alias", "compatibility_resolution_failed:compose_invalid_shape"),
        ("compose", "timestamp", "compatibility_resolution_failed:compose_invalid_shape"),
        ("compose", "non_string_key", "compatibility_resolution_failed:compose_invalid_shape"),
        ("compose", "non_finite", "compatibility_resolution_failed:compose_invalid_shape"),
        ("compose", "huge_integer", "compatibility_resolution_failed:compose_invalid_shape"),
        ("compose", "parser_huge_integer", "compatibility_resolution_failed:compose_unreadable"),
        ("compose", "duplicate_key", "compatibility_resolution_failed:compose_unreadable"),
        (
            "dependencies",
            "missing",
            "compatibility_resolution_failed:dependencies_unreadable",
        ),
        (
            "dependencies",
            "malformed",
            "compatibility_resolution_failed:dependencies_unreadable",
        ),
        (
            "dependencies",
            "invalid_utf8",
            "compatibility_resolution_failed:dependencies_unreadable",
        ),
        (
            "dependencies",
            "non_finite",
            "compatibility_resolution_failed:dependencies_invalid_shape",
        ),
        (
            "dependencies",
            "huge_integer",
            "compatibility_resolution_failed:dependencies_invalid_shape",
        ),
        (
            "dependencies",
            "parser_huge_integer",
            "compatibility_resolution_failed:dependencies_unreadable",
        ),
        (
            "dependencies",
            "duplicate_key",
            "compatibility_resolution_failed:dependencies_unreadable",
        ),
    ],
)
def test_ordinary_boot_cli_input_failure_writes_one_terminal_result(
    tmp_path: Path,
    input_name: str,
    damage: str,
    reason_code: str,
) -> None:
    manifest = _ordinary_boot_manifest()
    manifest_path = tmp_path / "manifest.json"
    compose_path = tmp_path / "compose.yaml"
    dependencies_path = tmp_path / "dependencies.json"
    paths = {
        "manifest": manifest_path,
        "compose": compose_path,
        "dependencies": dependencies_path,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    compose_path.write_text(yaml.safe_dump(_promotion_compose()), encoding="utf-8")
    dependencies_path.write_text(
        json.dumps(_compatible_dependencies(manifest)),
        encoding="utf-8",
    )
    damaged_path = paths[input_name]
    if damage == "missing":
        damaged_path.unlink()
    elif damage == "malformed":
        damaged_path.write_text(":\n - [", encoding="utf-8")
    elif damage == "invalid_utf8":
        damaged_path.write_bytes(b"\xff")
    elif damage == "recursive_alias":
        damaged_path.write_text(
            "recursive: &recursive\n  self: *recursive\n",
            encoding="utf-8",
        )
    elif damage == "timestamp":
        damaged_path.write_text("created: 2026-08-29\n", encoding="utf-8")
    elif damage == "non_string_key":
        damaged_path.write_text("services:\n  1: value\n", encoding="utf-8")
    elif damage in {"huge_integer", "parser_huge_integer"}:
        digits = "9" * (1500 if damage == "huge_integer" else 5000)
        if input_name == "compose":
            damaged_path.write_text(f"value: {digits}\n", encoding="utf-8")
        else:
            damaged_path.write_text(f'{{"value": {digits}}}', encoding="utf-8")
    elif damage == "duplicate_key":
        if input_name == "compose":
            damaged_path.write_text(
                "services:\n  app: {}\n  app: {}\n",
                encoding="utf-8",
            )
        else:
            damaged_path.write_text(
                '{"value": "first", "value": "second"}',
                encoding="utf-8",
            )
    elif input_name == "compose":
        damaged_path.write_text("value: .nan\n", encoding="utf-8")
    else:
        damaged_path.write_text('{"value": NaN}', encoding="utf-8")

    operation_id = _ordinary_boot_operation_id(f"{input_name}-{damage}")
    journal_path = tmp_path / "ordinary-boot.jsonl"
    command = _ordinary_boot_cli_command(
        manifest_path,
        compose_path,
        dependencies_path,
        journal_path,
        operation_id,
    )
    first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert first.returncode == 3, first.stderr
    assert first.stderr == ""
    result = json.loads(first.stdout)
    assert result["terminal_phase"] == "PRE_MUTATION_FAILURE"
    assert result["reason_code"] == reason_code
    assert result["writers_permitted"] is False
    assert _journal_rows(journal_path) == [result]

    replay = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert replay.returncode == 3, replay.stderr
    assert json.loads(replay.stdout) == result
    assert _journal_rows(journal_path) == [result]


def test_ordinary_boot_cli_accepts_canonical_yaml_compose(tmp_path: Path) -> None:
    manifest = _ordinary_boot_manifest()
    manifest_path = tmp_path / "manifest.json"
    compose_path = tmp_path / "compose.yaml"
    dependencies_path = tmp_path / "dependencies.json"
    journal_path = tmp_path / "ordinary-boot.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    compose_path.write_text(yaml.safe_dump(_promotion_compose()), encoding="utf-8")
    dependencies_path.write_text(
        json.dumps(_compatible_dependencies(manifest)),
        encoding="utf-8",
    )
    proc = subprocess.run(
        _ordinary_boot_cli_command(
            manifest_path,
            compose_path,
            dependencies_path,
            journal_path,
            _ordinary_boot_operation_id("yaml-compose"),
        ),
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["terminal_phase"] == "ORDINARY_BOOT_PASS"
    assert _journal_rows(journal_path) == [result]


def test_ordinary_boot_in_memory_recursive_input_is_terminal(tmp_path: Path) -> None:
    manifest = _ordinary_boot_manifest()
    recursive_compose: dict[str, object] = {}
    recursive_compose["self"] = recursive_compose
    journal_path = tmp_path / "recursive-input.jsonl"
    result = run_ordinary_boot(
        manifest,
        recursive_compose,
        _compatible_dependencies(manifest),
        operation_id=_ordinary_boot_operation_id("recursive-in-memory"),
        journal_path=journal_path,
    )
    assert result["terminal_phase"] == "PRE_MUTATION_FAILURE"
    assert result["reason_code"] == "compatibility_resolution_failed:compose_invalid_shape"
    assert result["writers_permitted"] is False
    assert _journal_rows(journal_path) == [result]


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda row: {key: value for key, value in row.items() if key != "reason_code"},
        lambda row: {**row, "writers_permitted": False},
        lambda row: {**row, "terminal_phase": "PASS"},
        lambda row: {**row, "channel": "unresolved"},
        lambda row: {**row, "dependencies": row["dependencies"][1:]},
        lambda row: {
            **row,
            "dependencies": [
                {
                    **entry,
                    "policy": "degraded_ok",
                    "classification": "degraded_compatible",
                }
                if entry["name"] == "artifact"
                else entry
                for entry in row["dependencies"]
            ],
        },
    ],
)
def test_ordinary_boot_semantic_journal_corruption_blocks_new_authority(
    tmp_path: Path,
    corrupt,
) -> None:
    manifest = _ordinary_boot_manifest()
    journal_path = tmp_path / "ordinary-boot.jsonl"
    result = run_ordinary_boot(
        manifest,
        _promotion_compose(),
        _compatible_dependencies(manifest),
        operation_id=_ordinary_boot_operation_id("boot-valid-before-corruption"),
        journal_path=journal_path,
    )
    journal_path.write_text(
        json.dumps(corrupt(result), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(OrdinaryBootJournalError, match="journal_corrupt"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            _compatible_dependencies(manifest),
            operation_id=_ordinary_boot_operation_id("boot-after-corruption"),
            journal_path=journal_path,
        )


@pytest.mark.parametrize("damage", ["truncated", "duplicate"])
def test_ordinary_boot_structural_journal_corruption_blocks_new_authority(
    tmp_path: Path,
    damage: str,
) -> None:
    manifest = _ordinary_boot_manifest()
    journal_path = tmp_path / "ordinary-boot.jsonl"
    run_ordinary_boot(
        manifest,
        _promotion_compose(),
        _compatible_dependencies(manifest),
        operation_id=_ordinary_boot_operation_id("boot-valid-structural"),
        journal_path=journal_path,
    )
    raw = journal_path.read_text(encoding="utf-8")
    journal_path.write_text(
        raw.rstrip("\n") if damage == "truncated" else raw + raw,
        encoding="utf-8",
    )

    with pytest.raises(OrdinaryBootJournalError, match="journal_corrupt"):
        run_ordinary_boot(
            manifest,
            _promotion_compose(),
            _compatible_dependencies(manifest),
            operation_id=_ordinary_boot_operation_id("boot-after-structural-corruption"),
            journal_path=journal_path,
        )


def _ordinary_boot_cli_command(
    manifest_path: Path,
    compose_path: Path,
    dependencies_path: Path,
    journal_path: Path,
    operation_id: str,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "app.release_channels.ordinary_boot",
        "doctor",
        "--manifest",
        str(manifest_path),
        "--compose",
        str(compose_path),
        "--dependencies",
        str(dependencies_path),
        "--operation-id",
        operation_id,
        "--journal",
        str(journal_path),
    ]


def test_ordinary_boot_concurrent_callers_converge_or_conflict_once(tmp_path: Path) -> None:
    """Process races produce one terminal row for an operation id, never two."""
    manifest = _ordinary_boot_manifest()
    compatible = _compatible_dependencies(manifest)
    incompatible = _compatible_dependencies(manifest)
    incompatible["schema"] = {"status": "unavailable"}
    manifest_path = tmp_path / "manifest.json"
    compose_path = tmp_path / "compose.json"
    compatible_path = tmp_path / "compatible.json"
    incompatible_path = tmp_path / "incompatible.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    compose_path.write_text(json.dumps(_promotion_compose()), encoding="utf-8")
    compatible_path.write_text(json.dumps(compatible), encoding="utf-8")
    incompatible_path.write_text(json.dumps(incompatible), encoding="utf-8")

    identical_journal = tmp_path / "identical.jsonl"
    identical_commands = _ordinary_boot_cli_command(
        manifest_path,
        compose_path,
        compatible_path,
        identical_journal,
        _ordinary_boot_operation_id("boot-concurrent-identical"),
    )
    identical_processes = [
        subprocess.Popen(
            identical_commands,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    identical_results = [process.communicate(timeout=10) for process in identical_processes]
    assert [process.returncode for process in identical_processes] == [0, 0], identical_results
    assert len(_journal_rows(identical_journal)) == 1

    conflicting_journal = tmp_path / "conflicting.jsonl"
    conflicting_processes = [
        subprocess.Popen(
            _ordinary_boot_cli_command(
                manifest_path,
                compose_path,
                dependency_path,
                conflicting_journal,
                _ordinary_boot_operation_id("boot-concurrent-conflicting"),
            ),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for dependency_path in (compatible_path, incompatible_path)
    ]
    conflicting_results = [process.communicate(timeout=10) for process in conflicting_processes]
    return_codes = {process.returncode for process in conflicting_processes}
    assert 2 in return_codes and return_codes & {0, 3}, conflicting_results
    assert (
        sum("operation_conflict" in stderr for _, stderr in conflicting_results) == 1
    ), conflicting_results
    assert len(_journal_rows(conflicting_journal)) == 1


def test_prod_receipt_validator_is_invoked_before_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = json.loads(
        (ROOT / "tests/fixtures/startup_redesign/promotion_receipt.valid.json").read_text()
    )
    registry = json.loads(
        (
            ROOT
            / "tests/fixtures/startup_redesign/promotion_receipt_registry.valid.json"
        ).read_text()
    )
    context = json.loads(
        (
            ROOT
            / "tests/fixtures/startup_redesign/promotion_admission_context.valid.json"
        ).read_text()
    )
    check_report = json.loads(
        (
            ROOT
            / "tests/fixtures/startup_redesign/promotion_check_report.valid.json"
        ).read_text()
    )
    now = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)

    from app.release_channels import promotion_receipt

    calls: list[str] = []
    real_validator = promotion_receipt.authorize_prod_activation

    def observed_validator(*args, **kwargs):
        calls.append("validate")
        return real_validator(*args, **kwargs)

    monkeypatch.setattr(
        promotion_receipt,
        "authorize_prod_activation",
        observed_validator,
    )
    authorization = prepare_prod_activation(
        receipt,
        registry,
        context,
        check_report=check_report,
        source_repo=ROOT,
        now=now,
    )
    assert calls == ["validate"]
    assert authorization == {
        "activation_permitted": True,
        "activation_state": "validated_not_activated",
        "receipt_id": receipt["receipt_id"],
    }

    rejected: list[tuple[object, object, object, object, datetime, str]] = [
        (None, registry, context, check_report, now, "receipt_missing"),
        (
            receipt,
            registry,
            context,
            check_report,
            datetime(2026, 8, 17, tzinfo=timezone.utc),
            "receipt_stale",
        ),
    ]
    revoked = json.loads(json.dumps(registry))
    revoked["entries"][receipt["receipt_id"]]["status"] = "revoked"
    rejected.append((receipt, revoked, context, check_report, now, "receipt_revoked"))
    mismatched = dict(context, config_identity="sha256:" + "c" * 64)
    rejected.append(
        (receipt, registry, mismatched, check_report, now, "identity_mismatch")
    )
    mismatched_baseline = dict(
        context,
        migration_baseline_identity="git:" + "f" * 40,
    )
    rejected.append(
        (
            receipt,
            registry,
            mismatched_baseline,
            check_report,
            now,
            "migration_baseline_mismatch",
        )
    )
    mismatched_report = json.loads(json.dumps(check_report))
    mismatched_report["migration_set_identity"] = "sha256:" + "e" * 64
    rejected.append(
        (
            receipt,
            registry,
            context,
            mismatched_report,
            now,
            "migration_set_mismatch",
        )
    )
    rejected.append(
        (receipt, registry, context, None, now, "check_report_invalid")
    )

    for (
        candidate,
        candidate_registry,
        candidate_context,
        candidate_report,
        candidate_now,
        code,
    ) in rejected:
        with pytest.raises(PromotionReceiptError) as exc_info:
            prepare_prod_activation(
                candidate,
                candidate_registry,
                candidate_context,
                check_report=candidate_report,
                source_repo=ROOT,
                now=candidate_now,
            )
        assert exc_info.value.code == code


def test_validate_prod_activation_cli_resolves_repo_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.release_channels.promotion_receipt import main

    rc = main(
        [
            "validate-prod-activation",
            "--receipt",
            str(ROOT / "tests/fixtures/startup_redesign/promotion_receipt.valid.json"),
            "--registry",
            str(
                ROOT
                / "tests/fixtures/startup_redesign/promotion_receipt_registry.valid.json"
            ),
            "--admission-context",
            str(
                ROOT
                / "tests/fixtures/startup_redesign/promotion_admission_context.valid.json"
            ),
            "--check-report",
            str(ROOT / "tests/fixtures/startup_redesign/promotion_check_report.valid.json"),
            "--now",
            "2026-08-16T12:00:00Z",
        ]
    )

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["activation_state"] == "validated_not_activated"


def _promotion_test_signing_material() -> tuple[Ed25519PrivateKey, bytes]:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, public_key


def _promotion_check_results() -> dict[str, bool]:
    return {
        "readiness": True,
        "schema": True,
        "smoke": True,
        "ui": True,
        "version": True,
    }


def _promotion_admission_context(
    *,
    migration_baseline_sha: str = PROMOTION_BASELINE_SHA,
) -> dict[str, str]:
    context = json.loads(
        (
            ROOT
            / "tests/fixtures/startup_redesign/promotion_admission_context.valid.json"
        ).read_text()
    )
    context["migration_baseline_identity"] = f"git:{migration_baseline_sha}"
    return context


def _promotion_test_candidate_inputs(
    *,
    source_sha: str = PROMOTION_SOURCE_SHA,
) -> tuple[dict[str, object], dict[str, object]]:
    manifest = json.loads(MANIFEST_FIXTURE.read_text(encoding="utf-8"))
    context = _promotion_admission_context()
    manifest["artifact"]["source_sha"] = source_sha
    manifest["identities"]["config"] = context["config_identity"]
    manifest["identities"]["migration"] = context["schema_identity"]
    compose = _promotion_compose()
    compose["x-startup-identities"] = dict(manifest["identities"])
    compose["services"]["api"]["volumes"][0]["source"] = manifest["identities"][
        "vault"
    ]
    compose["services"]["database"]["volumes"][0]["source"] = manifest[
        "identities"
    ]["database"]
    compose["volumes"][manifest["identities"]["vault"]] = compose["volumes"].pop(
        "prod-vault-v1"
    )
    compose["volumes"][manifest["identities"]["database"]] = compose["volumes"].pop(
        "prod-db-v1"
    )
    rendered = render_channel_manifest(
        manifest,
        compose,
        channel="promotion-test",
        mode="promotion",
        intent="promotion",
    )
    return rendered, manifest


def _promotion_check_report(
    *,
    check_results: dict[str, bool] | None = None,
    source_repo: Path = ROOT,
    migration_baseline_sha: str = PROMOTION_BASELINE_SHA,
    source_sha: str = PROMOTION_SOURCE_SHA,
) -> dict[str, object]:
    rendered, manifest = _promotion_test_candidate_inputs(source_sha=source_sha)
    return build_promotion_test_check_report(
        rendered=rendered,
        channel_manifest=manifest,
        prod_admission_context=_promotion_admission_context(
            migration_baseline_sha=migration_baseline_sha
        ),
        check_results=check_results or _promotion_check_results(),
        source_repo=source_repo,
    )


def _seed_promotion_registry(store: Path, public_key: bytes) -> None:
    store.mkdir(parents=True, exist_ok=True)
    registry = {
        "registry_version": "promotion-receipt-registry.v1",
        "trusted_keys": {
            "promotion-test-issuer-key-v1": base64.urlsafe_b64encode(public_key)
            .decode("ascii")
            .rstrip("=")
        },
        "entries": {},
    }
    registry_path = store / "registry.json"
    registry_path.write_text(
        json.dumps(registry, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    registry_path.chmod(0o600)


def _promotion_migration_git_delta(
    tmp_path: Path,
    *,
    content: str,
) -> tuple[Path, str, str]:
    repo = tmp_path / "source-repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", PROD_REPOSITORY_URL],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "fetch",
            "-q",
            "--no-tags",
            "origin",
            "refs/heads/main:refs/remotes/origin/main",
        ],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "checkout", "-q", "--detach", "origin/main"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Receipt Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "receipt-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    baseline = subprocess.check_output(
        ["git", "rev-parse", "origin/main"],
        cwd=repo,
        text=True,
    ).strip()
    migrations = repo / "app" / "alembic" / "versions"
    migrations.mkdir(parents=True, exist_ok=True)
    (migrations / "receipt_delta.py").write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "app/alembic/versions/receipt_delta.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "add migration"], cwd=repo, check=True)
    target = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return repo, baseline, target


def test_promotion_test_refuses_self_enrolled_registry_trust(tmp_path: Path) -> None:
    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"

    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            attempt_id="pt-" + "a" * 32,
            rendered=rendered,
            channel_manifest=manifest,
            prod_admission_context=_promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            issued_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            fresh_until=datetime(2026, 8, 17, tzinfo=timezone.utc),
            issuer_id="promotion-test-issuer",
            issuer_key_id="promotion-test-issuer-key-v1",
            signer=private_key.sign,
            issuer_public_key=public_key,
            receipt_store=store,
            resettable_roots=(tmp_path / "tmp-test", tmp_path / "vault-test"),
        )
    assert exc_info.value.code == "registry_missing"
    assert list((store / "reservations").glob("*.json")) == []
    assert list((store / "receipts").glob("*.json")) == []
    assert list((store / "attempts").glob("*.json")) == []


def test_promotion_test_rejects_untrusted_signer_before_terminal_publication(
    tmp_path: Path,
) -> None:
    _, trusted_public_key = _promotion_test_signing_material()
    untrusted_private_key = Ed25519PrivateKey.generate()
    untrusted_public_key = untrusted_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, trusted_public_key)

    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            attempt_id="pt-" + "b" * 32,
            rendered=rendered,
            channel_manifest=manifest,
            prod_admission_context=_promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            issued_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            fresh_until=datetime(2026, 8, 17, tzinfo=timezone.utc),
            issuer_id="promotion-test-issuer",
            issuer_key_id="promotion-test-issuer-key-v1",
            signer=untrusted_private_key.sign,
            issuer_public_key=untrusted_public_key,
            receipt_store=store,
            resettable_roots=(tmp_path / "tmp-test", tmp_path / "vault-test"),
        )
    assert exc_info.value.code == "registry_key_conflict"
    registry = json.loads((store / "registry.json").read_text(encoding="utf-8"))
    assert registry["entries"] == {}
    assert list((store / "reservations").glob("*.json")) == []
    assert list((store / "receipts").glob("*.json")) == []
    assert list((store / "attempts").glob("*.json")) == []


def test_promotion_test_derives_complete_migration_delta_from_candidate_git(
    tmp_path: Path,
) -> None:
    repo, baseline, target = _promotion_migration_git_delta(
        tmp_path,
        content='reversibility = "reversible"\n',
    )
    rendered, manifest = _promotion_test_candidate_inputs(source_sha=target)

    report = build_promotion_test_check_report(
        rendered=rendered,
        channel_manifest=manifest,
        prod_admission_context=_promotion_admission_context(
            migration_baseline_sha=baseline
        ),
        check_results=_promotion_check_results(),
        source_repo=repo,
    )
    assert report["migration_set_identity"] != _promotion_check_report()[
        "migration_set_identity"
    ]
    assert report["migration_baseline_identity"] == f"git:{baseline}"


def test_promotion_test_rejects_candidate_as_prod_migration_baseline(
    tmp_path: Path,
) -> None:
    repo, _, target = _promotion_migration_git_delta(
        tmp_path,
        content='reversibility = "reversible"\n',
    )
    rendered, manifest = _promotion_test_candidate_inputs(source_sha=target)

    with pytest.raises(PromotionReceiptError) as exc_info:
        build_promotion_test_check_report(
            rendered=rendered,
            channel_manifest=manifest,
            prod_admission_context=_promotion_admission_context(
                migration_baseline_sha=target
            ),
            check_results=_promotion_check_results(),
            source_repo=repo,
        )
    assert exc_info.value.code == "migration_baseline_mismatch"


def test_promotion_test_writes_one_durable_terminal_receipt(tmp_path: Path) -> None:
    private_key, public_key = _promotion_test_signing_material()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    resettable_roots = (tmp_path / "tmp-test", tmp_path / "vault-test")
    rendered, manifest = _promotion_test_candidate_inputs()
    common = {
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": resettable_roots,
        "source_repo": ROOT,
    }

    pass_report = _promotion_check_report()
    passed = write_promotion_test_terminal_receipt(
        attempt_id="pt-" + "1" * 32,
        check_report=pass_report,
        **common,
    )
    assert passed["outcome"] == "PASS"
    assert passed["migration_baseline_identity"] == pass_report[
        "migration_baseline_identity"
    ]
    assert passed["migration_set_identity"] == pass_report["migration_set_identity"]
    assert passed["check_report_identity"] == "sha256:" + hashlib.sha256(
        json.dumps(
            pass_report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert write_promotion_test_terminal_receipt(
        attempt_id="pt-" + "1" * 32,
        check_report=pass_report,
        **common,
    ) == passed
    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert len(list((store / "attempts").glob("*.json"))) == 1
    registry = json.loads((store / "registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][passed["receipt_id"]]["status"] == "issued"
    assert prepare_prod_activation(
        passed,
        registry,
        _promotion_admission_context(),
        check_report=pass_report,
        source_repo=ROOT,
        now=datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
    ) == {
        "activation_permitted": True,
        "activation_state": "validated_not_activated",
        "receipt_id": passed["receipt_id"],
    }
    pass_attempt = json.loads(
        (store / "attempts" / f"pt-{'1' * 32}.json").read_text(encoding="utf-8")
    )
    assert pass_attempt["receipt_id"] == passed["receipt_id"]
    assert pass_attempt["outcome"] == "PASS"
    assert pass_attempt["check_results"] == {
        "migration": True,
        **_promotion_check_results(),
    }
    assert pass_attempt["migration_classification"] == {
        "migrations_checked": 0,
        "reversible": [],
        "forward_only": [],
        "classification_decisions": [],
    }

    migration_repo, migration_baseline, migration_target = _promotion_migration_git_delta(
        tmp_path / "unclassified",
        content="revision = 'unclassified'\n",
    )
    failed_rendered, failed_manifest = _promotion_test_candidate_inputs(
        source_sha=migration_target
    )
    failed = write_promotion_test_terminal_receipt(
        attempt_id="pt-" + "2" * 32,
        check_report=_promotion_check_report(
            source_repo=migration_repo,
            migration_baseline_sha=migration_baseline,
            source_sha=migration_target,
        ),
        **dict(
            common,
            rendered=failed_rendered,
            channel_manifest=failed_manifest,
            source_repo=migration_repo,
            prod_admission_context=_promotion_admission_context(
                migration_baseline_sha=migration_baseline
            ),
        ),
    )
    assert failed["outcome"] == "FAIL"
    assert len(list((store / "receipts").glob("*.json"))) == 2
    assert len(list((store / "attempts").glob("*.json"))) == 2
    registry = json.loads((store / "registry.json").read_text(encoding="utf-8"))
    assert set(registry["entries"]) == {passed["receipt_id"], failed["receipt_id"]}
    fail_attempt = json.loads(
        (store / "attempts" / f"pt-{'2' * 32}.json").read_text(encoding="utf-8")
    )
    assert fail_attempt["receipt_id"] == failed["receipt_id"]
    assert fail_attempt["outcome"] == "FAIL"
    assert fail_attempt["check_results"]["migration"] is False
    assert fail_attempt["migration_classification"] == {"status": "invalid"}

    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            attempt_id="pt-" + "3" * 32,
            check_report=_promotion_check_report(),
            **dict(common, receipt_store=tmp_path / "tmp-test" / "receipts"),
        )
    assert exc_info.value.code == "resettable_receipt_store"


def test_promotion_test_terminal_receipt_race_has_one_winner(tmp_path: Path) -> None:
    private_key, public_key = _promotion_test_signing_material()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    rendered, manifest = _promotion_test_candidate_inputs()
    common = {
        "attempt_id": "pt-" + "4" * 32,
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
        "source_repo": ROOT,
    }

    def write(smoke_ok: bool) -> tuple[str, str]:
        checks = _promotion_check_results()
        checks["smoke"] = smoke_ok
        try:
            receipt = write_promotion_test_terminal_receipt(
                check_report=_promotion_check_report(check_results=checks),
                **common,
            )
        except PromotionReceiptError as exc:
            return "error", exc.code
        return "ok", str(receipt["outcome"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, (True, False)))

    assert sorted(result[0] for result in results) == ["error", "ok"]
    assert ("error", "attempt_conflict") in results
    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert len(list((store / "attempts").glob("*.json"))) == 1


def test_promotion_test_receipt_recovery_and_secret_boundary(tmp_path: Path) -> None:
    private_key, public_key = _promotion_test_signing_material()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    rendered, manifest = _promotion_test_candidate_inputs()
    common = {
        "attempt_id": "pt-" + "5" * 32,
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "check_report": _promotion_check_report(),
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
        "source_repo": ROOT,
    }
    receipt = write_promotion_test_terminal_receipt(**common)
    pointer = next((store / "attempts").glob("*.json"))
    pointer.unlink()

    assert write_promotion_test_terminal_receipt(**common) == receipt
    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert len(list((store / "attempts").glob("*.json"))) == 1

    secret_bearing = dict(
        _promotion_admission_context(),
        vault_identity="postgresql://admin:hunter2@prod/app",
    )
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            **dict(
                common,
                attempt_id="pt-" + "6" * 32,
                prod_admission_context=secret_bearing,
            )
        )
    assert exc_info.value.code == "identity_invalid"


def test_promotion_test_reservation_blocks_changed_orphan_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.release_channels import promotion_receipt

    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    common = {
        "attempt_id": "pt-" + "7" * 32,
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "source_repo": ROOT,
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
    }
    real_install = promotion_receipt._install_content_addressed

    def crash_after_receipt(path: Path, data: bytes) -> None:
        real_install(path, data)
        raise PromotionReceiptError("injected_post_receipt_crash")

    monkeypatch.setattr(
        promotion_receipt,
        "_install_content_addressed",
        crash_after_receipt,
    )
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            check_report=_promotion_check_report(),
            **common,
        )
    assert exc_info.value.code == "injected_post_receipt_crash"
    assert len(list((store / "reservations").glob("*.json"))) == 1
    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert list((store / "attempts").glob("*.json")) == []

    monkeypatch.setattr(
        promotion_receipt,
        "_install_content_addressed",
        real_install,
    )
    changed_checks = _promotion_check_results()
    changed_checks["smoke"] = False
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            check_report=_promotion_check_report(check_results=changed_checks),
            **common,
        )
    assert exc_info.value.code == "attempt_conflict"
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            check_report=_promotion_check_report(),
            **dict(
                common,
                issued_at=datetime(2026, 8, 16, 0, 0, 1, tzinfo=timezone.utc),
            ),
        )
    assert exc_info.value.code == "attempt_conflict"
    recovered = write_promotion_test_terminal_receipt(
        check_report=_promotion_check_report(),
        **common,
    )
    assert recovered["outcome"] == "PASS"
    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert len(list((store / "attempts").glob("*.json"))) == 1


def test_promotion_test_rejects_stale_candidate_and_migration_reports(
    tmp_path: Path,
) -> None:
    private_key, public_key = _promotion_test_signing_material()
    rendered_a, manifest_a = _promotion_test_candidate_inputs()
    previous_source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD^"],
        cwd=ROOT,
        text=True,
    ).strip()
    rendered_b, manifest_b = _promotion_test_candidate_inputs(
        source_sha=previous_source_sha
    )
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    common = {
        "attempt_id": "pt-" + "8" * 32,
        "prod_admission_context": _promotion_admission_context(),
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
        "source_repo": ROOT,
    }
    report_a = _promotion_check_report()
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            rendered=rendered_b,
            channel_manifest=manifest_b,
            check_report=report_a,
            **common,
        )
    assert exc_info.value.code == "check_report_candidate_mismatch"
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            rendered=rendered_a,
            channel_manifest=manifest_a,
            check_report=report_a,
            **dict(
                common,
                prod_admission_context=_promotion_admission_context(
                    migration_baseline_sha=previous_source_sha
                ),
            ),
        )
    assert exc_info.value.code == "migration_baseline_mismatch"
    assert not (store / "receipts").exists()

    first = write_promotion_test_terminal_receipt(
        rendered=rendered_a,
        channel_manifest=manifest_a,
        check_report=report_a,
        **common,
    )
    report_b = build_promotion_test_check_report(
        rendered=rendered_b,
        channel_manifest=manifest_b,
        prod_admission_context=_promotion_admission_context(),
        check_results=_promotion_check_results(),
        source_repo=ROOT,
    )
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            rendered=rendered_b,
            channel_manifest=manifest_b,
                check_report=report_b,
                **dict(
                    common,
                    prod_admission_context=_promotion_admission_context(),
                ),
        )
    assert exc_info.value.code == "attempt_conflict"
    assert len(list((common["receipt_store"] / "receipts").glob("*.json"))) == 1
    assert first["outcome"] == "PASS"


def test_promotion_test_classifies_same_migration_snapshot_used_for_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.release_channels import promotion_receipt

    private_key, public_key = _promotion_test_signing_material()
    repo, baseline, target = _promotion_migration_git_delta(
        tmp_path,
        content='reversibility = "reversible"\n',
    )
    rendered, manifest = _promotion_test_candidate_inputs(source_sha=target)
    report = _promotion_check_report(
        source_repo=repo,
        migration_baseline_sha=baseline,
        source_sha=target,
    )
    migration = repo / "app" / "alembic" / "versions" / "receipt_delta.py"
    real_check = promotion_receipt.check_migration_snapshots

    def mutate_worktree_while_classifying(snapshots):
        migration.write_text(
            'reversibility = "forward-only"\n',
            encoding="utf-8",
        )
        return real_check(snapshots)

    monkeypatch.setattr(
        promotion_receipt,
        "check_migration_snapshots",
        mutate_worktree_while_classifying,
    )
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    receipt = write_promotion_test_terminal_receipt(
        attempt_id="pt-" + "b" * 32,
        rendered=rendered,
        channel_manifest=manifest,
        prod_admission_context=_promotion_admission_context(
            migration_baseline_sha=baseline
        ),
        check_report=report,
        source_repo=repo,
        issued_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        fresh_until=datetime(2026, 8, 17, tzinfo=timezone.utc),
        issuer_id="promotion-test-issuer",
        issuer_key_id="promotion-test-issuer-key-v1",
        signer=private_key.sign,
        issuer_public_key=public_key,
        receipt_store=store,
        resettable_roots=(tmp_path / "tmp-test", tmp_path / "vault-test"),
    )
    attempt = json.loads(next((store / "attempts").glob("*.json")).read_text())
    assert receipt["outcome"] == "PASS"
    assert attempt["migration_classification"]["reversible"] == ["receipt_delta.py"]
    assert attempt["migration_classification"]["forward_only"] == []
    assert migration.read_text(encoding="utf-8") == 'reversibility = "forward-only"\n'


def test_promotion_test_attempt_publication_never_overwrites_racing_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.release_channels import promotion_receipt

    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    real_install = promotion_receipt._install_immutable_record

    def install_with_racing_path(path: Path, data: bytes, *, code: str) -> None:
        if path.parent.name == "attempts":
            path.write_bytes(b"{}")
        real_install(path, data, code=code)

    monkeypatch.setattr(
        promotion_receipt,
        "_install_immutable_record",
        install_with_racing_path,
    )
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            attempt_id="pt-" + "9" * 32,
            rendered=rendered,
            channel_manifest=manifest,
            prod_admission_context=_promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            issued_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            fresh_until=datetime(2026, 8, 17, tzinfo=timezone.utc),
            issuer_id="promotion-test-issuer",
            issuer_key_id="promotion-test-issuer-key-v1",
            signer=private_key.sign,
            issuer_public_key=public_key,
            receipt_store=store,
            resettable_roots=(tmp_path / "tmp-test", tmp_path / "vault-test"),
        )
    assert exc_info.value.code == "attempt_conflict"
    assert next((store / "attempts").glob("*.json")).read_bytes() == b"{}"
    assert len(list((store / "receipts").glob("*.json"))) == 1


def test_promotion_test_fences_preprovisioned_store_and_child_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.release_channels import promotion_receipt

    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    real_fsync = promotion_receipt._fsync_directory
    fenced: list[Path] = []

    def observed_fsync(path: Path) -> None:
        fenced.append(path)
        real_fsync(path)

    monkeypatch.setattr(promotion_receipt, "_fsync_directory", observed_fsync)
    write_promotion_test_terminal_receipt(
        attempt_id="pt-" + "a" * 32,
        rendered=rendered,
        channel_manifest=manifest,
        prod_admission_context=_promotion_admission_context(),
        check_report=_promotion_check_report(),
        source_repo=ROOT,
        issued_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        fresh_until=datetime(2026, 8, 17, tzinfo=timezone.utc),
        issuer_id="promotion-test-issuer",
        issuer_key_id="promotion-test-issuer-key-v1",
        signer=private_key.sign,
        issuer_public_key=public_key,
        receipt_store=store,
        resettable_roots=(tmp_path / "tmp-test", tmp_path / "vault-test"),
    )
    assert store in fenced

    failed_store = tmp_path / "failed-ops" / "test-promotions"
    _seed_promotion_registry(failed_store, public_key)

    def fail_store_parent_fsync(path: Path) -> None:
        if path == failed_store:
            raise OSError("injected parent durability failure")
        real_fsync(path)

    monkeypatch.setattr(
        promotion_receipt,
        "_fsync_directory",
        fail_store_parent_fsync,
    )
    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(
            attempt_id="pt-" + "c" * 32,
            rendered=rendered,
            channel_manifest=manifest,
            prod_admission_context=_promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            issued_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            fresh_until=datetime(2026, 8, 17, tzinfo=timezone.utc),
            issuer_id="promotion-test-issuer",
            issuer_key_id="promotion-test-issuer-key-v1",
            signer=private_key.sign,
            issuer_public_key=public_key,
            receipt_store=failed_store,
            resettable_roots=(tmp_path / "tmp-test", tmp_path / "vault-test"),
        )
    assert exc_info.value.code == "receipt_store_unavailable"
    assert list((failed_store / "receipts").glob("*.json")) == []


@pytest.mark.parametrize(
    ("target_kind", "target_occurrence"),
    [
        ("store", 1),
        ("store", 2),
        ("store", 3),
        ("reservations", 1),
        ("receipts", 1),
        ("attempts", 1),
    ],
)
def test_promotion_test_retry_refences_every_uncertain_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
    target_occurrence: int,
) -> None:
    from app.release_channels import promotion_receipt

    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    targets = {
        "store": store,
        "reservations": store / "reservations",
        "receipts": store / "receipts",
        "attempts": store / "attempts",
    }
    target = targets[target_kind]
    real_fsync = promotion_receipt._fsync_directory
    target_calls = 0

    def fail_once(path: Path) -> None:
        nonlocal target_calls
        if path == target:
            target_calls += 1
            if target_calls == target_occurrence:
                raise OSError("injected uncertain directory entry")
        real_fsync(path)

    common = {
        "attempt_id": "pt-" + "d" * 32,
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "check_report": _promotion_check_report(),
        "source_repo": ROOT,
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
    }
    monkeypatch.setattr(promotion_receipt, "_fsync_directory", fail_once)
    with pytest.raises(PromotionReceiptError):
        write_promotion_test_terminal_receipt(**common)

    retry_fences: list[Path] = []

    def observe_retry(path: Path) -> None:
        retry_fences.append(path)
        real_fsync(path)

    monkeypatch.setattr(promotion_receipt, "_fsync_directory", observe_retry)
    receipt = write_promotion_test_terminal_receipt(**common)
    assert receipt["outcome"] == "PASS"
    assert target in retry_fences
    assert len(list((store / "reservations").glob("*.json"))) == 1
    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert len(list((store / "attempts").glob("*.json"))) == 1


@pytest.mark.parametrize("crash_target", ["reservations", "receipts", "attempts"])
def test_promotion_test_recovers_linked_temp_before_terminal_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crash_target: str,
) -> None:
    from app.release_channels import promotion_receipt

    class SimulatedPowerLoss(BaseException):
        pass

    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    target_parent = store / crash_target
    real_unlink = promotion_receipt._unlink_temp

    def lose_power_before_unlink(path: Path) -> None:
        if path.parent == target_parent:
            raise SimulatedPowerLoss
        real_unlink(path)

    common = {
        "attempt_id": "pt-" + "e" * 32,
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "check_report": _promotion_check_report(),
        "source_repo": ROOT,
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
    }
    monkeypatch.setattr(promotion_receipt, "_unlink_temp", lose_power_before_unlink)
    with pytest.raises(SimulatedPowerLoss):
        write_promotion_test_terminal_receipt(**common)
    linked_temps = list(target_parent.glob(".*.tmp"))
    assert len(linked_temps) == 1
    published = [
        path
        for path in target_parent.iterdir()
        if not path.name.startswith(".") and path.is_file()
    ]
    assert any(path.stat().st_nlink == 2 for path in published)

    monkeypatch.setattr(promotion_receipt, "_unlink_temp", real_unlink)
    receipt = write_promotion_test_terminal_receipt(**common)
    assert receipt["outcome"] == "PASS"
    assert list(target_parent.glob(".*.tmp")) == []
    assert all(
        path.stat().st_nlink == 1
        for path in target_parent.iterdir()
        if path.is_file()
    )
    registry = json.loads((store / "registry.json").read_text(encoding="utf-8"))
    assert registry["entries"][receipt["receipt_id"]]["status"] == "issued"


def test_promotion_test_retry_never_reissues_a_revoked_receipt(tmp_path: Path) -> None:
    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    common = {
        "attempt_id": "pt-" + "f" * 32,
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "check_report": _promotion_check_report(),
        "source_repo": ROOT,
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
    }
    receipt = write_promotion_test_terminal_receipt(**common)
    registry_path = store / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["entries"][receipt["receipt_id"]]["status"] = "revoked"
    registry_path.write_bytes(
        json.dumps(
            registry,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    with pytest.raises(PromotionReceiptError) as exc_info:
        write_promotion_test_terminal_receipt(**common)
    assert exc_info.value.code == "registry_entry_conflict"
    persisted = json.loads(registry_path.read_text(encoding="utf-8"))
    assert persisted["entries"][receipt["receipt_id"]]["status"] == "revoked"
    with pytest.raises(PromotionReceiptError) as exc_info:
        prepare_prod_activation(
            receipt,
            persisted,
            _promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            now=datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        )
    assert exc_info.value.code == "receipt_revoked"


def test_promotion_test_never_issues_registry_authority_before_terminal_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.release_channels import promotion_receipt

    class SimulatedPowerLoss(BaseException):
        pass

    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    real_install = promotion_receipt._install_immutable_record

    def lose_power_before_attempt_binding(
        path: Path,
        data: bytes,
        *,
        code: str,
    ) -> None:
        if path.parent == store / "attempts":
            raise SimulatedPowerLoss
        real_install(path, data, code=code)

    monkeypatch.setattr(
        promotion_receipt,
        "_install_immutable_record",
        lose_power_before_attempt_binding,
    )
    with pytest.raises(SimulatedPowerLoss):
        write_promotion_test_terminal_receipt(
            attempt_id="pt-" + "0" * 32,
            rendered=rendered,
            channel_manifest=manifest,
            prod_admission_context=_promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            issued_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
            fresh_until=datetime(2026, 8, 17, tzinfo=timezone.utc),
            issuer_id="promotion-test-issuer",
            issuer_key_id="promotion-test-issuer-key-v1",
            signer=private_key.sign,
            issuer_public_key=public_key,
            receipt_store=store,
            resettable_roots=(tmp_path / "tmp-test", tmp_path / "vault-test"),
        )

    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert list((store / "attempts").glob("*.json")) == []
    registry = json.loads((store / "registry.json").read_text(encoding="utf-8"))
    assert registry["entries"] == {}
    receipt = json.loads(
        next((store / "receipts").glob("*.json")).read_text(encoding="utf-8")
    )
    with pytest.raises(PromotionReceiptError) as exc_info:
        prepare_prod_activation(
            receipt,
            registry,
            _promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            now=datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        )
    assert exc_info.value.code == "receipt_unregistered"


def test_promotion_test_terminal_binding_stays_inadmissible_until_registry_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.release_channels import promotion_receipt

    class SimulatedPowerLoss(BaseException):
        pass

    private_key, public_key = _promotion_test_signing_material()
    rendered, manifest = _promotion_test_candidate_inputs()
    store = tmp_path / "ops" / "test-promotions"
    _seed_promotion_registry(store, public_key)
    real_publish = promotion_receipt._publish_registry_entry
    common = {
        "attempt_id": "pt-" + "3" * 32,
        "rendered": rendered,
        "channel_manifest": manifest,
        "prod_admission_context": _promotion_admission_context(),
        "check_report": _promotion_check_report(),
        "source_repo": ROOT,
        "issued_at": datetime(2026, 8, 16, tzinfo=timezone.utc),
        "fresh_until": datetime(2026, 8, 17, tzinfo=timezone.utc),
        "issuer_id": "promotion-test-issuer",
        "issuer_key_id": "promotion-test-issuer-key-v1",
        "signer": private_key.sign,
        "issuer_public_key": public_key,
        "receipt_store": store,
        "resettable_roots": (tmp_path / "tmp-test", tmp_path / "vault-test"),
    }

    def lose_power_before_registry_issue(
        path: Path,
        *,
        receipt: Mapping[str, object],
        issuer_public_key: bytes,
    ) -> dict[str, object]:
        raise SimulatedPowerLoss

    monkeypatch.setattr(
        promotion_receipt,
        "_publish_registry_entry",
        lose_power_before_registry_issue,
    )
    with pytest.raises(SimulatedPowerLoss):
        write_promotion_test_terminal_receipt(**common)

    assert len(list((store / "receipts").glob("*.json"))) == 1
    assert len(list((store / "attempts").glob("*.json"))) == 1
    registry = json.loads((store / "registry.json").read_text(encoding="utf-8"))
    assert registry["entries"] == {}
    receipt = json.loads(
        next((store / "receipts").glob("*.json")).read_text(encoding="utf-8")
    )
    with pytest.raises(PromotionReceiptError) as exc_info:
        prepare_prod_activation(
            receipt,
            registry,
            _promotion_admission_context(),
            check_report=_promotion_check_report(),
            source_repo=ROOT,
            now=datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        )
    assert exc_info.value.code == "receipt_unregistered"

    monkeypatch.setattr(
        promotion_receipt,
        "_publish_registry_entry",
        real_publish,
    )
    retried = write_promotion_test_terminal_receipt(**common)
    registry = json.loads((store / "registry.json").read_text(encoding="utf-8"))
    assert prepare_prod_activation(
        retried,
        registry,
        _promotion_admission_context(),
        check_report=_promotion_check_report(),
        source_repo=ROOT,
        now=datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
    )["activation_state"] == "validated_not_activated"
