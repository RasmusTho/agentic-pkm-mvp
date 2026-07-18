from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from tests.deploy.test_deploy_channel import (
    _configure_prod_retry_preflight,
    _deploy_events,
    _deploy_harness,
    _run_deploy,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/deploy_channel.sh"
MAKEFILE = REPO_ROOT / "Makefile"


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_override(loader: _ComposeLoader, node: yaml.Node) -> object:
    return loader.construct_sequence(node)


_ComposeLoader.add_constructor("!override", _construct_override)


def _compose(path: str) -> dict:
    return yaml.load((REPO_ROOT / path).read_text(encoding="utf-8"), Loader=_ComposeLoader)


def _run_script(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _git_sha(ref: str) -> str:
    return subprocess.check_output(["git", "rev-parse", ref], cwd=REPO_ROOT, text=True).strip()


def _read_pin_tag(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("APP_IMAGE_TAG="):
            return line.split("=", 1)[1]
    raise AssertionError(f"missing APP_IMAGE_TAG in {path}")


@contextmanager
def _without_previous_pin(channel: str) -> Iterator[Path]:
    path = REPO_ROOT / "config" / "deploy" / f"{channel}.previous.env"
    original = path.read_text(encoding="utf-8") if path.exists() else None
    path.unlink(missing_ok=True)
    try:
        yield path
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(original, encoding="utf-8")


def _stub_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_marker = tmp_path / "docker-called"
    curl_marker = tmp_path / "curl-called"
    for name, marker in ("docker", docker_marker), ("curl", curl_marker):
        stub = bin_dir / name
        stub.write_text(f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 99\n", encoding="utf-8")
        stub.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env, docker_marker, curl_marker


def test_deploy_sequence_and_forward_only_ack_gate() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "migration_gate" in text
    assert "DEPLOY_ACK_FORWARD_ONLY" in text
    assert "--ack-forward-only" in text
    assert "forward-only migrations require" in text
    assert "migration gate blocked before recreate" in text
    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("migration_gate") < run_block.index("write_pin")
    assert run_block.index("write_pin") < run_block.index("compose pull")
    assert run_block.index("compose pull") < run_block.index("recreate_channel_services")

    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_pin_write_preserves_channel_runtime_env() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    write_pin = text.split("write_pin() {", 1)[1].split("\n}\n", 1)[0]

    assert 'APP_IMAGE_REPOSITORY=%s\\nAPP_IMAGE_TAG=%s\\n' in write_pin
    assert '$1 != "APP_IMAGE_REPOSITORY" && $1 != "APP_IMAGE_TAG"' in write_pin
    assert ">>\"${tmp_file}\"" in write_pin
    assert "mv \"${tmp_file}\" \"${file}\"" in write_pin


def test_health_gate_blocks_and_triggers_rollback() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "health_gate" in text
    assert "http://127.0.0.1:${api_port}/healthz" in text
    assert "http://127.0.0.1:${ui_port}/healthz" in text
    assert 'wait_json_ok "http://127.0.0.1:${ui_port}/healthz"' in text
    assert "isinstance(data, dict)" in text
    assert 'run_postmutation_gate "health gate failed"' in text
    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("recreate_channel_services") < run_block.index("health_gate")
    assert run_block.index("health_gate") < run_block.index("version_gate")


def test_rollback_uses_previous_pin_and_skips_forward_only_reversal() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "rollback" in text
    assert "previous_pin_file" in text
    assert "Do not auto-reverse forward-only migrations" not in text
    assert "forward_only" in text
    assert "ack_forward_only" in text
    assert "forward-only migration(s) are not auto-reversed" in text
    assert "alembic downgrade" not in text


def test_rollback_dry_run_without_sha_parses_flag_and_skips_writes(tmp_path: Path) -> None:
    pin_path = REPO_ROOT / "config" / "deploy" / "dev.env"
    original_pin = pin_path.read_text(encoding="utf-8")
    current_sha = _read_pin_tag(pin_path)
    env, docker_marker, curl_marker = _stub_env(tmp_path)

    with _without_previous_pin("dev"):
        result = _run_script("rollback", "dev", "--dry-run", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"target={current_sha}" in result.stdout
    assert "dry-run: stopping before pin write, docker recreate, health gate, and receipt write" in result.stdout
    assert pin_path.read_text(encoding="utf-8") == original_pin
    assert not docker_marker.exists()
    assert not curl_marker.exists()


def test_rollback_with_explicit_sha_still_allows_flags(tmp_path: Path) -> None:
    explicit_sha = _git_sha("HEAD")
    pin_path = REPO_ROOT / "config" / "deploy" / "dev.env"
    original_pin = pin_path.read_text(encoding="utf-8")
    env, docker_marker, curl_marker = _stub_env(tmp_path)

    with _without_previous_pin("dev"):
        result = _run_script("rollback", "dev", explicit_sha, "--dry-run", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"target={explicit_sha}" in result.stdout
    assert "dry-run: stopping before pin write, docker recreate, health gate, and receipt write" in result.stdout
    assert pin_path.read_text(encoding="utf-8") == original_pin
    assert not docker_marker.exists()
    assert not curl_marker.exists()


def test_app_bind_mount_removed_and_version_authoritative() -> None:
    base = _compose("docker-compose.yaml")
    for service_name in ("api", "worker", "watcher", "companion-ui"):
        service = base["services"][service_name]
        mounts = [str(mount) for mount in service.get("volumes", [])]
        assert "./:/app" not in mounts

    api_mounts = [str(mount) for mount in base["services"]["api"]["volumes"]]
    assert '"/Users:/Users"' not in api_mounts
    assert "/Users:/Users" in api_mounts
    assert "/Volumes:/Volumes" in api_mounts

    text = SCRIPT.read_text(encoding="utf-8")
    assert "/version" in text
    assert "/api/health" in text
    assert "version_gate" in text

    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "APP_CODE_BIND_COMPOSE ?=" in makefile
    assert "APP_CODE_BIND_COMPOSE ?= docker-compose.app-bind.yml" not in makefile
    assert "deploy-dev" in makefile and "deploy-test" in makefile and "deploy-prod" in makefile


def test_version_gate_accepts_health_version_string_or_object() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    version_gate = text.split("version_gate() {", 1)[1].split("\n}\n", 1)[0]

    assert "value=data.get(\"version\")" in version_gate
    assert "isinstance(value, dict)" in version_gate
    assert "isinstance(value, str)" in version_gate
    assert "value.get(\"git_sha\", \"\")" in version_gate


def test_deploy_receipt_embeds_fleet_model_fitness() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "fleet_model_fitness_gate" in text
    assert "app.release_channels.fleet_model_fitness" in text
    assert "--require-pinned" in text
    assert "FLEET_MODEL_FITNESS_JSON" in text
    assert '"fleet_model_fitness"' in text

    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("health_gate") < run_block.index("version_gate")
    assert run_block.index("version_gate") < run_block.index("fleet_model_fitness_gate")
    assert run_block.index("fleet_model_fitness_gate") < run_block.index("record_receipt")


def _seed_previous_pin(
    root: Path, previous_sha: str, *, channel: str = "dev"
) -> Path:
    pin_path = root / f"config/deploy/{channel}.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    return pin_path


def _run_rollback(
    root: Path, env: dict[str, str], sha: str, *, channel: str = "dev"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", channel, sha],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_postdeploy_smoke_failure_rolls_back_previous_pin_and_services(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "1" * 40
    pin_path = _seed_previous_pin(root, previous_sha)
    env["FAKE_POSTDEPLOY_SMOKE"] = "fail"
    env["FAKE_POSTDEPLOY_SMOKE_RC"] = "73"

    result = _run_deploy(root, env, sha)

    assert result.returncode == 73
    assert "fake postdeploy smoke diagnostic" in result.stderr
    assert "companion UI post-deploy smoke failed" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    recreate = (
        "up -d --force-recreate api worker watcher "
        "heimdal-capture-watch companion-ui"
    )
    assert sum(event.endswith(recreate) for event in _deploy_events(env)) == 2
    assert not (root / "ops/deployments/dev-latest.json").exists()


@pytest.mark.parametrize(
    (
        "failure_env",
        "failure_value",
        "expected_status",
        "diagnostic",
        "expected_recreate_attempts",
    ),
    [
        ("FAKE_DOCKER_FAIL_MATCH", " pull ", 24, "image pull failed", 1),
        (
            "FAKE_DOCKER_FAIL_MATCH",
            "up -d --force-recreate",
            24,
            "service recreate/liveness gate failed",
            2,
        ),
        ("FAKE_API_LIVENESS", "fail", 1, "health gate failed", 2),
        ("FAKE_VERSION_SHA", "wrong-sha", 1, "/version reported wrong-sha", 2),
        (
            "FAKE_FLEET_MODEL_FITNESS",
            "fail",
            41,
            "fake fleet-model fitness diagnostic",
            2,
        ),
        (
            "FAKE_RECEIPT_WRITE",
            "fail",
            52,
            "fake receipt write diagnostic",
            2,
        ),
        (
            "FAKE_CAPTURE_WATCH_STATUS",
            "unhealthy",
            1,
            "capture-watch gate: container unhealthy",
            2,
        ),
    ],
)
def test_every_postmutation_gate_has_fail_closed_terminal_handling(
    tmp_path: Path,
    failure_env: str,
    failure_value: str,
    expected_status: int,
    diagnostic: str,
    expected_recreate_attempts: int,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "2" * 40
    pin_path = _seed_previous_pin(root, previous_sha)
    env[failure_env] = failure_value

    result = _run_deploy(root, env, sha)

    assert result.returncode == expected_status
    assert diagnostic in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    recreate = (
        "up -d --force-recreate api worker watcher "
        "heimdal-capture-watch companion-ui"
    )
    assert (
        sum(event.endswith(recreate) for event in _deploy_events(env))
        == expected_recreate_attempts
    )
    assert not (root / "ops/deployments/dev-latest.json").exists()


def test_failed_postmutation_gate_preserves_forward_only_rollback_limitations(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "3" * 40
    pin_path = _seed_previous_pin(root, previous_sha)
    migration = root / "app/alembic/versions/999_forward_only.py"
    migration.write_text('reversibility = "forward-only"\n', encoding="utf-8")
    env["FAKE_POSTDEPLOY_SMOKE"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-forward-only")

    assert result.returncode == 73
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    assert "forward-only migration" in result.stderr
    assert "not auto-reversed" in result.stderr
    assert "code and services only" in result.stderr


def test_failed_manual_rollback_retains_the_known_good_rollback_target(
    tmp_path: Path,
) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    pre_rollback_sha = "4" * 40
    pin_path = _seed_previous_pin(root, pre_rollback_sha)
    env["FAKE_POSTDEPLOY_SMOKE"] = "fail"

    result = _run_rollback(root, env, rollback_sha)

    assert result.returncode == 73
    assert "manual rollback gate failed" in result.stderr
    assert "retaining rollback target" in result.stderr
    assert f"APP_IMAGE_TAG={rollback_sha}" in pin_path.read_text(encoding="utf-8")
    assert f"APP_IMAGE_TAG={pre_rollback_sha}" not in pin_path.read_text(
        encoding="utf-8"
    )
    recreate = (
        "up -d --force-recreate api worker watcher "
        "heimdal-capture-watch companion-ui"
    )
    assert sum(event.endswith(recreate) for event in _deploy_events(env)) == 1


def test_failed_manual_rollback_before_recreate_restores_pre_rollback_state(
    tmp_path: Path,
) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    pre_rollback_sha = "6" * 40
    pin_path = _seed_previous_pin(root, pre_rollback_sha)
    env["FAKE_DOCKER_FAIL_MATCH"] = " pull "

    result = _run_rollback(root, env, rollback_sha)

    assert result.returncode == 24
    assert "failed before target services were established" in result.stderr
    assert f"APP_IMAGE_TAG={pre_rollback_sha}" in pin_path.read_text(encoding="utf-8")
    assert f"APP_IMAGE_TAG={rollback_sha}" not in pin_path.read_text(encoding="utf-8")
    recreate = (
        "up -d --force-recreate api worker watcher "
        "heimdal-capture-watch companion-ui"
    )
    assert sum(event.endswith(recreate) for event in _deploy_events(env)) == 1


def test_prod_promotion_receipt_failure_does_not_publish_latest_receipt(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "5" * 40
    pin_path = _seed_previous_pin(root, previous_sha, channel="prod")
    _configure_prod_retry_preflight(root, env, tmp_path, rows=[])
    env["FAKE_PROMOTION_RECEIPT_COPY"] = "fail"
    env["FAKE_PROMOTION_RECEIPT_COPY_RC"] = "61"

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 61
    assert "fake promotion receipt copy diagnostic" in result.stderr
    assert "deploy receipt creation failed" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    assert not (root / "ops/deployments/prod-latest.json").exists()
    assert not (root / f"ops/promotions/prod-deploy-{sha}.json").exists()
