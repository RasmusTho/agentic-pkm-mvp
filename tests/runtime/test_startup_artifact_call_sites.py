"""Startup-redesign production call-site proofs and deferred skeletons."""

from __future__ import annotations

import hashlib
import ast
import json
import os
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
        ("compose", "missing", "compatibility_resolution_failed:compose_unreadable"),
        ("compose", "malformed", "compatibility_resolution_failed:compose_unreadable"),
        ("compose", "invalid_utf8", "compatibility_resolution_failed:compose_unreadable"),
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
    else:
        damaged_path.write_bytes(b"\xff")

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


@pytest.mark.xfail(strict=True, reason="STARTUP-04 receipt-validator production call site is not implemented")
def test_prod_receipt_validator_is_invoked_before_activation() -> None:
    raise NotImplementedError


@pytest.mark.xfail(strict=True, reason="STARTUP-04 promotion-test receipt writer call site is not implemented")
def test_promotion_test_writes_one_durable_terminal_receipt() -> None:
    raise NotImplementedError
