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


def _scalar_gateway_credentials(tmp_path: Path) -> tuple[Path, Path]:
    htpasswd = tmp_path / "scalar.htpasswd"
    htpasswd.write_text(
        "operator:{SHA}5en6G6MezRroT3XKqkdPOmY/BfQ=\n",
        encoding="utf-8",
    )
    auth_netrc = tmp_path / "scalar-auth.netrc"
    auth_netrc.write_text(
        "machine 127.0.0.1 login operator password secret\n",
        encoding="utf-8",
    )
    auth_netrc.chmod(0o600)
    return htpasswd, auth_netrc


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
    assert run_block.index("compose pull") < run_block.index(
        "prepare_instance_state_deployment"
    )
    assert run_block.index("prepare_instance_state_deployment") < run_block.index(
        "migration execution failed"
    )
    assert run_block.index("migration execution failed") < run_block.index(
        "recreate_channel_services"
    )

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

    assert "APP_IMAGE_REPOSITORY=%s\\nAPP_IMAGE_TAG=%s\\n" in write_pin
    assert '$1 != "APP_IMAGE_REPOSITORY" && $1 != "APP_IMAGE_TAG"' in write_pin
    assert '>>"${tmp_file}"' in write_pin
    assert 'mv "${tmp_file}" "${file}"' in write_pin


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
    assert (
        "dry-run: stopping before pin write, docker recreate, health gate, and receipt write"
        in result.stdout
    )
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
    assert (
        "dry-run: stopping before pin write, docker recreate, health gate, and receipt write"
        in result.stdout
    )
    assert pin_path.read_text(encoding="utf-8") == original_pin
    assert not docker_marker.exists()
    assert not curl_marker.exists()


def test_scalar_rollback_uses_guarded_overlay_and_only_safe_services(
    tmp_path: Path,
) -> None:
    base = _compose("docker-compose.yaml")
    scalar_overlay = (
        REPO_ROOT / "docker-compose.scalar-rollback.yml"
    ).read_text(encoding="utf-8")
    assert (
        "  scalar-rollback-gateway:\n"
        "    image: nginx:1.27-alpine\n"
        "    restart: unless-stopped\n"
    ) in scalar_overlay
    for service in ("api", "worker", "watcher", "heimdal-capture-watch"):
        command = " ".join(base["services"][service]["command"])
        assert (
            "vault-registry.md.scalar-rollback-session.json" in command
            and "requires the governed scalar overlay" in command
        )

    root, env, current_sha = _deploy_harness(tmp_path)
    runtime_marker = root / "app/instance/runtime.py"
    runtime_marker.unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/runtime.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "previous scalar image"],
        cwd=root,
        check=True,
    )
    scalar_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    pin_path = _seed_previous_pin(root, current_sha)
    selected_root = tmp_path / "selected-vault"
    selected_root.mkdir()
    htpasswd, auth_netrc = _scalar_gateway_credentials(tmp_path)
    env.update(
        {
            "SCALAR_ROLLBACK_VAULT_BINDING_ID": "binding-explicit",
            "SCALAR_ROLLBACK_VAULT_ROOT": str(selected_root),
            "SCALAR_ROLLBACK_HTPASSWD": str(htpasswd),
            "SCALAR_ROLLBACK_AUTH_NETRC": str(auth_netrc),
            "http_proxy": "http://proxy.invalid:3128",
            "HTTP_PROXY": "http://proxy.invalid:3128",
            "ALL_PROXY": "http://proxy.invalid:3128",
            "NO_PROXY": "",
        }
    )

    result = _run_rollback(root, env, scalar_sha)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"APP_IMAGE_TAG={current_sha}" in pin_path.read_text(encoding="utf-8")
    assert f"APP_IMAGE_TAG={scalar_sha}" in (
        root / "config/deploy/dev.previous.env"
    ).read_text(encoding="utf-8")
    events = _deploy_events(env)
    compose_events = [event for event in events if "docker compose " in event]
    assert compose_events
    assert all(
        "-f " + str(root / "docker-compose.scalar-rollback.yml") in event
        for event in compose_events
    )
    assert any(
        event.endswith(
            "stop api worker watcher heimdal-capture-watch companion-ui "
            "scalar-rollback-gateway"
        )
        for event in events
    )
    assert any(
        event.endswith(
            "up -d --force-recreate scalar-rollback-guard api "
            "scalar-rollback-gateway"
        )
        for event in events
    )
    assert any(
        "--user operator:definitely-invalid" in event
        for event in events
    )
    assert any(
        f"--netrc-file {auth_netrc}" in event
        for event in events
    )
    assert sum(
        "--noproxy *" in event
        for event in events
        if "definitely-invalid" in event or f"--netrc-file {auth_netrc}" in event
    ) == 2
    assert not any(
        "up -d --force-recreate api worker watcher "
        "heimdal-capture-watch companion-ui" in event
        for event in events
    )

    retry = subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", "dev"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert f"target={scalar_sha}" in retry.stdout
    assert f"APP_IMAGE_TAG={current_sha}" in pin_path.read_text(encoding="utf-8")

    bad_gateway_env = dict(env)
    bad_gateway_env["FAKE_SCALAR_GATEWAY_HTTP_STATUS"] = "200"
    bad_gateway = subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", "dev"],
        cwd=root,
        env=bad_gateway_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad_gateway.returncode == 1
    assert "did not reject invalid credentials" in bad_gateway.stderr

    bad_auth_env = dict(env)
    bad_auth_env["FAKE_SCALAR_GATEWAY_AUTH"] = "fail"
    receipt_path = root / "ops/deployments/dev-latest.json"
    receipt_before = receipt_path.read_bytes()
    bad_auth = subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", "dev"],
        cwd=root,
        env=bad_auth_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert bad_auth.returncode == 22
    assert "provisioned credential cannot authenticate" in bad_auth.stderr
    assert receipt_path.read_bytes() == receipt_before


def test_scalar_rollback_rejects_invalid_gateway_credentials_before_mutation(
    tmp_path: Path,
) -> None:
    root, env, current_sha = _deploy_harness(tmp_path)
    (root / "app/instance/runtime.py").unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/runtime.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "previous scalar image"],
        cwd=root,
        check=True,
    )
    scalar_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    _seed_previous_pin(root, current_sha)
    selected_root = tmp_path / "selected-vault"
    selected_root.mkdir()
    htpasswd = tmp_path / "scalar.htpasswd"
    htpasswd.write_text("", encoding="utf-8")
    env.update(
        {
            "SCALAR_ROLLBACK_VAULT_BINDING_ID": "binding-explicit",
            "SCALAR_ROLLBACK_VAULT_ROOT": str(selected_root),
            "SCALAR_ROLLBACK_HTPASSWD": str(htpasswd),
        }
    )

    result = _run_rollback(root, env, scalar_sha)

    assert result.returncode == 78
    assert "credential file is empty or invalid" in result.stderr
    event_log = Path(env["FAKE_DEPLOY_EVENT_LOG"])
    assert not event_log.exists() or not any(
        event.startswith("docker ")
        for event in event_log.read_text(encoding="utf-8").splitlines()
    )

    htpasswd, auth_netrc = _scalar_gateway_credentials(tmp_path)
    auth_netrc.chmod(0o644)
    env["SCALAR_ROLLBACK_HTPASSWD"] = str(htpasswd)
    env["SCALAR_ROLLBACK_AUTH_NETRC"] = str(auth_netrc)
    unsafe_netrc = _run_rollback(root, env, scalar_sha)

    assert unsafe_netrc.returncode == 78
    assert "probe credential is invalid" in unsafe_netrc.stderr


def test_normal_roll_forward_retires_scalar_services_before_recreate(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    env["FAKE_SCALAR_CONTAINERS"] = "1"

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    gateway_lookup = next(
        index
        for index, event in enumerate(events)
        if "com.docker.compose.service=scalar-rollback-gateway" in event
    )
    gateway_remove = events.index("docker rm -f fake-scalar-gateway")
    guard_remove = events.index("docker rm -f fake-scalar-guard")
    instance_state_init = next(
        index
        for index, event in enumerate(events)
        if "run --rm --no-deps -T instance-state-init" in event
    )
    normal_recreate = next(
        index
        for index, event in enumerate(events)
        if event.endswith(
            "up -d --force-recreate api worker watcher "
            "heimdal-capture-watch companion-ui"
        )
    )
    assert gateway_lookup < gateway_remove < instance_state_init < normal_recreate
    assert guard_remove < instance_state_init


def test_scalar_rollback_establishment_failure_retains_retryable_guarded_mode(
    tmp_path: Path,
) -> None:
    root, env, current_sha = _deploy_harness(tmp_path)
    (root / "app/instance/runtime.py").unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/runtime.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "previous scalar image"],
        cwd=root,
        check=True,
    )
    scalar_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    pin_path = _seed_previous_pin(root, current_sha)
    selected_root = tmp_path / "selected-vault"
    selected_root.mkdir()
    htpasswd, auth_netrc = _scalar_gateway_credentials(tmp_path)
    env.update(
        {
            "SCALAR_ROLLBACK_VAULT_BINDING_ID": "binding-explicit",
            "SCALAR_ROLLBACK_VAULT_ROOT": str(selected_root),
            "SCALAR_ROLLBACK_HTPASSWD": str(htpasswd),
            "SCALAR_ROLLBACK_AUTH_NETRC": str(auth_netrc),
            "FAKE_DOCKER_FAIL_MATCH": (
                "up -d --force-recreate scalar-rollback-guard"
            ),
        }
    )

    failed = _run_rollback(root, env, scalar_sha)

    assert failed.returncode == 24
    assert "retaining the current guard pin and scalar rollback target" in failed.stderr
    assert f"APP_IMAGE_TAG={current_sha}" in pin_path.read_text(encoding="utf-8")
    assert f"APP_IMAGE_TAG={scalar_sha}" in (
        root / "config/deploy/dev.previous.env"
    ).read_text(encoding="utf-8")
    assert not any(
        "up -d --force-recreate api worker watcher "
        "heimdal-capture-watch companion-ui" in event
        for event in _deploy_events(env)
    )

    retry_env = dict(env)
    retry_env.pop("FAKE_DOCKER_FAIL_MATCH")
    retry = subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", "dev"],
        cwd=root,
        env=retry_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert f"target={scalar_sha}" in retry.stdout
    assert f"APP_IMAGE_TAG={current_sha}" in pin_path.read_text(encoding="utf-8")


def test_scalar_rollback_fails_before_mutation_without_explicit_inputs(
    tmp_path: Path,
) -> None:
    root, env, current_sha = _deploy_harness(tmp_path)
    (root / "app/instance/runtime.py").unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/runtime.py"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "previous scalar image"],
        cwd=root,
        check=True,
    )
    scalar_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    pin_path = _seed_previous_pin(root, current_sha)
    before = pin_path.read_bytes()

    result = _run_rollback(root, env, scalar_sha)

    assert result.returncode == 78
    assert "SCALAR_ROLLBACK_VAULT_BINDING_ID" in result.stderr
    assert pin_path.read_bytes() == before
    assert not (tmp_path / "docker-called").exists()


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

    assert 'value=data.get("version")' in version_gate
    assert "isinstance(value, dict)" in version_gate
    assert "isinstance(value, str)" in version_gate
    assert 'value.get("git_sha", "")' in version_gate


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


def _seed_previous_pin(root: Path, previous_sha: str, *, channel: str = "dev") -> Path:
    pin_path = root / f"config/deploy/{channel}.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
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
    recreate = "up -d --force-recreate api worker watcher " "heimdal-capture-watch companion-ui"
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
        (
            "FAKE_VERSION_CURL",
            "fail",
            7,
            "fake version curl diagnostic",
            2,
        ),
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
        (
            "FAKE_DOCKER_FAIL_MATCH",
            " ps -q ",
            24,
            "capture-watch gate: service lookup failed",
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
    recreate = "up -d --force-recreate api worker watcher " "heimdal-capture-watch companion-ui"
    assert (
        sum(event.endswith(recreate) for event in _deploy_events(env)) == expected_recreate_attempts
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
    subprocess.run(["git", "add", str(migration.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add forward-only migration"], cwd=root, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env["FAKE_SHA"] = sha
    env["FAKE_POSTDEPLOY_SMOKE"] = "fail"

    result = _run_deploy(root, env, sha, "--ack-forward-only")

    assert result.returncode == 73
    assert f"APP_IMAGE_TAG={sha}" in pin_path.read_text(encoding="utf-8")
    assert "forward-only migration" in result.stderr
    assert "not auto-reversed" in result.stderr
    assert "target pin is retained for a compatible forward fix" in result.stderr


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
    assert f"APP_IMAGE_TAG={pre_rollback_sha}" not in pin_path.read_text(encoding="utf-8")
    recreate = "up -d --force-recreate api worker watcher " "heimdal-capture-watch companion-ui"
    assert sum(event.endswith(recreate) for event in _deploy_events(env)) == 1


def test_manual_rollback_never_runs_target_forward_migration_authority(tmp_path: Path) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    pre_rollback_sha = "7" * 40
    pin_path = _seed_previous_pin(root, pre_rollback_sha)
    migration = root / "app/alembic/versions/reversible_current_only.py"
    migration.write_text(
        'revision = "reversible_current_only"\n'
        f'down_revision = "{rollback_sha[:12]}"\n'
        'reversibility = "reversible"\n'
        "def downgrade():\n    pass\n",
        encoding="utf-8",
    )

    result = _run_rollback(root, env, rollback_sha)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"APP_IMAGE_TAG={rollback_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert not any(" stop api worker watcher" in event for event in events)
    assert not any("exit-code-from migrate" in event for event in events)
    assert not any("instance-state-init" in event for event in events)
    assert not any("deployment-begin" in event for event in events)
    assert not any("deployment-prove" in event for event in events)
    assert not any("deployment-finish" in event for event in events)
    assert not any("docker ps --no-trunc" in event for event in events)


def test_prod_rollback_ensures_external_volume_without_instance_state_authority(
    tmp_path: Path,
) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    pre_rollback_sha = "8" * 40
    pin_path = _seed_previous_pin(root, pre_rollback_sha, channel="prod")

    result = _run_rollback(root, env, rollback_sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"APP_IMAGE_TAG={rollback_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert "docker volume inspect pkm-prod_instance-state" in events
    assert not any("instance-state-init" in event for event in events)
    assert not any("deployment-begin" in event for event in events)
    assert not any("deployment-prove" in event for event in events)
    assert not any("deployment-finish" in event for event in events)
    assert not any("docker ps --no-trunc" in event for event in events)
    assert not any("exit-code-from migrate" in event for event in events)


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
    recreate = "up -d --force-recreate api worker watcher " "heimdal-capture-watch companion-ui"
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


def _commit_migration(root: Path, name: str) -> str:
    """Commit a migration file into the harness repo and return the new HEAD."""
    migration = root / "app/alembic/versions" / name
    migration.write_text(
        'revision = "feedc0de0001"\ndown_revision = None\nreversibility = "reversible"\n'
        "\n\ndef upgrade() -> None:\n    pass\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "app"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add migration"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_missing_target_git_object_blocks_migration_gate(tmp_path: Path) -> None:
    """A partial/corrupt object store must fail the gate loudly, never yield an empty set."""
    root, env, _sha = _deploy_harness(tmp_path)
    target = _commit_migration(root, "feedc0de0001_gate_probe.py")
    blob = subprocess.check_output(
        ["git", "rev-parse", f"{target}:app/alembic/versions/feedc0de0001_gate_probe.py"],
        cwd=root,
        text=True,
    ).strip()
    object_path = root / ".git/objects" / blob[:2] / blob[2:]
    assert object_path.exists()
    object_path.unlink()

    result = _run_deploy(root, env, target)

    assert result.returncode != 0, result.stdout
    assert "failed to materialize the exact" in result.stderr
    assert not (root / "config/deploy/dev.migration-pending.env").exists()


def test_first_deploy_marker_retry_replays_full_classification(tmp_path: Path) -> None:
    """An interrupted first-ever deploy must be retryable from its durable marker."""
    root, env, _sha = _deploy_harness(tmp_path)
    target = _commit_migration(root, "feedc0de0002_first_deploy.py")
    marker = root / "config/deploy/dev.migration-pending.env"
    env = dict(env)
    env["FAKE_VERSION_SHA"] = target
    env["FAKE_HEALTH_VERSION_SHA"] = target

    fail_env = dict(env)
    fail_env["FAKE_DOCKER_FAIL_MATCH"] = "--exit-code-from migrate"
    first = _run_deploy(root, fail_env, target)
    assert first.returncode != 0
    assert marker.exists(), first.stderr
    assert "FROM_SHA=__NO_BASELINE__" in marker.read_text(encoding="utf-8")

    retry = _run_deploy(root, env, target)
    combined = retry.stdout + retry.stderr
    assert "migration retry blocked" not in combined
    assert "migration retry: revalidating" in combined
    assert retry.returncode == 0, retry.stderr
    assert not marker.exists()


def test_rollback_failure_preserves_foreign_pending_marker(tmp_path: Path) -> None:
    """A failing rollback must not delete another deploy attempt's pending marker."""
    root, env, sha = _deploy_harness(tmp_path)
    previous_sha = "5" * 40
    _seed_previous_pin(root, sha)
    (root / "config/deploy/dev.previous.env").write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    marker = root / "config/deploy/dev.migration-pending.env"
    marker.write_text(
        f"FROM_SHA=<none>\nTARGET_SHA={sha}\nACK_FORWARD_ONLY=0\n", encoding="utf-8"
    )

    fail_env = dict(env)
    fail_env["FAKE_DOCKER_FAIL_MATCH"] = "pull"
    result = _run_rollback(root, fail_env, previous_sha)

    assert result.returncode != 0
    assert marker.exists(), "rollback failure must not clear a deploy's pending marker"


def test_channel_mutation_lock_blocks_concurrent_deploy(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    lock_dir = root / "config/deploy/dev.env.lock"
    lock_dir.mkdir(parents=True)

    result = _run_deploy(root, env, sha)
    assert result.returncode == 89
    assert "channel mutation blocked" in result.stderr

    lock_dir.rmdir()
    clean = _run_deploy(root, env, sha)
    assert clean.returncode == 0, clean.stderr
    assert not lock_dir.exists(), "lock must be released on exit"


def test_channel_lock_is_acquired_before_mutable_state_snapshot() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    lock_call = text.index("\nacquire_channel_mutation_lock\n")
    snapshot = text.index('current_sha="$(read_pin')

    assert lock_call < snapshot


def test_incomplete_pending_marker_blocks_retry_with_exit_88(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    marker = root / "config/deploy/dev.migration-pending.env"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("FROM_SHA=\nACK_FORWARD_ONLY=0\n", encoding="utf-8")

    result = _run_deploy(root, env, sha)

    assert result.returncode == 88
    assert "pending migration marker is incomplete" in result.stderr
    assert marker.exists(), "an incomplete marker must be preserved for operator inspection"


def test_pending_target_mismatch_blocks_different_deploy_with_exit_88(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    pending_target = "6" * 40
    marker = root / "config/deploy/dev.migration-pending.env"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        f"FROM_SHA=__NO_BASELINE__\nTARGET_SHA={pending_target}\nACK_FORWARD_ONLY=0\n",
        encoding="utf-8",
    )

    result = _run_deploy(root, env, sha)

    assert result.returncode == 88
    assert f"pending target {pending_target} must be reconciled" in result.stderr
    assert marker.exists(), "a mismatched marker must survive until reconciled"


def test_same_target_retry_preserves_rollback_anchor(tmp_path: Path) -> None:
    """A failed-then-retried deploy must not stamp previous.env with the failed target."""
    root, env, sha = _deploy_harness(tmp_path)
    good_previous = "5" * 40
    _seed_previous_pin(root, good_previous)
    target = _commit_migration(root, "feedc0de0003_anchor_probe.py")
    env = dict(env)
    env["FAKE_VERSION_SHA"] = target
    env["FAKE_HEALTH_VERSION_SHA"] = target
    previous_pin = root / "config/deploy/dev.previous.env"

    fail_env = dict(env)
    fail_env["FAKE_DOCKER_FAIL_MATCH"] = "--exit-code-from migrate"
    first = _run_deploy(root, fail_env, target)
    assert first.returncode != 0
    assert f"APP_IMAGE_TAG={good_previous}" in previous_pin.read_text(encoding="utf-8")

    retry = _run_deploy(root, env, target)
    assert retry.returncode == 0, retry.stderr
    assert f"APP_IMAGE_TAG={good_previous}" in previous_pin.read_text(encoding="utf-8"), (
        "the rollback anchor must survive a same-target retry"
    )
    assert f"APP_IMAGE_TAG={target}" in (root / "config/deploy/dev.env").read_text(encoding="utf-8")


def test_api_service_receives_raw_store_key() -> None:
    """#4422: the deploy wrapper bootstraps the declared api consumer and the
    api service consumes its materialized secret layer, without changing how
    heimdal-capture-watch is provisioned."""
    lib = (REPO_ROOT / "scripts" / "lib" / "deploy_channel_compose.sh").read_text(
        encoding="utf-8"
    )
    # The api consumer bootstrap wrap exists, degrade-visibly, and re-exports
    # its env-file handle under the api-specific name before any nested
    # capture-watch bootstrap can scrub the shared one.
    assert "_deploy_channel_needs_api_ingress_secret" in lib
    assert "_deploy_channel_api_ingress_bootstrap_available" in lib
    assert "--consumer heimdal-api-ingress" in lib
    # Degrade-visibly: the precheck proves contract + Keychain item resolve
    # before the wrap is added, so an unprovisioned key skips the layer
    # loudly instead of failing the deploy (the bootstrap mechanism is
    # fail-closed for kind raw-store-key).
    assert "_security_keychain_lookup" in lib
    assert "continuing without it" in lib
    assert 'HOST_SECRET_RUNTIME_ENV_FILE_API="${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"' in lib
    # The capture-watch provisioning is unchanged.
    assert "--consumer heimdal-capture-watch" in lib
    assert "_deploy_channel_needs_dev_capture_secret" in lib

    syntax = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "scripts" / "lib" / "deploy_channel_compose.sh")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax.returncode == 0, syntax.stderr

    # The api service's env_file chain consumes the api consumer's layer.
    import yaml

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    env_files = compose["services"]["api"]["env_file"]
    api_layers = [
        entry
        for entry in env_files
        if isinstance(entry, dict)
        and "HOST_SECRET_RUNTIME_ENV_FILE_API" in str(entry.get("path", ""))
    ]
    assert len(api_layers) == 1
    assert api_layers[0].get("required") is False

    # The gating helper fires for an unfiltered `up` and for `up api`, not for
    # unrelated service-scoped ups, in every channel.
    probe = (
        'source "$1"; shift; '
        "if _deploy_channel_needs_api_ingress_secret \"$@\"; then echo yes; else echo no; fi"
    )
    lib_path = str(REPO_ROOT / "scripts" / "lib" / "deploy_channel_compose.sh")

    def gate(*args: str) -> str:
        run = subprocess.run(
            ["bash", "-c", probe, "_", lib_path, *args],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        return run.stdout.strip().splitlines()[-1] if run.stdout.strip() else run.stderr

    assert gate("prod", "up", "-d") == "yes"
    assert gate("test", "up", "-d", "api") == "yes"
    assert gate("dev", "up", "-d", "heimdal-capture-watch") == "no"
    assert gate("dev", "logs") == "no"

    # Functional proof of the handle-rename shim and its survival across the
    # nested capture-watch bootstrap's environment scrub: the outer shim
    # renames the shared handle, a simulated inner bootstrap unsets the shared
    # name (exactly what _clean_child_environment does), and the final child
    # still sees the renamed api handle.
    shim = (
        'export HOST_SECRET_RUNTIME_ENV_FILE_API='
        '"${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"; exec "$@"'
    )
    inner_scrub = 'unset HOST_SECRET_RUNTIME_ENV_FILE HEIMDAL_RAW_STORE_KEY; exec "$@"'
    run = subprocess.run(
        [
            "env", "HOST_SECRET_RUNTIME_ENV_FILE=/tmp/api-layer.env",
            "sh", "-c", shim, "_",
            "sh", "-c", inner_scrub, "_",
            "sh", "-c",
            'printf "%s|%s" "${HOST_SECRET_RUNTIME_ENV_FILE_API:-missing}" '
            '"${HOST_SECRET_RUNTIME_ENV_FILE:-scrubbed}"',
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.stdout == "/tmp/api-layer.env|scrubbed", run.stderr
