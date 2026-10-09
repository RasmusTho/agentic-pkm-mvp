from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from tests.deploy.test_deploy_channel import (
    _HEIMDAL_FIXED_OVERLAY,
    _configure_dev_test_environment_clobber_preflight,
    _configure_prod_retry_preflight,
    _configure_bws_retry_driver,
    _deploy_events,
    _deploy_harness as _base_deploy_harness,
    _run_deploy,
)
from tests.helpers.runtime_identity import runtime_reachable_test_root


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/deploy_channel.sh"
MAKEFILE = REPO_ROOT / "Makefile"


def _deploy_harness(tmp_path: Path) -> tuple[Path, dict[str, str], str]:
    root, env, sha = _base_deploy_harness(tmp_path)
    # BWS deployment callers supply the runtime env path from private host
    # config. Keep the shell harness explicit so it tests the same boundary.
    env["BWS_DEPLOY_RUNTIME_ENV_FILE"] = str(root / "tmp/runtime.env")
    return root, env, sha


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
    runtime_env_resolve = text.index(
        "_deploy_channel_resolve_runtime_env_file", text.index("pin_file=")
    )
    model_access_preflight = text.index("deploy_channel_model_access_preflight \\\n")
    migration_call = text.index(
        'migration_gate "${migration_from_sha}" "${target_sha}"'
    )
    instance_state_setup = text.index("\nprepare_instance_ownership_host_state_dir\n")
    assert runtime_env_resolve < model_access_preflight < migration_call
    assert model_access_preflight < instance_state_setup

    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("migration_gate") < run_block.index("write_pin")
    assert run_block.index("migration_gate") < run_block.index(
        "heimdal_raw_migration_secret_preflight"
    )
    assert run_block.index("heimdal_raw_migration_secret_preflight") < run_block.index(
        "write_pin"
    )
    assert run_block.index("write_pin") < run_block.index("pull_channel_images")
    assert run_block.index("pull_channel_images") < run_block.index(
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


def test_prod_model_access_preflight_runs_before_channel_mutation(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    model_access_env = tmp_path / "model-access-runtime.env"
    unsafe_value = "do-not-log-this-value"
    model_access_env.write_text(
        f"UNSUPPORTED_KEY={unsafe_value}\n",
        encoding="utf-8",
    )
    for relative in (
        "scripts/deploy_channel.sh",
        "scripts/lib/deploy_channel_compose.sh",
    ):
        script_path = root / relative
        script = script_path.read_text(encoding="utf-8")
        script_path.write_text(
            script.replace(
                "/etc/yggdrasil/model-access/runtime.env",
                str(model_access_env),
            ),
            encoding="utf-8",
        )

    result = _run_deploy(root, env, sha, channel="prod")

    assert result.returncode == 78
    assert "model-access runtime env preflight: blocked reason=invalid_contents" in result.stderr
    assert unsafe_value not in result.stdout + result.stderr
    assert not Path(tmp_path / "docker-called").exists()
    assert _deploy_events(env) == ["archive-preflight prod"]
    assert not (root / "config/deploy/prod.env.lock").exists()
    assert not (root / "config/deploy/prod.env").exists()
    assert not (root / "config/deploy/prod.previous.env").exists()
    assert not (root / "config/deploy/prod.migration-pending.env").exists()
    assert not (root / "ops/deployments/prod-latest.json").exists()
    assert not Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"]).exists()


def test_receipt_preflight_is_skipped_for_rollback() -> None:
    text = (REPO_ROOT / "scripts/lib/deploy_channel_compose.sh").read_text(encoding="utf-8")
    receipt_block = text.split('receipt_host_dir="$(_deploy_channel_env_value', 1)[1]
    receipt_block = receipt_block.split("vault_container_root=", 1)[0]
    assert 'if [ "${action:-deploy}" != "rollback" ]' in receipt_block
    assert "pwd -P" in receipt_block


def test_pin_write_preserves_channel_runtime_env() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    write_pin = text.split("write_pin() {", 1)[1].split("\n}\n", 1)[0]

    assert "APP_IMAGE_REPOSITORY=%s\\nAPP_IMAGE_TAG=%s\\n" in write_pin
    assert '$1 != "APP_IMAGE_REPOSITORY" && $1 != "APP_IMAGE_TAG"' in write_pin
    assert '>>"${tmp_file}"' in write_pin
    assert 'mv "${tmp_file}" "${file}"' in write_pin


def test_health_gate_requires_liveness_readiness_and_functional_health() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    health_gate = text.split("health_gate() {", 1)[1].split("\n}\n", 1)[0]
    readiness_wait = text.split("wait_http_success() {", 1)[1].split("\n}\n", 1)[0]
    functional_health_wait = text.split("wait_json_required_ok() {", 1)[1].split(
        "\n}\n", 1
    )[0]

    assert 'wait_json_ok "http://127.0.0.1:${api_port}/healthz"' in health_gate
    assert 'wait_http_success "http://127.0.0.1:${api_port}/readyz"' in health_gate
    assert 'wait_json_required_ok "http://127.0.0.1:${api_port}/api/health"' in health_gate
    assert 'wait_json_ok "http://127.0.0.1:${ui_port}/healthz"' in health_gate
    assert 'curl -fsS --max-time 3 "${url}"' in readiness_wait
    assert 'data.get("required_ok") is True' in functional_health_wait
    assert "isinstance(data, dict)" in text
    assert 'run_postmutation_gate "health gate failed"' in text
    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("recreate_channel_services") < run_block.index("health_gate")
    assert run_block.index("health_gate") < run_block.index("version_gate")


def test_embedding_rebuild_path_preserves_deferred_readiness_exception() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    recreate = text.split("recreate_channel_services() {", 1)[1].split(
        "\n}\n\nscalar_rollback_gateway_auth_gate", 1
    )[0]
    acknowledged_path = recreate.split(
        'if [ "${action}" = "deploy" ] && [ "${ack_embedding_rebuild_required}" = "1" ]; then',
        1,
    )[1].split("  fi\n\n  compose up", 1)[0]

    assert 'wait_json_ok "http://127.0.0.1:${api_port}/healthz"' in acknowledged_path
    assert "/readyz must stay red" in acknowledged_path
    assert 'run_postmutation_gate "health gate failed" health_gate' in text


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
    runtime_marker = root / "app/instance/mvr05_cutover.py"
    runtime_marker.unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/mvr05_cutover.py"],
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
    (root / "app/instance/mvr05_cutover.py").unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/mvr05_cutover.py"],
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
    (root / "app/instance/mvr05_cutover.py").unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/mvr05_cutover.py"],
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
    (root / "app/instance/mvr05_cutover.py").unlink()
    subprocess.run(
        ["git", "add", "-u", "app/instance/mvr05_cutover.py"],
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


def _commit_prefloor_successor(root: Path, label: str) -> str:
    """Create a readable second pre-SETTINGS-05A ref for rollback fixtures."""

    subprocess.run(
        ["git", "commit", "--allow-empty", "-qm", f"fixture {label}"],
        cwd=root,
        check=True,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


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
    root, env, previous_sha = _deploy_harness(tmp_path)
    sha = _commit_prefloor_successor(root, "postdeploy-smoke target")
    env["FAKE_SHA"] = sha
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
    root, env, previous_sha = _deploy_harness(tmp_path)
    sha = _commit_prefloor_successor(root, "postmutation-gate target")
    env["FAKE_SHA"] = sha
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


@pytest.mark.parametrize(
    "runtime_env_text",
    [
        "TTS_ENABLED=false\n",
        'TTS_ENABLED=false\nHEIMDAL_CAPTURE_WATCH_DIR=""\n',
        "TTS_ENABLED=false\nHEIMDAL_CAPTURE_WATCH_DIR=''\n",
        'TTS_ENABLED=false\nHEIMDAL_CAPTURE_WATCH_DIR="" # disabled\n',
    ],
)
def test_unconfigured_capture_watch_does_not_block_or_start_with_deploy(
    tmp_path: Path, runtime_env_text: str
) -> None:
    root, env, base_sha = _deploy_harness(tmp_path)
    sha = _commit_prefloor_successor(root, "capture watch disabled target")
    previous_sha = base_sha
    pin_path = _seed_previous_pin(root, previous_sha)
    (root / "tmp/runtime.env").write_text(runtime_env_text, encoding="utf-8")
    env["FAKE_SHA"] = sha
    env["FAKE_DOCKER_FAIL_MATCH"] = " ps -q "
    fitness_args = tmp_path / "fleet-model-fitness-args.txt"
    env["FAKE_FLEET_MODEL_FITNESS_ARGS_FILE"] = str(fitness_args)

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "capture-watch gate: skipped (HEIMDAL_CAPTURE_WATCH_DIR not configured)"
        in result.stdout
    )
    assert f"APP_IMAGE_TAG={sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert any(event.endswith("pull api worker watcher companion-ui") for event in events)
    assert any(event.endswith("stop heimdal-capture-watch") for event in events)
    assert any(
        event.endswith("up -d --force-recreate api worker watcher companion-ui")
        for event in events
    )
    assert not any(
        "pull api worker watcher heimdal-capture-watch" in event for event in events
    )
    assert not any(
        event.endswith(
            "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
        )
        for event in events
    )
    assert not any("ps -q heimdal-capture-watch" in event for event in events)
    assert (root / "ops/deployments/dev-latest.json").exists()
    assert "--capture-watch-disabled" in fitness_args.read_text(encoding="utf-8")
    assert "--capture-watch-configured" not in fitness_args.read_text(encoding="utf-8")


def test_fleet_model_fitness_gate_passes_capture_configuration(tmp_path: Path) -> None:
    root, env, _ = _deploy_harness(tmp_path)
    sha = _commit_prefloor_successor(root, "capture watcher configured target")
    env["FAKE_SHA"] = sha
    fitness_args = tmp_path / "fleet-model-fitness-args.txt"
    env["FAKE_FLEET_MODEL_FITNESS_ARGS_FILE"] = str(fitness_args)

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    args = fitness_args.read_text(encoding="utf-8")
    assert "--capture-watch-configured" in args
    assert "--capture-watch-disabled" not in args


def test_unconfigured_capture_watch_stays_disabled_during_automatic_recovery(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    sha = _commit_prefloor_successor(root, "capture disabled recovery target")
    env["FAKE_SHA"] = sha
    pin_path = _seed_previous_pin(root, previous_sha)
    (root / "tmp/runtime.env").write_text("TTS_ENABLED=false\n", encoding="utf-8")
    env["FAKE_API_LIVENESS"] = "fail"

    result = _run_deploy(root, env, sha)

    assert result.returncode == 1
    assert "health gate failed" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert sum(event.endswith("stop heimdal-capture-watch") for event in events) == 2
    assert sum(
        event.endswith("up -d --force-recreate api worker watcher companion-ui")
        for event in events
    ) == 2
    assert not any("heimdal-capture-watch companion-ui" in event for event in events)


def test_duplicate_capture_watch_config_fails_before_deploy_mutation(
    tmp_path: Path,
) -> None:
    root, env, base_sha = _deploy_harness(tmp_path)
    sha = _commit_prefloor_successor(root, "capture duplicate target")
    env["FAKE_SHA"] = sha
    (root / "tmp/runtime.env").write_text(
        "TTS_ENABLED=false\n"
        "HEIMDAL_CAPTURE_WATCH_DIR=/fixture/first\n"
        "HEIMDAL_CAPTURE_WATCH_DIR=/fixture/second\n",
        encoding="utf-8",
    )
    pin_path = _seed_previous_pin(root, base_sha)
    original_pin = pin_path.read_text(encoding="utf-8")

    result = _run_deploy(root, env, sha)

    assert result.returncode == 78
    assert (
        "capture-watch config preflight: blocked reason=invalid_runtime_env"
        in result.stderr
    )
    assert pin_path.read_text(encoding="utf-8") == original_pin
    assert _deploy_events(env) == ["archive-preflight dev"]
    assert not Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"]).exists()
    assert not (root / "config/deploy/dev.env.lock").exists()


def test_instance_state_preflight_failure_before_migrations_restores_prior_pin_and_clears_pending_marker(
    tmp_path: Path,
) -> None:
    """MVR-05 preparation fails before Alembic, so its retry state is recoverable."""
    root, env, previous_sha = _deploy_harness(tmp_path)
    pin_path = _seed_previous_pin(root, previous_sha)
    target = _commit_migration(root, "feedc0de0004_instance_state_preflight.py")
    env = dict(env)
    env["FAKE_DOCKER_FAIL_MATCH"] = "run --rm --no-deps -T instance-state-init"

    result = _run_deploy(root, env, target)

    assert result.returncode == 24
    assert "instance-state deployment preparation failed" in result.stderr
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    assert not (root / "config/deploy/dev.migration-pending.env").exists()
    events = _deploy_events(env)
    assert any("run --rm --no-deps -T instance-state-init" in event for event in events)
    assert not any("--exit-code-from migrate" in event for event in events)
    recreate = "up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"
    assert sum(event.endswith(recreate) for event in events) == 1
    assert not (root / "ops/deployments/dev-latest.json").exists()

    retry_target = _commit_prefloor_successor(root, "recovered instance-state preflight")
    retry_env = dict(env)
    retry_env.pop("FAKE_DOCKER_FAIL_MATCH")
    retry_env["FAKE_SHA"] = retry_target
    retry = _run_deploy(root, retry_env, retry_target)

    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert "migration retry blocked" not in retry.stdout + retry.stderr


def test_instance_state_preflight_failure_preserves_ambiguous_marker_on_same_target_retry(
    tmp_path: Path,
) -> None:
    """A prior migration attempt owns its retry marker, not a later MVR-05 failure."""
    root, env, previous_sha = _deploy_harness(tmp_path)
    _seed_previous_pin(root, previous_sha)
    target = _commit_migration(root, "feedc0de0005_instance_state_retry.py")
    env = dict(env)
    env["FAKE_SHA"] = target

    first_env = dict(env)
    first_env["FAKE_DOCKER_FAIL_MATCH"] = "--exit-code-from migrate"
    first = _run_deploy(root, first_env, target)

    marker = root / "config/deploy/dev.migration-pending.env"
    assert first.returncode == 24
    marker_before_retry = marker.read_text(encoding="utf-8")

    retry_env = dict(env)
    retry_env["FAKE_DOCKER_FAIL_MATCH"] = "run --rm --no-deps -T instance-state-init"
    retry = _run_deploy(root, retry_env, target)

    assert retry.returncode == 24
    assert "instance-state deployment preparation failed" in retry.stderr
    assert marker.read_text(encoding="utf-8") == marker_before_retry
    assert f"APP_IMAGE_TAG={target}" in (root / "config/deploy/dev.env").read_text(
        encoding="utf-8"
    )


def test_failed_postmutation_gate_preserves_forward_only_rollback_limitations(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
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
    pre_rollback_sha = _commit_prefloor_successor(root, "pre-manual-rollback pin")
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
    pre_rollback_sha = _commit_prefloor_successor(root, "migration-free rollback pin")
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


def test_manual_rollback_keeps_unconfigured_capture_watch_stopped(
    tmp_path: Path,
) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    current_sha = _commit_prefloor_successor(root, "capture disabled manual rollback pin")
    pin_path = _seed_previous_pin(root, current_sha)
    (root / "tmp/runtime.env").write_text("TTS_ENABLED=false\n", encoding="utf-8")

    result = _run_rollback(root, env, rollback_sha)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "capture-watch gate: skipped (HEIMDAL_CAPTURE_WATCH_DIR not configured)" in result.stdout
    assert f"APP_IMAGE_TAG={rollback_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    assert any(event.endswith("pull api worker watcher companion-ui") for event in events)
    assert any(event.endswith("stop heimdal-capture-watch") for event in events)
    assert any(
        event.endswith("up -d --force-recreate api worker watcher companion-ui")
        for event in events
    )
    assert not any("heimdal-capture-watch" in event for event in events if " pull " in event)
    assert not any("heimdal-capture-watch companion-ui" in event for event in events)


def test_prod_rollback_ensures_external_volume_without_instance_state_authority(
    tmp_path: Path,
) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    pre_rollback_sha = _commit_prefloor_successor(root, "prod rollback pin")
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


def test_prod_rollback_ignores_invalid_optional_model_access_config(
    tmp_path: Path,
) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    pre_rollback_sha = _commit_prefloor_successor(root, "prod rollback with invalid MARR")
    _seed_previous_pin(root, pre_rollback_sha, channel="prod")
    model_access_env = tmp_path / "model-access-runtime.env"
    model_access_env.write_text("UNSUPPORTED_KEY=fixture-invalid-value\n", encoding="utf-8")
    for relative in (
        "scripts/deploy_channel.sh",
        "scripts/lib/deploy_channel_compose.sh",
    ):
        script_path = root / relative
        script = script_path.read_text(encoding="utf-8")
        script_path.write_text(
            script.replace(
                "/etc/yggdrasil/model-access/runtime.env",
                str(model_access_env),
            ),
            encoding="utf-8",
        )

    # Record only the four exported references at the Compose boundary. The
    # inherited canaries must be cleared for previous-good rollback.
    docker_path = Path(env["PATH"].split(os.pathsep)[0]) / "docker"
    docker_script = docker_path.read_text(encoding="utf-8")
    capture = '''if [[ "$*" == compose* ]]; then
  printf 'model-access-bindings %s|%s|%s|%s\\n' \\
    "${MODEL_ACCESS_CODEX_VLAN_ENDPOINT:-}" \\
    "${MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE:-}" \\
    "${MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT:-}" \\
    "${MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY:-}" \\
    >> "${FAKE_DEPLOY_EVENT_LOG:?}"
fi
'''
    docker_path.write_text(
        docker_script.replace("set -eu\n", "set -eu\n" + capture, 1),
        encoding="utf-8",
    )
    for key in (
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT",
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT",
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY",
    ):
        env[key] = "inherited-canary"

    result = _run_rollback(root, env, rollback_sha, channel="prod")

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    compose_events = [event for event in events if event.startswith("docker compose ")]
    assert compose_events
    bindings = [event for event in events if event.startswith("model-access-bindings ")]
    assert bindings
    assert all(event == "model-access-bindings |||" for event in bindings)
    assert any(
        "up -d --force-recreate api worker watcher" in compose_event
        and index > 0
        and events[index - 1] == "model-access-bindings |||"
        for index, compose_event in enumerate(events)
    )
    assert str(model_access_env) not in "\n".join(events)
    assert "fixture-invalid-value" not in result.stdout + result.stderr + "\n".join(events)


def test_prod_automatic_recovery_ignores_marr_config_invalidated_during_deploy(
    tmp_path: Path,
) -> None:
    root, env, previous_sha = _deploy_harness(tmp_path)
    (root / "target.txt").write_text("new candidate\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "new candidate"], cwd=root, check=True)
    target_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    env["FAKE_SHA"] = target_sha

    pin_path = root / "config/deploy/prod.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n"
        f"APP_IMAGE_TAG={previous_sha}\n",
        encoding="utf-8",
    )
    model_access_env = tmp_path / "model-access-runtime.env"
    endpoint = "https://marr.example.test"
    ca_bundle = "/synthetic/marr-ca.pem"
    client_cert = "/synthetic/marr-client.pem"
    client_key = "/synthetic/marr-client-key.pem"
    model_access_env.write_text(
        "\n".join(
            (
                f"MODEL_ACCESS_CODEX_VLAN_ENDPOINT={endpoint}",
                f"MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE={ca_bundle}",
                f"MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT={client_cert}",
                f"MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY={client_key}",
                "",
            )
        ),
        encoding="utf-8",
    )
    for relative in (
        "scripts/deploy_channel.sh",
        "scripts/lib/deploy_channel_compose.sh",
    ):
        script_path = root / relative
        script = script_path.read_text(encoding="utf-8")
        script_path.write_text(
            script.replace(
                "/etc/yggdrasil/model-access/runtime.env",
                str(model_access_env),
            ),
            encoding="utf-8",
        )

    _configure_prod_retry_preflight(root, env, tmp_path, rows=[])
    invalidated_marker = tmp_path / "model-access-invalidated"
    env["FAKE_MODEL_ACCESS_ENV_FILE"] = str(model_access_env)
    env["FAKE_MODEL_ACCESS_INVALIDATED"] = str(invalidated_marker)

    # Capture only the service recreation boundary, then corrupt the optional
    # file during the first recreation and fail that deploy attempt once.
    # Automatic previous-good recovery must pass through Docker with all four
    # references cleared despite the now-invalid source file.
    docker_path = Path(env["PATH"].split(os.pathsep)[0]) / "docker"
    docker_script = docker_path.read_text(encoding="utf-8")
    injection = '''if [[ "$*" == *"up -d --force-recreate api worker watcher heimdal-capture-watch companion-ui"* ]]; then
  printf 'model-access-bindings %s|%s|%s|%s\\n' \\
    "${MODEL_ACCESS_CODEX_VLAN_ENDPOINT:-}" \\
    "${MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE:-}" \\
    "${MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT:-}" \\
    "${MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY:-}" \\
    >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  if [ ! -e "${FAKE_MODEL_ACCESS_INVALIDATED:?}" ]; then
    printf '%s\\n' 'UNSUPPORTED_KEY=fixture-invalid-value' > "${FAKE_MODEL_ACCESS_ENV_FILE:?}"
    touch "${FAKE_MODEL_ACCESS_INVALIDATED}"
    exit 24
  fi
fi
'''
    docker_path.write_text(
        docker_script.replace("set -eu\n", "set -eu\n" + injection, 1),
        encoding="utf-8",
    )

    result = _run_deploy(root, env, target_sha, channel="prod")

    assert result.returncode == 24, result.stdout + result.stderr
    assert invalidated_marker.exists()
    assert f"APP_IMAGE_TAG={previous_sha}" in pin_path.read_text(encoding="utf-8")
    events = _deploy_events(env)
    bindings = [event for event in events if event.startswith("model-access-bindings ")]
    assert bindings == [
        f"model-access-bindings {endpoint}|{ca_bundle}|{client_cert}|{client_key}",
        "model-access-bindings |||",
    ]
    assert str(model_access_env) not in "\n".join(events) + result.stdout + result.stderr
    assert "fixture-invalid-value" not in "\n".join(events) + result.stdout + result.stderr


def test_failed_manual_rollback_before_recreate_restores_pre_rollback_state(
    tmp_path: Path,
) -> None:
    root, env, rollback_sha = _deploy_harness(tmp_path)
    pre_rollback_sha = _commit_prefloor_successor(root, "failed rollback pin")
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
    root, env, previous_sha = _deploy_harness(tmp_path)
    sha = _commit_prefloor_successor(root, "prod receipt target")
    env["FAKE_SHA"] = sha
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
    api service consumes its materialized secret layer. #4362 later made
    heimdal-capture-watch's own provisioning channel-independent (see
    ``test_capture_watch_secret_gate_fires_for_every_channel`` below); this
    test only pins the api-consumer wiring, which #4362 did not change."""
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
    # The shim must also UNSET the shared handle: on a dev unfiltered `up`
    # no inner capture-watch bootstrap runs to scrub it, and a lingering
    # shared handle would deliver the api consumer's layer to the
    # capture-watch service's env_file chain.
    assert "unset HOST_SECRET_RUNTIME_ENV_FILE;" in lib
    # The capture-watch provisioning helper still exists and is still wired.
    assert "--consumer heimdal-capture-watch" in lib
    assert "_deploy_channel_needs_capture_secret" in lib

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
        '"${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"; '
        'unset HOST_SECRET_RUNTIME_ENV_FILE; exec "$@"'
    )
    probe_env = (
        'printf "%s|%s" "${HOST_SECRET_RUNTIME_ENV_FILE_API:-missing}" '
        '"${HOST_SECRET_RUNTIME_ENV_FILE:-scrubbed}"'
    )
    # Without any inner bootstrap (the dev unfiltered-up shape): the shim
    # itself must scrub the shared handle so it can never reach the
    # capture-watch service's env_file chain.
    run = subprocess.run(
        [
            "env", "HOST_SECRET_RUNTIME_ENV_FILE=/tmp/api-layer.env",
            "sh", "-c", shim, "_",
            "sh", "-c", probe_env,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.stdout == "/tmp/api-layer.env|scrubbed", run.stderr
    # And with a simulated nested capture-watch bootstrap scrub in between,
    # the renamed api handle still survives.
    inner_scrub = 'unset HOST_SECRET_RUNTIME_ENV_FILE HEIMDAL_RAW_STORE_KEY; exec "$@"'
    run = subprocess.run(
        [
            "env", "HOST_SECRET_RUNTIME_ENV_FILE=/tmp/api-layer.env",
            "sh", "-c", shim, "_",
            "sh", "-c", inner_scrub, "_",
            "sh", "-c", probe_env,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.stdout == "/tmp/api-layer.env|scrubbed", run.stderr


def test_capture_watch_secret_gate_fires_for_every_channel() -> None:
    """#4362: heimdal-capture-watch's host-secret bootstrap wrap must fire on
    every channel host_secret_contract.json declares the consumer for
    (dev/test/prod), not only dev.

    Before this fix, `_deploy_channel_needs_dev_capture_secret` hardcoded
    `[ "${channel}" = "dev" ] || return 1`, so a `test` or `prod` deploy never
    wrapped the compose invocation and HEIMDAL_RAW_STORE_KEY never reached
    the service's env_file chain there no matter what the Keychain held --
    the operator had to export it ad-hoc at compose time instead (the bug
    report's prod bring-up symptom).
    """
    lib = (REPO_ROOT / "scripts" / "lib" / "deploy_channel_compose.sh").read_text(
        encoding="utf-8"
    )
    assert "_deploy_channel_needs_capture_secret" in lib
    assert "_deploy_channel_needs_dev_capture_secret" not in lib

    probe = (
        'source "$1"; shift; '
        "if _deploy_channel_needs_capture_secret \"$@\"; then echo yes; else echo no; fi"
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

    for channel in ("dev", "test", "prod"):
        assert gate(channel, "up", "-d", "heimdal-capture-watch") == "yes", channel
        assert (
            gate(channel, "up", "-d", "api", "worker", "watcher", "heimdal-capture-watch")
            == "yes"
        ), channel
    assert gate("test", "up", "-d", "api") == "no"
    assert gate("prod", "logs") == "no"

    syntax = subprocess.run(
        ["bash", "-n", lib_path],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax.returncode == 0, syntax.stderr


def test_raw_migration_secret_gate_wraps_only_the_exact_one_shot_command() -> None:
    """HAR-02 migration authority is present on every governed deploy lane."""
    lib_path = str(REPO_ROOT / "scripts" / "lib" / "deploy_channel_compose.sh")
    lib = Path(lib_path).read_text(encoding="utf-8")
    deploy = (REPO_ROOT / "scripts" / "deploy_channel.sh").read_text(encoding="utf-8")

    assert "_deploy_channel_needs_migration_secret" in lib
    assert "--consumer heimdal-raw-migrate" in lib
    assert (
        'HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE="${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"'
        in lib
    )
    assert (
        "compose up --abort-on-container-exit --exit-code-from migrate "
        "--force-recreate migrate"
    ) in deploy

    probe = (
        'source "$1"; shift; DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING=1; '
        "if _deploy_channel_needs_migration_secret \"$@\"; then echo yes; else echo no; fi"
    )

    def gate(*args: str) -> str:
        run = subprocess.run(
            ["bash", "-c", probe, "_", lib_path, *args],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr
        return run.stdout.strip().splitlines()[-1]

    for channel in ("dev", "test", "prod"):
        assert (
            gate(
                channel,
                "up",
                "--abort-on-container-exit",
                "--exit-code-from",
                "migrate",
                "--force-recreate",
                "migrate",
            )
            == "yes"
        )
    assert gate("dev", "up", "-d", "api") == "no"
    assert gate("test", "up", "-d", "heimdal-capture-watch") == "no"
    assert gate("prod", "up", "-d") == "no"
    assert gate("prod", "up", "migrate") == "no"
    assert gate("prod", "up", "--exit-code-from", "migrate", "api") == "no"
    assert gate("prod", "logs", "migrate") == "no"

    unselected = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; shift; '
            "if _deploy_channel_needs_migration_secret \"$@\"; then echo yes; else echo no; fi",
            "_",
            lib_path,
            "dev",
            "up",
            "--abort-on-container-exit",
            "--exit-code-from",
            "migrate",
            "--force-recreate",
            "migrate",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert unselected.returncode == 0, unselected.stderr
    assert unselected.stdout.strip().splitlines()[-1] == "no"

    syntax = subprocess.run(
        ["bash", "-n", lib_path],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert syntax.returncode == 0, syntax.stderr

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    migration_layers = [
        entry
        for entry in compose["services"]["migrate"]["env_file"]
        if isinstance(entry, dict)
        and "HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE" in str(entry.get("path", ""))
    ]
    assert migration_layers == [
        {
            "path": "${HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE:-/dev/null}",
            "required": False,
        }
    ]

    # The production shim retains only its migrate-specific pointer. The raw
    # binding and shared pointer remain absent from the child environment.
    shim = (
        'export HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE='
        '"${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"; '
        'unset HOST_SECRET_RUNTIME_ENV_FILE; exec "$@"'
    )
    probe_env = (
        'printf "%s|%s|%s" "${HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE:-missing}" '
        '"${HOST_SECRET_RUNTIME_ENV_FILE:-scrubbed}" '
        '"${HEIMDAL_RAW_STORE_KEY:-scrubbed}"'
    )
    run = subprocess.run(
        [
            "env",
            "HOST_SECRET_RUNTIME_ENV_FILE=fixture-handle",
            "sh",
            "-c",
            shim,
            "_",
            "sh",
            "-c",
            probe_env,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == "fixture-handle|scrubbed|scrubbed"


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_raw_migration_production_wrapper_bootstraps_before_compose(
    tmp_path: Path,
    channel: str,
) -> None:
    """The real channel wrapper resolves the declared key before Docker."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_marker = tmp_path / "docker-called"
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!/usr/bin/env bash\nset -eu\ntouch {docker_marker!s}\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    security = bin_dir / "security"
    security.write_text(
        "#!/usr/bin/env bash\nset -eu\nprintf '%064d\\n' 0\n",
        encoding="utf-8",
    )
    security.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PYTHON": sys.executable,
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(tmp_path / "instance-state"),
            "DEPLOY_TTS_CONFIG_GOVERNED": "1",
            "DEPLOY_TTS_ENABLED": "false",
            "DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING": "1",
            # Use the fixture's fake keychain provider explicitly on Linux.
            "HOST_SECRET_PROVIDER": "keychain",
        }
    )
    env.pop("HOST_SECRET_RUNTIME_ENV_FILE", None)
    env.pop("HOST_SECRET_RUNTIME_ENV_FILE_MIGRATE", None)
    lib_path = REPO_ROOT / "scripts" / "lib" / "deploy_channel_compose.sh"
    command = (
        'source "$1"; '
        "resolve_signboard_root_env() { unset SIGNBOARD_ROOT; }; "
        'deploy_channel_compose "$2" "$3" "$4" "$5" "$6" '
        "up --abort-on-container-exit --exit-code-from migrate --force-recreate migrate"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            command,
            "_",
            str(lib_path),
            str(REPO_ROOT),
            channel,
            f"docker-compose.{channel}.yml",
            f"pkm-{channel}",
            str(REPO_ROOT / "config" / "deploy" / f"{channel}.env"),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert docker_marker.exists()
    assert "HEIMDAL_RAW_STORE_KEY" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["missing", "malformed", "divergent"])
@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_raw_migration_production_wrapper_fails_before_compose_and_redacts(
    tmp_path: Path,
    failure: str,
    channel: str,
) -> None:
    """Unusable migration authority cannot reach Docker or disclose details."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_marker = tmp_path / "docker-called"
    docker = bin_dir / "docker"
    docker.write_text(
        f"#!/usr/bin/env bash\nset -eu\ntouch {docker_marker!s}\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    security = bin_dir / "security"
    if failure == "missing":
        security_body = "echo private-lookup-detail >&2\nexit 44"
    elif failure == "malformed":
        security_body = "printf '%s\\n' private-malformed-material"
    else:
        security_body = (
            'case "$*" in\n'
            '  *heimdal-api-ingress*) printf \'%064d\\n\' 1 ;;\n'
            "  *) printf '%064d\\n' 0 ;;\n"
            "esac"
        )
    security.write_text(
        f"#!/usr/bin/env bash\nset -eu\n{security_body}\n",
        encoding="utf-8",
    )
    security.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PYTHON": sys.executable,
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(tmp_path / "instance-state"),
            "DEPLOY_TTS_CONFIG_GOVERNED": "1",
            "DEPLOY_TTS_ENABLED": "false",
            "DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING": "1",
            # Use the fixture's fake keychain provider explicitly on Linux.
            "HOST_SECRET_PROVIDER": "keychain",
        }
    )
    lib_path = REPO_ROOT / "scripts" / "lib" / "deploy_channel_compose.sh"
    command = (
        'source "$1"; '
        "resolve_signboard_root_env() { unset SIGNBOARD_ROOT; }; "
        'deploy_channel_compose "$2" "$3" "$4" "$5" "$6" '
        "up --abort-on-container-exit --exit-code-from migrate --force-recreate migrate"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            command,
            "_",
            str(lib_path),
            str(REPO_ROOT),
            channel,
            f"docker-compose.{channel}.yml",
            f"pkm-{channel}",
            str(REPO_ROOT / "config" / "deploy" / f"{channel}.env"),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert not docker_marker.exists()
    assert "output=redacted" in combined
    assert "private-lookup-detail" not in combined
    assert "private-malformed-material" not in combined
    assert "heimdal-raw-migrate:heimdal.raw-store-key" not in combined


def _configure_successful_channel_preflights(
    root: Path,
    env: dict[str, str],
    tmp_path: Path,
    *,
    channel: str,
) -> None:
    if channel == "prod":
        _configure_prod_retry_preflight(root, env, tmp_path, rows=[])
        return
    _configure_dev_test_environment_clobber_preflight(
        root,
        env,
        tmp_path,
        channel=channel,
        overlay_content=_HEIMDAL_FIXED_OVERLAY,
    )


def _set_bws_consumer_selection(env: dict[str, str], *, raw_migration: bool) -> None:
    env.update(
        BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED='1',
        BWS_EXPECTED_RAW_MIGRATION_PENDING='1' if raw_migration else '0',
        BWS_DEPLOY_TARGET_REVISION=env['FAKE_SHA'],
    )


def _commit_har_raw_migration(root: Path, name: str) -> str:
    migration = root / "app" / "alembic" / "versions" / name
    migration.write_text(
        'revision = "e7b4c9d2a6f1"\n'
        'down_revision = None\n'
        'reversibility = "forward-only"\n'
        "\n\ndef upgrade() -> None:\n    pass\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "app"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "add HAR raw migration"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_full_deploy_preflights_raw_migration_key_before_any_docker(
    tmp_path: Path,
    channel: str,
) -> None:
    """The production deploy preflight precedes every mutating Docker step."""
    root, env, _initial_sha = _deploy_harness(tmp_path)
    target = _commit_har_raw_migration(
        root,
        "e7b4c9d2a6f1_heimdal_raw_representation.py",
    )
    env["FAKE_SHA"] = target
    env["DEPLOY_ACK_FORWARD_ONLY"] = "1"
    env["FAKE_SECURITY_EVENT_LOG"] = env["FAKE_DEPLOY_EVENT_LOG"]
    _configure_successful_channel_preflights(
        root,
        env,
        tmp_path,
        channel=channel,
    )

    result = _run_deploy(root, env, target, channel=channel)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    first_secret = next(
        index
        for index, event in enumerate(events)
        if event == "security migrate-primary"
    )
    first_docker = next(index for index, event in enumerate(events) if event.startswith("docker "))
    stop = next(index for index, event in enumerate(events) if " stop api worker watcher" in event)
    migrate = next(index for index, event in enumerate(events) if "exit-code-from migrate" in event)
    assert first_secret < first_docker <= stop < migrate


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
@pytest.mark.parametrize("failure", ["missing", "malformed", "divergent"])
def test_full_deploy_raw_migration_key_failure_is_redacted_and_nonmutating(
    tmp_path: Path,
    channel: str,
    failure: str,
) -> None:
    """Bad key authority refuses before pins, markers, volumes, or Docker."""
    root, env, _initial_sha = _deploy_harness(tmp_path)
    target = _commit_har_raw_migration(
        root,
        "e7b4c9d2a6f1_heimdal_raw_representation.py",
    )
    env["FAKE_SHA"] = target
    env["DEPLOY_ACK_FORWARD_ONLY"] = "1"
    env["FAKE_SECURITY_MODE"] = failure
    env["FAKE_SECURITY_EVENT_LOG"] = env["FAKE_DEPLOY_EVENT_LOG"]
    if channel == "test":
        (root / "tmp-test").mkdir()
        (root / "tmp-test" / "runtime.env").write_text(
            "TTS_ENABLED=false\n",
            encoding="utf-8",
        )

    result = _run_deploy(root, env, target, channel=channel)

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert combined.count("migration raw-key preflight failed: output=redacted") == 1
    assert "fixture-private-lookup-detail" not in combined
    assert "fixture-private-malformed-material" not in combined
    assert "heimdal-raw-migrate:heimdal.raw-store-key" not in combined
    assert not (tmp_path / "docker-called").exists()
    assert not (root / "config" / "deploy" / f"{channel}.env").exists()
    assert not (root / "config" / "deploy" / f"{channel}.previous.env").exists()
    assert not (root / "config" / "deploy" / f"{channel}.migration-pending.env").exists()
    assert not (root / "ops" / "deployments" / f"{channel}-latest.json").exists()
    assert not Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"]).exists()
    security_events = _deploy_events(env)
    assert security_events[0] == f"archive-preflight {channel}"
    assert any(
        event == "security migrate-primary"
        for event in security_events[1:]
    )
    assert all(event.startswith("security ") for event in security_events[1:])


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_full_deploy_unrelated_migration_skips_raw_key_lookup(
    tmp_path: Path,
    channel: str,
) -> None:
    """An unrelated migration proceeds without borrowing HAR key authority."""
    root, env, _initial_sha = _deploy_harness(tmp_path)
    target = _commit_migration(root, f"unrelated_{channel}.py")
    env["FAKE_SHA"] = target
    env["FAKE_SECURITY_MODE"] = "matching"
    env["FAKE_SECURITY_EVENT_LOG"] = env["FAKE_DEPLOY_EVENT_LOG"]
    _configure_successful_channel_preflights(
        root,
        env,
        tmp_path,
        channel=channel,
    )

    result = _run_deploy(root, env, target, channel=channel)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    migrate_index = next(
        index for index, event in enumerate(events) if "exit-code-from migrate" in event
    )
    assert not any(event.startswith("security ") for event in events[:migrate_index])
    assert any(" stop api worker watcher" in event for event in events[:migrate_index])


def test_full_deploy_mixed_migration_inventory_still_gates_raw_key(
    tmp_path: Path,
) -> None:
    """Presence of HAR-02 among unrelated migrations keeps the gate active."""
    root, env, _initial_sha = _deploy_harness(tmp_path)
    _commit_migration(root, "unrelated_before_har.py")
    target = _commit_har_raw_migration(
        root,
        "e7b4c9d2a6f1_heimdal_raw_representation.py",
    )
    env["FAKE_SHA"] = target
    env["DEPLOY_ACK_FORWARD_ONLY"] = "1"
    env["FAKE_SECURITY_MODE"] = "missing"
    env["FAKE_SECURITY_EVENT_LOG"] = env["FAKE_DEPLOY_EVENT_LOG"]

    result = _run_deploy(root, env, target, channel="dev")

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert combined.count("migration raw-key preflight failed: output=redacted") == 1
    events = _deploy_events(env)
    assert events[0] == "archive-preflight dev"
    assert any(
        event == "security migrate-primary"
        for event in events[1:]
    )
    assert all(event.startswith("security ") for event in events[1:])
    assert not (tmp_path / "docker-called").exists()


@pytest.mark.parametrize(
    "receipt",
    [
        {
            "migrations_checked": 1,
            "reversible": [],
            "forward_only": [],
            "classification_decisions": [],
        },
        {
            "migrations_checked": 2,
            "reversible": [
                "e7b4c9d2a6f1_heimdal_raw_representation.py",
                "e7b4c9d2a6f1_heimdal_raw_representation.py",
            ],
            "forward_only": [],
            "classification_decisions": [
                {
                    "migration": "e7b4c9d2a6f1_heimdal_raw_representation.py",
                    "classification": "reversible",
                    "is_forward_only": False,
                },
                {
                    "migration": "e7b4c9d2a6f1_heimdal_raw_representation.py",
                    "classification": "reversible",
                    "is_forward_only": False,
                },
            ],
        },
    ],
    ids=["count-mismatch", "duplicate-filename"],
)
def test_full_deploy_invalid_migration_receipt_fails_before_mutation(
    tmp_path: Path,
    receipt: dict[str, object],
) -> None:
    """Malformed or ambiguous classifier output is never deployment authority."""
    root, env, _initial_sha = _deploy_harness(tmp_path)
    reversibility = root / "app" / "release_channels" / "reversibility.py"
    with reversibility.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n\ndef check_all_migrations(paths):\n"
            f"    return {receipt!r}\n"
        )
    target = _commit_migration(root, "untrusted_receipt.py")
    env["FAKE_SHA"] = target
    # CI exports the real checkout on PYTHONPATH.  The harness's explicit
    # top-level package must still make the isolated classifier authoritative.
    env["PYTHONPATH"] = str(REPO_ROOT)

    result = _run_deploy(root, env, target, channel="dev")

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert combined.count("migration gate blocked: invalid migration receipt") == 1
    assert not (tmp_path / "docker-called").exists()
    assert not (root / "config" / "deploy" / "dev.pin").exists()
    assert not (root / "config" / "deploy" / "dev.migration-pending.env").exists()
    assert not (root / "ops" / "deployments" / "dev-latest.json").exists()
    assert not Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"]).exists()


def test_heimdal_capture_watch_host_secret_layer_lives_in_base_compose() -> None:
    """#4362: the HOST_SECRET_RUNTIME_ENV_FILE env_file layer for
    heimdal-capture-watch must live in the base compose file so every
    channel inherits it deterministically, rather than only in the dev
    overlay (which left test/prod without a delivery path for
    HEIMDAL_RAW_STORE_KEY at all)."""
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    env_files = compose["services"]["heimdal-capture-watch"]["env_file"]
    host_secret_layers = [
        entry
        for entry in env_files
        if isinstance(entry, dict)
        and str(entry.get("path", "")) == "${HOST_SECRET_RUNTIME_ENV_FILE:-/dev/null}"
    ]
    assert len(host_secret_layers) == 1
    assert host_secret_layers[0].get("required") is False


def test_deploy_waits_for_in_progress_shared_import_and_rechecks_parity(tmp_path: Path) -> None:
    from dataclasses import replace
    from io import StringIO
    import threading
    from app.ops.postgres_deploy import deploy_from_host
    from tests.ops.test_secret_admin import CANARY
    admin, provider, plan, remote = _bws_host(tmp_path)
    plan = replace(plan, consumers=(*plan.consumers, 'builderops-model-inquiry'))
    provider.seed()
    import_entered, release_import, deploy_finished = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def during_import():
        import_entered.set()
        assert release_import.wait(5)
    provider.on_put = during_import
    def importer():
        try:
            admin.import_stdin('test', 'openai.api-key', StringIO(CANARY))
        except Exception as error:
            errors.append(error)
    def deployer():
        try:
            deploy_from_host(admin, remote, plan, qualified=lambda: None)
        except Exception as error:
            errors.append(error)
        finally:
            deploy_finished.set()
    writer = threading.Thread(target=importer)
    writer.start()
    assert import_entered.wait(5)
    deploy = threading.Thread(target=deployer)
    deploy.start()
    assert not deploy_finished.wait(0.05)
    assert not remote.events
    release_import.set()
    writer.join(5)
    deploy.join(5)
    assert not writer.is_alive() and not deploy.is_alive()
    assert not errors
    assert remote.activation_count == 1
    assert all(provider.values[project, 'shared/openai.api-key'].value == CANARY for project in ('prod', 'non-prod'))
    assert provider.calls[-2:] != [('put', 'non-prod', 'shared/openai.api-key'), ('put', 'prod', 'shared/openai.api-key')]
    last_write = max(i for i, call in enumerate(provider.calls) if call[0] == 'put')
    assert ('read', 'prod', 'shared/openai.api-key') in provider.calls[last_write + 1:]


class _BwsVmEffects:
    def __init__(self, *, running=False, auth=True, quiet=True):
        self.events = []
        self.running = running
        self.auth = auth
        self.quiet = quiet

    def select_active_plan(self, plan):
        return plan

    def preflight(self, plan):
        self.events.append('preflight:' + plan.channel)
        return 'fake-postgres-canary'

    def initialized(self):
        return True

    def materialize(self, password):
        assert password == 'fake-postgres-canary'
        self.events.append('materialized')

    def local_database(self):
        return True

    def database_running(self):
        return self.running

    def start_database_only(self):
        self.events.append('start:db:no-deps')
        self.running = True

    def authenticate(self):
        self.events.append('password-auth')
        if not self.auth:
            raise RuntimeError('fake-postgres-canary')

    def stop_database(self):
        self.events.append('stop:db')
        self.running = False

    def activate(self, plan):
        self.events.append('activate-clients')

    def quiescent(self):
        self.events.append('quiescence')
        return self.quiet


def _bws_worker(tmp_path, effects):
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, DeployWorker
    from uuid import uuid4
    plan = DeployPlan('test', 'a' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'))
    journal = DeployJournal(tmp_path / 'journal', 'test')
    return DeployWorker(journal, effects), journal, plan, str(uuid4())


def test_initialized_postgres_auth_probe_starts_only_database_before_authentication(tmp_path):
    effects = _BwsVmEffects()
    worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    stages = []
    original = journal.write

    def write(identifier, stage):
        stages.append(stage)
        if stage == 'authenticating':
            assert 'start:db:no-deps' not in effects.events
        if stage == 'activating':
            assert 'password-auth' in effects.events
            assert 'activate-clients' not in effects.events
        return original(identifier, stage)

    journal.write = write
    receipt = worker.run(operation_id, plan)
    assert receipt.stage == 'committed'
    assert stages == ['prepared', 'preflighted', 'materialized', 'authenticating', 'activating', 'committed']
    assert effects.events.index('start:db:no-deps') < effects.events.index('password-auth') < effects.events.index('activate-clients')
    assert 'fake-postgres-canary' not in (tmp_path / 'journal/test.json').read_text()


@pytest.mark.parametrize('running,quiet', [(False, True), (True, True), (False, False), (True, False)])
def test_wrong_initialized_postgres_password_leaves_new_consumers_stopped_and_rolls_back_probe(tmp_path, running, quiet):
    from app.ops.postgres_deploy import PostgresDeployError
    effects = _BwsVmEffects(running=running, auth=False, quiet=quiet)
    worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    if quiet:
        assert worker.run(operation_id, plan).stage == 'aborted'
    else:
        with pytest.raises(PostgresDeployError) as failure:
            worker.run(operation_id, plan)
        assert 'fake-postgres-canary' not in str(failure.value)
        assert journal.read().stage == 'authenticating'
    assert 'activate-clients' not in effects.events
    assert ('stop:db' in effects.events) is not running
    assert effects.running is running


def test_deploy_writes_durable_operation_stages_and_terminal_receipt(tmp_path, monkeypatch):
    import os
    effects = _BwsVmEffects()
    worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    events = []
    real_fsync, real_rename = os.fsync, os.rename
    monkeypatch.setattr(os, 'fsync', lambda fd: (events.append('fsync'), real_fsync(fd))[-1])
    monkeypatch.setattr(os, 'rename', lambda *a, **kw: (events.append('rename'), real_rename(*a, **kw))[-1])
    receipt = worker.run(operation_id, plan)
    assert receipt == journal.read()
    assert receipt.evidence().source == 'remote-terminal'
    for index, event in enumerate(events):
        if event == 'rename':
            assert events[index - 1] == events[index + 1] == 'fsync'
    assert (tmp_path / 'journal/test.json').stat().st_mode & 0o777 == 0o600


def test_deploy_nonterminal_remote_receipt_blocks_next_operation(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError
    from uuid import uuid4
    worker, journal, plan, operation_id = _bws_worker(tmp_path, _BwsVmEffects())
    journal.write(operation_id, 'prepared')
    with pytest.raises(PostgresDeployError):
        worker.run(str(uuid4()), plan)
    with pytest.raises(PostgresDeployError):
        worker.run(operation_id, plan)
    assert journal.read().stage == 'prepared'


def test_deploy_nonquiescent_compose_operation_remains_pending(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError
    effects = _BwsVmEffects(quiet=False)
    worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    with pytest.raises(PostgresDeployError):
        worker.run(operation_id, plan)
    assert journal.read().stage == 'activating'
    assert 'activate-clients' in effects.events


def _bws_host(tmp_path, *, missing=False):
    from tests.ops.test_secret_admin import FakeProvider
    from app.ops.host_secret_controller import HostSecretController
    from app.ops.secret_admin import SecretAdmin
    from app.ops.postgres_deploy import DeployPlan, DeployReceipt
    provider = FakeProvider()
    if not missing:
        provider.seed('test/postgres.password', 'fake-role-password', ('non-prod',))
    admin = SecretAdmin(provider, controller=HostSecretController(tmp_path / 'controller'))
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',))

    class Remote:
        def __init__(self):
            self.events = []
            self.empty = missing
            self.receipt = None
            self.lost_ack = False
            self.activation_count = 0
        def prepare(self, operation_id, selected, *, bootstrap):
            self.events.append(('prepare', operation_id, bootstrap))
            assert any(call == ('read', 'non-prod', 'test/postgres.password') for call in provider.calls)
            if bootstrap and not self.empty:
                self.receipt = DeployReceipt(operation_id, 'test', 'deploy', 'aborted', 'aborted')
            return self.empty
        def activate(self, operation_id, selected):
            self.events.append(('activate', operation_id))
            if self.receipt is None:
                self.activation_count += 1
                self.receipt = DeployReceipt(operation_id, 'test', 'deploy', 'committed', 'committed')
            if self.lost_ack:
                self.lost_ack = False
                raise RuntimeError('transport lost')
            return self.receipt
        def join(self, operation_id, selected):
            assert self.receipt is not None and self.receipt.operation_id == operation_id
            return self.receipt
    return admin, provider, plan, Remote()


def test_admin_parity_preflight_precedes_remote_deploy_mutation(tmp_path):
    from app.ops.postgres_deploy import DeployPlan, PostgresDeployError, deploy_from_host
    admin, provider, _, remote = _bws_host(tmp_path)
    provider.seed('shared/openai.api-key', 'a' * 32, ('non-prod',))
    provider.seed('shared/openai.api-key', 'b' * 32, ('prod',))
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db', 'builderops-model-inquiry'))
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=lambda: None)
    assert remote.events == []
    assert ('read', 'prod', 'shared/openai.api-key') in provider.calls
    assert not any(call[0] == 'put' for call in provider.calls)


def test_postgres_password_preflight_precedes_remote_and_vm_mutation(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host
    admin, provider, plan, remote = _bws_host(tmp_path)
    provider.seed('test/postgres.password', '\ninvalid', ('non-prod',))
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=lambda: None)
    assert remote.events == []
    with admin.controller._locked_journal() as descriptor:
        assert admin.controller._pending(descriptor) is None
    effects = _BwsVmEffects()
    def refused(_): raise RuntimeError('unreadable')
    effects.preflight = refused
    worker, journal, _, operation_id = _bws_worker(tmp_path, effects)
    with pytest.raises(RuntimeError):
        worker.run(operation_id, plan)
    assert effects.events == [] and journal.read() is None


def test_existing_secret_deploy_skips_bootstrap_qualification(tmp_path):
    from app.ops.postgres_deploy import deploy_from_host

    admin, provider, plan, remote = _bws_host(tmp_path)
    provider.seed('test/postgres.password', 'fake-role-password', ('non-prod',))
    receipt = deploy_from_host(
        admin,
        remote,
        plan,
        qualified=lambda: pytest.fail('existing-value deployment must not require BWS-write qualification'),
        allow_bootstrap=False,
    )

    assert receipt.stage == 'committed'
    assert remote.activation_count == 1
    assert not any(call[0] == 'put' for call in provider.calls)


def test_existing_secret_deploy_refuses_missing_password_before_remote_mutation(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host

    admin, provider, plan, remote = _bws_host(tmp_path, missing=True)
    with pytest.raises(PostgresDeployError):
        deploy_from_host(
            admin, remote, plan, qualified=lambda: pytest.fail('bootstrap is forbidden'),
            allow_bootstrap=False,
        )

    assert remote.events == []
    assert not any(call[0] == 'put' for call in provider.calls)
    with admin.controller._locked_journal() as descriptor:
        assert admin.controller._pending(descriptor) is None


def test_deploy_controller_binds_bootstrap_mode_before_rpc(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host

    admin, provider, plan, remote = _bws_host(tmp_path)
    provider.seed('test/postgres.password', 'fake-role-password', ('non-prod',))

    def lose_prepare_ack(operation_id, selected, *, bootstrap):
        remote.events.append(('prepare', operation_id, bootstrap))
        raise RuntimeError('simulated lost prepare acknowledgment')

    remote.prepare = lose_prepare_ack
    with pytest.raises(PostgresDeployError):
        deploy_from_host(
            admin, remote, plan, qualified=lambda: None, allow_bootstrap=False,
        )
    with admin.controller._locked_journal() as descriptor:
        pending = admin.controller._pending(descriptor)
    assert pending is not None and pending['allow_bootstrap'] is False
    prior_provider_calls = len(provider.calls)
    prior_remote_events = list(remote.events)

    with pytest.raises(PostgresDeployError):
        deploy_from_host(
            admin, remote, plan, qualified=lambda: pytest.fail('changed mode reached qualification'),
            allow_bootstrap=True,
        )

    assert len(provider.calls) == prior_provider_calls
    assert remote.events == prior_remote_events


def test_legacy_pending_deploy_must_reconcile_before_bootstrap_mode_is_bound(tmp_path):
    from app.ops.host_secret_controller import (
        HostSecretAdmissionError,
        HostSecretController,
        TerminalEvidence,
    )

    controller = HostSecretController(tmp_path)
    with controller.deploy_operation('test') as (operation, resumed):
        assert not resumed
        legacy_operation_id = operation.operation_id
        operation.prepare_mutation()

    with controller._locked_journal() as descriptor:
        pending = controller._pending(descriptor)
    assert pending is not None
    assert pending['operation_id'] == legacy_operation_id
    assert 'allow_bootstrap' not in pending

    with pytest.raises(HostSecretAdmissionError):
        with controller.deploy_operation('test', allow_bootstrap=False):
            pytest.fail('a new mode must not adopt an unbound legacy operation')

    with controller._locked_journal() as descriptor:
        still_pending = controller._pending(descriptor)
    assert still_pending is not None and still_pending['operation_id'] == legacy_operation_id

    controller.reconcile(
        lambda operation_id, kind, target: TerminalEvidence(
            operation_id, kind, target, 'committed', 'remote-terminal'
        )
    )
    with controller.deploy_operation('test', allow_bootstrap=False) as (operation, resumed):
        assert not resumed
        assert operation.operation_id != legacy_operation_id
        assert operation.allow_bootstrap is False


def test_postgres_bootstrap_requires_qualification_before_remote_mutation(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host

    admin, provider, plan, remote = _bws_host(tmp_path, missing=True)

    def reject_qualification():
        assert remote.events == []
        raise PostgresDeployError()

    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=reject_qualification, allow_bootstrap=True)

    assert remote.events == []
    assert not any(call[0] == 'put' for call in provider.calls)
    with admin.controller._locked_journal() as descriptor:
        assert admin.controller._pending(descriptor) is None


def test_vm_reader_recheck_is_project_scoped_and_precedes_compose(tmp_path):
    from app.ops.postgres_deploy import vm_selected_values
    _, _, plan, _ = _bws_host(tmp_path)
    calls = []
    class Reader:
        def lookup(self, project, identity):
            calls.append((project, identity))
            return 'fake-role-password'
    assert vm_selected_values(plan, Reader()) == {'postgres-db': {'postgres.password': 'fake-role-password'}}
    assert calls == [('non-prod', 'test/postgres.password')]
    effects = _BwsVmEffects()
    worker, _, _, operation_id = _bws_worker(tmp_path, effects)
    worker.run(operation_id, plan)
    activation = effects.events.index('activate-clients')
    assert effects.events[activation - 1] == 'preflight:test'


def test_vm_selected_values_deduplicates_bws_identity_per_preflight():
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployPlan, vm_selected_values

    consumers = tuple(DATABASE_CONSUMERS)
    plan = DeployPlan(
        'dev',
        'a' * 40,
        tuple(DATABASE_CONSUMERS.values()),
        consumers,
    )

    class Reader:
        def __init__(self):
            self.calls = []

        def lookup(self, project, identity):
            self.calls.append((project, identity))
            return f'fake-role-password-{len(self.calls)}'

    reader = Reader()
    first = vm_selected_values(plan, reader)
    second = vm_selected_values(plan, reader)

    assert first == {
        consumer: {'postgres.password': 'fake-role-password-1'}
        for consumer in consumers
    }
    assert second == {
        consumer: {'postgres.password': 'fake-role-password-2'}
        for consumer in consumers
    }
    assert reader.calls == [
        ('non-prod', 'dev/postgres.password'),
        ('non-prod', 'dev/postgres.password'),
    ]


def test_inactive_optional_model_credentials_do_not_block_deploy(tmp_path):
    from app.ops.postgres_deploy import deploy_from_host
    admin, provider, plan, remote = _bws_host(tmp_path)
    assert deploy_from_host(admin, remote, plan, qualified=lambda: None).stage == 'committed'
    assert all('openai' not in identity and 'anthropic' not in identity for _, _, identity in provider.calls)


def test_bws_deploy_selects_only_active_secret_consumers(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployPlan

    root = tmp_path
    cfg = SimpleNamespace(channel='test', root=root)
    base = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'))
    monkeypatch.setattr(linux, 'database_input_files', lambda _cfg: [root / 'pin', root / 'runtime'])
    monkeypatch.setattr(linux, 'validate_database_inputs', lambda *_args: None)
    monkeypatch.setattr(linux, 'require_file_protocol', lambda *_args: None)
    selected_state = {'capture': False, 'migration': False}
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _cfg: selected_state['capture'])
    monkeypatch.setattr(linux, '_raw_representation_migration_pending',
                        lambda _cfg, _revision: selected_state['migration'])

    def selected(capture, migration):
        selected_state.update(capture=capture, migration=migration)
        return linux.LinuxEffects(cfg).select_active_plan(base).consumers

    assert selected(False, False) == (*DATABASE_CONSUMERS, 'heimdal-api-ingress')
    assert selected(True, False) == (*DATABASE_CONSUMERS, 'heimdal-api-ingress', 'heimdal-capture-watch')
    assert selected(False, True) == (*DATABASE_CONSUMERS, 'heimdal-api-ingress', 'heimdal-raw-migrate')
    assert selected(True, True) == (
        *DATABASE_CONSUMERS, 'heimdal-api-ingress', 'heimdal-capture-watch', 'heimdal-raw-migrate'
    )


def test_vm_raw_key_selection_matches_target_migration_delta_and_pending_marker(tmp_path):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root = tmp_path / 'repo'
    (root / 'config/deploy').mkdir(parents=True)
    (root / 'app/alembic/versions').mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=root, check=True)
    baseline_migration = root / 'app/alembic/versions/000000000000_baseline.py'
    baseline_migration.write_text('reversibility = "reversible"\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'app'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-qm', 'baseline'], cwd=root, check=True)
    baseline = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()

    target_migration = root / 'app/alembic/versions/e7b4c9d2a6f1_heimdal_raw_representation.py'
    target_migration.write_text('reversibility = "forward-only"\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'app'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-qm', 'add raw migration'], cwd=root, check=True)
    target = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    cfg = linux.LinuxConfig('test', root, root / 'data', 1000, 1000, '', '')
    pin = root / 'config/deploy/test.env'

    pin.write_text(f'APP_IMAGE_TAG={baseline}\n', encoding='utf-8')
    assert linux._raw_representation_migration_pending(cfg, target) is True
    pin.write_text(f'APP_IMAGE_TAG={target}\n', encoding='utf-8')
    assert linux._raw_representation_migration_pending(cfg, target) is False

    pending = root / 'config/deploy/test.migration-pending.env'
    pending.write_text(
        f'FROM_SHA={baseline}\nTARGET_SHA={target}\nACK_FORWARD_ONLY=1\n', encoding='utf-8'
    )
    assert linux._raw_representation_migration_pending(cfg, target) is True
    with pytest.raises(PostgresDeployError):
        linux._raw_representation_migration_pending(cfg, 'f' * 40)


@pytest.mark.parametrize('active_consumer', ['heimdal-capture-watch', 'heimdal-raw-migrate'])
def test_bws_deploy_requires_raw_key_for_active_capture_and_migration(active_consumer):
    from app.ops.bws_secret_reader import BwsItemAbsent
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployPlan, PostgresDeployError, vm_selected_values

    plan = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress', active_consumer))
    calls = []

    class Reader:
        def lookup(self, project, identity):
            calls.append((project, identity))
            if identity.endswith('heimdal.raw-store-key'):
                raise BwsItemAbsent()
            if identity.endswith('github.token'):
                return 'ghp_' + 'x' * 36
            return 'fake-role-password'

    with pytest.raises(PostgresDeployError):
        vm_selected_values(plan, Reader())
    assert calls.count(('non-prod', 'test/heimdal.raw-store-key')) == 1


@pytest.mark.parametrize(
    'active_consumer,capture,migration',
    [('heimdal-capture-watch', True, False), ('heimdal-raw-migrate', False, True)],
)
@pytest.mark.parametrize('quiescent', [True, False])
def test_missing_active_raw_key_stops_supervisor_before_activation(
    tmp_path, monkeypatch, active_consumer, capture, migration, quiescent
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.bws_secret_reader import BwsItemAbsent
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError

    root = tmp_path / 'repo'
    (root / 'config/deploy').mkdir(parents=True)
    journal = DeployJournal(tmp_path / 'journal', 'test')
    lookups = []

    class Reader:
        def lookup(self, _project, identity):
            lookups.append(identity)
            if identity.endswith('heimdal.raw-store-key'):
                raise BwsItemAbsent()
            if identity.endswith('postgres.password'):
                return 'fake-role-password'
            if identity.endswith('github.token'):
                return 'ghp_' + 'x' * 36
            raise AssertionError(identity)

    config = SimpleNamespace(
        channel='test', root=root, journal=journal, reader=lambda: Reader()
    )
    plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'),
    )
    monkeypatch.setattr(
        linux, 'database_input_files', lambda _config: [root / 'pin', root / 'runtime']
    )
    monkeypatch.setattr(linux, 'validate_database_inputs', lambda *_args: None)
    monkeypatch.setattr(linux, 'require_file_protocol', lambda *_args: None)
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _config: capture)
    monkeypatch.setattr(
        linux, '_raw_representation_migration_pending', lambda _config, _revision: migration
    )

    effects = linux.LinuxEffects(config)
    effects.quiescent = lambda: quiescent
    activation_events = []

    def unexpected_activation(event, *_args):
        activation_events.append(event)

    for method in (
        'initialized', 'materialize', 'local_database', 'database_running',
        'start_database_only', 'authenticate', 'stop_database', 'activate',
    ):
        setattr(effects, method, lambda *args, _event=method: unexpected_activation(_event, *args))
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    monkeypatch.setattr(linux, 'LinuxEffects', lambda _config: effects)
    supervisor = linux.DeploymentSupervisor(config)
    operation_id = str(uuid4())
    request = {
        'action': 'prepare', 'operation_id': operation_id,
        'plan': plan.__dict__, 'bootstrap': False,
    }

    if quiescent:
        result = supervisor.request(request)
        assert result['receipt']['terminal_result'] == 'aborted'
        assert journal.read().stage == 'aborted'
        assert not (root / 'config/deploy/test.env.lock').exists()
    else:
        with pytest.raises(PostgresDeployError):
            supervisor.request(request)
        receipt = journal.read()
        assert receipt is not None and receipt.stage == 'prepared'
        assert receipt.terminal_result is None
        assert (root / 'config/deploy/test.env.lock').is_dir()
        retry = {**request, 'operation_id': str(uuid4())}
        with pytest.raises(PostgresDeployError):
            supervisor.request(retry)

    assert active_consumer in effects.active_consumers
    assert effects.password is None
    assert effects.consumer_values == {}
    # The absent raw key is cached for the remaining consumers in this preflight.
    assert sum(identity.endswith('heimdal.raw-store-key') for identity in lookups) == 1
    assert activation_events == []


def test_bws_host_and_vm_preflight_use_active_secret_consumers(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.bws_secret_reader import BwsItemAbsent
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployPlan, PostgresDeployError, deploy_from_host, vm_selected_values

    admin, _provider, _old_plan, remote = _bws_host(tmp_path)
    plan = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'))
    assert deploy_from_host(admin, remote, plan, qualified=lambda: None).stage == 'committed'

    cfg = SimpleNamespace(channel='test', root=tmp_path)
    monkeypatch.setattr(linux, 'database_input_files', lambda _cfg: [tmp_path / 'pin', tmp_path / 'runtime'])
    monkeypatch.setattr(linux, 'validate_database_inputs', lambda *_args: None)
    monkeypatch.setattr(linux, 'require_file_protocol', lambda *_args: None)
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _cfg: False)
    migration_pending = {'value': False}
    monkeypatch.setattr(linux, '_raw_representation_migration_pending',
                        lambda _cfg, _revision: migration_pending['value'])
    selected = linux.LinuxEffects(cfg).select_active_plan(plan)

    class Reader:
        def lookup(self, _project, identity):
            if identity.endswith('heimdal.raw-store-key') or identity.endswith('github.token'):
                raise BwsItemAbsent()
            return 'fake-role-password'

    values = vm_selected_values(selected, Reader())
    assert values['heimdal-api-ingress'] == {}
    migration_pending['value'] = True
    active = linux.LinuxEffects(cfg).select_active_plan(plan)
    with pytest.raises(PostgresDeployError):
        vm_selected_values(active, Reader())


def test_vm_capture_watch_selection_uses_runtime_input_and_fails_on_ambiguity(tmp_path):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    pin_dir = tmp_path / 'config/deploy'
    pin_dir.mkdir(parents=True)
    pin = pin_dir / 'test.env'
    pin.write_text('WATCHER_RUNTIME_ENV_FILE=./runtime.env\n', encoding='utf-8')
    cfg = linux.LinuxConfig('test', tmp_path, tmp_path / 'data', 1000, 1000, '', '')
    assert linux._capture_watch_configured(cfg) is False
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('HEIMDAL_CAPTURE_WATCH_DIR=""\n', encoding='utf-8')
    assert linux._capture_watch_configured(cfg) is False
    runtime.write_text("HEIMDAL_CAPTURE_WATCH_DIR=''\n", encoding='utf-8')
    assert linux._capture_watch_configured(cfg) is False
    runtime.write_text('HEIMDAL_CAPTURE_WATCH_DIR="" # disabled\n', encoding='utf-8')
    assert linux._capture_watch_configured(cfg) is False
    runtime.write_text('HEIMDAL_CAPTURE_WATCH_DIR=/capture\n', encoding='utf-8')
    assert linux._capture_watch_configured(cfg) is True
    alternate = tmp_path / 'alternate.env'
    alternate.write_text('', encoding='utf-8')
    pin.write_text(
        'WATCHER_RUNTIME_ENV_FILE=./runtime.env\n'
        'WATCHER_RUNTIME_ENV_FILE=./alternate.env\n',
        encoding='utf-8',
    )
    assert linux._capture_watch_configured(cfg) is True
    pin.write_text('WATCHER_RUNTIME_ENV_FILE=./runtime.env\n', encoding='utf-8')
    runtime.write_text('HEIMDAL_CAPTURE_WATCH_DIR=/first\nHEIMDAL_CAPTURE_WATCH_DIR=/second\n', encoding='utf-8')
    with pytest.raises(PostgresDeployError):
        linux._capture_watch_configured(cfg)


def test_vm_and_deploy_shell_resolve_quoted_runtime_env_path_consistently(tmp_path):
    from app.ops import postgres_deploy_linux as linux

    root = tmp_path / 'checkout'
    pin_dir = root / 'config/deploy'
    pin_dir.mkdir(parents=True)
    pin = pin_dir / 'test.env'
    pin.write_text('WATCHER_RUNTIME_ENV_FILE="./runtime.env"\n', encoding='utf-8')
    runtime = root / 'runtime.env'
    runtime.write_text('HEIMDAL_CAPTURE_WATCH_DIR=/capture\n', encoding='utf-8')
    cfg = linux.LinuxConfig('test', root, tmp_path / 'data', 1000, 1000, '', '')

    assert linux.database_input_files(cfg)[1] == runtime
    assert linux._capture_watch_configured(cfg) is True

    helper = REPO_ROOT / 'scripts/lib/deploy_channel_compose.sh'
    result = subprocess.run(
        [
            'bash', '-c',
            'source "$1"; _deploy_channel_resolve_runtime_env_file "$2" test "$3"; '
            'printf "%s\\n" "$DEPLOY_CHANNEL_RUNTIME_ENV_FILE"',
            'test', str(helper), str(root), str(pin),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, 'HOST_SECRET_PROVIDER': '', 'BWS_DEPLOY_RUNTIME_ENV_FILE': ''},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(runtime)


def test_bws_runtime_env_config_path_is_used_consistently(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux

    for key in ('DATABASE_URL', 'DB_DSN', 'POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / 'controller'
    pin_dir = root / 'config/deploy'
    pin_dir.mkdir(parents=True)
    pin = pin_dir / 'test.env'
    pin.write_text('WATCHER_RUNTIME_ENV_FILE=./wrong-runtime.env\n', encoding='utf-8')
    runtime = tmp_path / 'channel-runtime' / 'runtime.env'
    runtime.parent.mkdir()
    runtime.write_text(
        'DATABASE_URL=postgresql://app@db:5432/app_test\n'
        'HEIMDAL_CAPTURE_WATCH_DIR=/capture\n',
        encoding='utf-8',
    )
    cfg = linux.LinuxConfig('test', root, tmp_path / 'data', 1000, 1000, '', '', runtime)

    assert linux.database_input_files(cfg) == [pin, runtime]
    assert linux._capture_watch_configured(cfg) is True
    selected_environment = linux.LinuxEffects(cfg).environment()
    assert selected_environment['BWS_DEPLOY_RUNTIME_ENV_FILE'] == str(runtime)
    assert selected_environment['WATCHER_RUNTIME_ENV_FILE'] == str(runtime)

    helper = REPO_ROOT / 'scripts/lib/deploy_channel_compose.sh'
    result = subprocess.run(
        [
            'bash', '-c',
            'source "$1"; _deploy_channel_resolve_runtime_env_file "$2" test "$3"; '
            'printf "%s\\n" "$DEPLOY_CHANNEL_RUNTIME_ENV_FILE"',
            'test', str(helper), str(root), str(pin),
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            'HOST_SECRET_PROVIDER': 'bws',
            'BWS_DEPLOY_RUNTIME_ENV_FILE': str(runtime),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(runtime)


@pytest.mark.parametrize(
    'invalid_path_kind',
    ['missing_config_key', 'missing', 'malformed', 'relative', 'unreadable', 'directory', 'symlink'],
)
def test_bws_runtime_env_config_preflight_fails_before_mutation(tmp_path, monkeypatch, invalid_path_kind):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root = tmp_path / 'controller'
    pin_dir = root / 'config/deploy'
    pin_dir.mkdir(parents=True)
    pin = pin_dir / 'test.env'
    original_pin = b'APP_IMAGE_TAG=' + b'a' * 40 + b'\n'
    pin.write_bytes(original_pin)
    runtime = tmp_path / 'runtime.env'
    runtime_value: object = str(runtime)
    if invalid_path_kind in {'unreadable', 'symlink'}:
        runtime.write_text('LLM_PROVIDER=mock\n', encoding='utf-8')
    elif invalid_path_kind == 'directory':
        runtime.mkdir()
    elif invalid_path_kind == 'relative':
        runtime_value = 'relative/runtime.env'
    elif invalid_path_kind == 'malformed':
        runtime_value = 17
    elif invalid_path_kind == 'missing':
        runtime_value = str(tmp_path / 'missing.env')
    if invalid_path_kind == 'symlink':
        link = tmp_path / 'runtime-link.env'
        link.symlink_to(runtime)
        runtime_value = str(link)

    config = {
        'root': str(root),
        'data_directory': str(tmp_path / 'data'),
        'uid': 1000,
        'gid': 1000,
        'organization_id': '00000000-0000-4000-8000-000000000001',
        'project_id': '00000000-0000-4000-8000-000000000002',
    }
    if invalid_path_kind != 'missing_config_key':
        config['runtime_env_file'] = runtime_value
    monkeypatch.setattr(linux, '_private_json', lambda _path: config)
    mutations: list[object] = []
    monkeypatch.setattr(linux, '_command', lambda *args, **kwargs: mutations.append((args, kwargs)) or '')
    if invalid_path_kind == 'unreadable':
        original_open = os.open

        def deny_runtime_file(path, flags, *args, **kwargs):
            if str(path) == str(runtime):
                raise PermissionError('unreadable test runtime env')
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(linux.os, 'open', deny_runtime_file)

    with pytest.raises(PostgresDeployError):
        linux.LinuxConfig.load('test')
    assert mutations == []
    assert pin.read_bytes() == original_pin


@pytest.mark.parametrize('runtime_path_state', ['absent', 'malformed', 'missing_file', 'unreadable_file'])
def test_bws_token_push_does_not_require_runtime_env_config(tmp_path, monkeypatch, runtime_path_state):
    from app.ops import bws_token_push
    from app.ops import postgres_deploy_linux as linux

    config = {
        'root': str(tmp_path / 'checkout'),
        'data_directory': str(tmp_path / 'data'),
        'uid': 1000,
        'gid': 1000,
        'organization_id': '00000000-0000-4000-8000-000000000001',
        'project_id': '00000000-0000-4000-8000-000000000002',
    }
    if runtime_path_state == 'malformed':
        config['runtime_env_file'] = 17
    elif runtime_path_state in {'missing_file', 'unreadable_file'}:
        runtime = tmp_path / 'runtime.env'
        if runtime_path_state == 'unreadable_file':
            runtime.write_text('LLM_PROVIDER=mock\n', encoding='utf-8')
            monkeypatch.setattr(
                linux,
                '_runtime_env_file_path',
                lambda _path: pytest.fail('token-push must not inspect the runtime env file'),
            )
        config['runtime_env_file'] = str(runtime)
    monkeypatch.setattr(linux, '_private_json', lambda _path: config)
    calls = []

    def remote_main(args, *, app_root):
        calls.append((args, app_root))
        return 0

    monkeypatch.setattr(bws_token_push, 'remote_main', remote_main)

    assert linux.main(['token-push-inspect', 'test']) == 0
    assert calls == [(['token-push-inspect', 'test'], tmp_path / 'checkout')]


def test_bws_worker_guard_rejects_runtime_env_path_override_before_provider_access(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    configured = tmp_path / 'configured-runtime.env'
    configured.write_text('LLM_PROVIDER=mock\n', encoding='utf-8')
    ambient = tmp_path / 'ambient-runtime.env'
    ambient.write_text('LLM_PROVIDER=other\n', encoding='utf-8')
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: SimpleNamespace(runtime_env_file=configured))
    monkeypatch.setattr(os, 'environ', {'BWS_DEPLOY_RUNTIME_ENV_FILE': str(ambient)})
    provider_reads: list[str] = []
    monkeypatch.setattr(linux.PasswordSource, 'verify', lambda _self: provider_reads.append('read'))

    with pytest.raises(PostgresDeployError):
        linux.inherited_worker_guard('test')
    assert provider_reads == []


def test_empty_vm_and_deploy_shell_runtime_selector_use_channel_default(tmp_path):
    from app.ops import postgres_deploy_linux as linux

    root = tmp_path / 'checkout'
    pin_dir = root / 'config/deploy'
    pin_dir.mkdir(parents=True)
    pin = pin_dir / 'test.env'
    runtime = root / 'tmp-test/runtime.env'
    runtime.parent.mkdir(parents=True)
    runtime.write_text('HEIMDAL_CAPTURE_WATCH_DIR=/capture\n', encoding='utf-8')
    cfg = linux.LinuxConfig('test', root, tmp_path / 'data', 1000, 1000, '', '')
    helper = REPO_ROOT / 'scripts/lib/deploy_channel_compose.sh'

    for selector in ('', '""'):
        pin.write_text(f'WATCHER_RUNTIME_ENV_FILE={selector}\n', encoding='utf-8')
        assert linux.database_input_files(cfg)[1] == runtime
        assert linux._capture_watch_configured(cfg) is True
        result = subprocess.run(
            [
                'bash', '-c',
                'source "$1"; _deploy_channel_resolve_runtime_env_file "$2" test "$3"; '
                'printf "%s\\n" "$DEPLOY_CHANNEL_RUNTIME_ENV_FILE"',
                'test', str(helper), str(root), str(pin),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(runtime)


def test_vm_and_deploy_shell_reject_directory_runtime_selector_source(tmp_path):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root = tmp_path / 'checkout'
    pin_dir = root / 'config/deploy'
    pin_dir.mkdir(parents=True)
    pin = pin_dir / 'test.env'
    pin.mkdir()
    cfg = linux.LinuxConfig('test', root, tmp_path / 'data', 1000, 1000, '', '')
    with pytest.raises(PostgresDeployError):
        linux.database_input_files(cfg)

    helper = REPO_ROOT / 'scripts/lib/deploy_channel_compose.sh'
    result = subprocess.run(
        [
            'bash', '-c',
            'source "$1"; _deploy_channel_resolve_runtime_env_file "$2" test "$3"',
            'test', str(helper), str(root), str(pin),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_vm_selector_failure_records_abort_and_releases_channel_lock(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    _, journal, plan, identifier = _bws_worker(tmp_path, _BwsVmEffects())
    root = tmp_path / 'checkout'
    (root / 'config/deploy').mkdir(parents=True)
    config = SimpleNamespace(channel='test', root=root, journal=journal)
    effects = linux.LinuxEffects(config)
    effects.validate_plan = lambda selected: selected.validate()

    def reject_selection(_selected):
        raise PostgresDeployError()

    effects.select_active_plan = reject_selection
    effects.quiescent = lambda: pytest.fail('read-only selection refusal needs no Compose probe')
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    monkeypatch.setattr(linux, 'LinuxEffects', lambda _config: effects)
    supervisor = linux.DeploymentSupervisor(config)

    result = supervisor.request({
        'action': 'prepare', 'operation_id': identifier, 'plan': plan.__dict__, 'bootstrap': False,
    })
    assert supervisor.operation is not None
    assert supervisor.operation.finished.wait(5)
    assert result['receipt']['terminal_result'] == 'aborted'
    receipt = journal.read()
    assert receipt is not None and receipt.stage == 'aborted'
    assert not (root / 'config/deploy/test.env.lock').exists()


def test_supervisor_rejects_changed_root_config_before_admission(tmp_path, monkeypatch):
    from dataclasses import replace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
    from uuid import uuid4

    journal = DeployJournal(tmp_path / 'journal', 'test')
    startup_config = linux.LinuxConfig(
        'test', tmp_path / 'checkout', tmp_path / 'data', 1000, 1000,
        '00000000-0000-4000-8000-000000000001',
        '00000000-0000-4000-8000-000000000002',
        tmp_path / 'runtime-a.env',
    )
    current_config = replace(startup_config, runtime_env_file=tmp_path / 'runtime-b.env')
    monkeypatch.setattr(linux.LinuxConfig, 'journal', property(lambda _self: journal))
    monkeypatch.setattr(
        linux.LinuxConfig, 'load',
        classmethod(lambda _cls, _channel: current_config),
    )
    created_effects = []
    monkeypatch.setattr(
        linux, 'LinuxEffects',
        lambda _config: created_effects.append('created') or pytest.fail('stale config reached effects'),
    )
    supervisor = linux.DeploymentSupervisor(startup_config)
    plan = DeployPlan('test', 'a' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'))

    with pytest.raises(PostgresDeployError):
        supervisor.request({
            'action': 'prepare', 'operation_id': str(uuid4()),
            'plan': plan.__dict__, 'bootstrap': False,
        })

    assert supervisor.operation is None
    assert created_effects == []
    assert journal.read() is None


def test_deploy_lost_ack_reconciles_matching_remote_terminal_receipt(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host
    admin, _, plan, remote = _bws_host(tmp_path)
    remote.lost_ack = True
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=lambda: None)
    original = remote.receipt
    with admin.controller._locked_journal() as descriptor:
        assert admin.controller._pending(descriptor)['operation_id'] == original.operation_id
    receipt = deploy_from_host(admin, remote, plan, qualified=lambda: None)
    assert receipt == original and remote.activation_count == 1
    with admin.controller._locked_journal() as descriptor:
        assert admin.controller._pending(descriptor) is None


def test_postgres_bootstrap_allows_absent_secret_only_for_locked_empty_data_directory(tmp_path):
    from app.ops.postgres_deploy import deploy_from_host
    from tests.ops.test_secret_admin import history
    admin, provider, plan, remote = _bws_host(tmp_path, missing=True)
    def before_put():
        records = history(admin.controller)
        assert records[0]['event'] == 'snapshot' and records[0]['previous_state'] == 'absent'
        assert any(record['event'] == 'prepared' for record in records)
        assert remote.events[0][0] == 'prepare' and remote.events[0][2] is True
    provider.on_put = before_put
    receipt = deploy_from_host(admin, remote, plan, qualified=lambda: None)
    assert receipt.stage == 'committed'
    assert sum(call[0] == 'put' for call in provider.calls) == 1
    assert receipt.operation_id in provider.values['non-prod', 'test/postgres.password'].note


def test_postgres_bootstrap_blocks_absent_secret_for_initialized_directory(tmp_path):
    from app.ops.postgres_deploy import deploy_from_host
    admin, provider, plan, remote = _bws_host(tmp_path, missing=True)
    remote.empty = False
    assert deploy_from_host(admin, remote, plan, qualified=lambda: None).stage == 'aborted'
    assert not any(call[0] == 'put' for call in provider.calls)
    assert remote.activation_count == 0


def test_postgres_secret_generated_only_for_empty_data_directory(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, bootstrap_password
    admin, provider, _, _ = _bws_host(tmp_path, missing=True)
    with admin.controller.deploy_operation('test') as (operation, _):
        with pytest.raises(PostgresDeployError):
            bootstrap_password(admin, operation, empty=False)
    assert provider.calls == []


def test_postgres_bootstrap_retry_reuses_stored_secret_after_interruption(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host
    admin, provider, plan, remote = _bws_host(tmp_path, missing=True)
    original = provider.put
    def commit_then_disconnect(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('lost provider acknowledgment')
    provider.put = commit_then_disconnect
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=lambda: None)
    provider.put = original
    prior_remote_events = list(remote.events)

    def reject_recovery_without_qualification():
        assert remote.events == prior_remote_events
        raise PostgresDeployError()

    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, remote, plan, qualified=reject_recovery_without_qualification)
    assert remote.events == prior_remote_events
    assert deploy_from_host(admin, remote, plan, qualified=lambda: None).stage == 'committed'
    assert sum(call[0] == 'put' for call in provider.calls) == 1


def test_postgres_bootstrap_ambiguous_create_without_matching_operation_note_remains_pending(tmp_path):
    from app.ops.postgres_deploy import PostgresDeployError, deploy_from_host
    admin, provider, plan, remote = _bws_host(tmp_path, missing=True)
    provider.fail['put', 'non-prod'] = RuntimeError('unknown provider send')
    for _ in range(2):
        with pytest.raises(PostgresDeployError):
            deploy_from_host(admin, remote, plan, qualified=lambda: None)
    assert sum(call[0] == 'put' for call in provider.calls) == 1
    assert remote.activation_count == 0
    with admin.controller._locked_journal() as descriptor:
        assert admin.controller._pending(descriptor) is not None


def test_deploy_ssh_loss_joins_same_supervised_operation_until_quiescent(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from dataclasses import asdict, replace
    from types import SimpleNamespace
    import threading
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError
    effects = _BwsVmEffects()
    _, journal, plan, identifier = _bws_worker(tmp_path, effects)
    effects.config = SimpleNamespace(channel='test', journal=journal)
    effects.validate_plan = lambda selected: selected.validate()
    entered, release = threading.Event(), threading.Event()
    counts = {'locks': 0, 'activations': 0}

    @contextmanager
    def channel_lock():
        counts['locks'] += 1
        yield
        assert journal.read().terminal_result == 'committed'

    def activate(selected):
        counts['activations'] += 1
        entered.set()
        assert release.wait(5)

    effects.channel_lock, effects.activate = channel_lock, activate
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: effects.config)
    monkeypatch.setattr(linux, 'LinuxEffects', lambda cfg: effects)
    supervisor = linux.DeploymentSupervisor(effects.config)
    request = {'action': 'prepare', 'operation_id': identifier, 'plan': asdict(plan), 'bootstrap': False}
    assert supervisor.request(request)['ready']
    operation = supervisor.operation
    # Simulate the transport's caller disappearing while its supervised work runs.
    operation.activation.set()
    assert entered.wait(5)
    assert supervisor.request(request)['pending']
    assert supervisor.operation is operation
    with pytest.raises(PostgresDeployError):
        supervisor.request({**request, 'plan': asdict(replace(plan, revision='b' * 40))})
    release.set()
    receipt = supervisor.request({**request, 'action': 'join'})['receipt']
    assert receipt['terminal_result'] == 'committed'
    assert counts == {'locks': 1, 'activations': 1}
    # A daemon restart may serve the old receipt only for its exact bound inputs.
    restarted = linux.DeploymentSupervisor(effects.config)
    assert restarted.request({**request, 'action': 'join'})['receipt'] == receipt
    for changed in ({'bootstrap': True}, {'plan': asdict(replace(plan, revision='c' * 40))}):
        with pytest.raises(PostgresDeployError):
            restarted.request({**request, **changed, 'action': 'join'})
    assert 'fake-postgres-canary' not in (journal.directory / 'test.request.json').read_text()


def test_bws_host_cli_binds_forward_only_ack_to_plan(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.postgres_deploy import DeployReceipt

    controller = SimpleNamespace(directory=tmp_path)
    captured = []
    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, 'configured_admin', lambda: object())
    monkeypatch.setattr(host, 'SecretAdmin', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(host, 'SshDeployRemote', lambda _host: object())
    monkeypatch.setattr(host, 'require_qualification', lambda _controller: None)

    def deploy(_admin, _remote, plan, *, qualified, allow_bootstrap):
        captured.append((plan, allow_bootstrap))
        return DeployReceipt(str(uuid4()), 'test', 'deploy', 'committed', 'committed')

    monkeypatch.setattr(host, 'deploy_from_host', deploy)

    assert host.main(['test', 'a' * 40]) == 0
    assert captured[-1][0].ack_forward_only is False
    assert captured[-1][1] is True
    assert host.main(['test', 'b' * 40, '--ack-forward-only']) == 0
    assert captured[-1][0].ack_forward_only is True
    assert captured[-1][1] is True
    assert host.main(['test', 'c' * 40, '--existing-secrets-only']) == 0
    assert captured[-1][1] is False


def test_bws_supervisor_binds_forward_only_ack_and_refuses_changed_retry(tmp_path, monkeypatch):
    from dataclasses import asdict, replace
    import json
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
    from app.ops.postgres_deploy_linux import DeploymentSupervisor, SshDeployRemote

    journal = DeployJournal(tmp_path / 'journal', 'test')
    operation_id = str(uuid4())
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',), False)
    journal.bind_request(operation_id, plan, False, create=True)
    journal.write(operation_id, 'prepared')
    journal.write(operation_id, 'preflighted')
    journal.write(operation_id, 'materialized')
    journal.write(operation_id, 'activating')
    receipt = journal.write(operation_id, 'committed')
    supervisor = DeploymentSupervisor(SimpleNamespace(channel='test', journal=journal))
    transmitted = []

    def ssh(_argv, **kwargs):
        transmitted.append(json.loads(kwargs['input']))
        return SimpleNamespace(returncode=0, stdout='{"pending": true}')

    monkeypatch.setattr(linux.subprocess, 'run', ssh)
    remote = SshDeployRemote('ygg-test')
    remote._request('join', operation_id, plan)
    request = transmitted[-1]

    assert type(request['plan']['ack_forward_only']) is bool
    assert request['plan']['ack_forward_only'] is False
    assert json.loads((journal.directory / 'test.request.json').read_text())['plan']['ack_forward_only'] is False
    assert supervisor.request(request)['receipt'] == asdict(receipt)
    remote._request('join', operation_id, replace(plan, ack_forward_only=True))
    with pytest.raises(PostgresDeployError):
        supervisor.request(transmitted[-1])

    malformed = asdict(plan)
    malformed['ack_forward_only'] = 1
    with pytest.raises(PostgresDeployError):
        supervisor.request({**request, 'plan': malformed})
    unknown = {**asdict(plan), 'unbound_authority': True}
    with pytest.raises(PostgresDeployError):
        supervisor.request({**request, 'plan': unknown})


@pytest.mark.parametrize('ack_forward_only', [False, True])
def test_bws_activation_uses_only_request_bound_forward_only_ack(tmp_path, monkeypatch, ack_forward_only):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployJournal, DeployPlan

    journal = DeployJournal(tmp_path / 'journal', 'test')
    operation_id = str(uuid4())
    journal.write(operation_id, 'prepared')
    journal.write(operation_id, 'preflighted')
    journal.write(operation_id, 'materialized')
    journal.write(operation_id, 'activating')
    source = tmp_path / 'tmpfs'
    source.mkdir()
    cfg = SimpleNamespace(channel='test', journal=journal, source_directory=source, root=tmp_path)
    effects = linux.LinuxEffects(cfg)
    effects.lock_fd = 123
    effects.source = SimpleNamespace(verify=lambda: None)
    effects.environment = lambda: {
        'HOST_SECRET_PROVIDER': 'bws', 'DEPLOY_ACK_FORWARD_ONLY': '1',
    }
    effects.consumer_values = {
        'heimdal-api-ingress': {}, 'heimdal-capture-watch': {}, 'heimdal-raw-migrate': {},
    }
    effects.active_consumers = (*DATABASE_CONSUMERS, 'heimdal-api-ingress')
    plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), ack_forward_only,
    )
    calls = []

    def command(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs['pass_fds'] == (123,)
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in source.iterdir())
        return ''

    monkeypatch.setattr(linux, '_command', command)
    effects.activate(plan)

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert ('--ack-forward-only' in argv) is ack_forward_only
    assert 'DEPLOY_ACK_FORWARD_ONLY' not in kwargs['env']
    assert list(source.iterdir()) == []


def test_supervisor_loss_never_replays_nonterminal_worker(tmp_path):
    from dataclasses import asdict
    from types import SimpleNamespace
    from app.ops.postgres_deploy_linux import DeploymentSupervisor
    from app.ops.postgres_deploy import PostgresDeployError
    _, journal, plan, identifier = _bws_worker(tmp_path, _BwsVmEffects())
    journal.bind_request(identifier, plan, False, create=True)
    journal.write(identifier, 'prepared')
    supervisor = DeploymentSupervisor(SimpleNamespace(channel='test', journal=journal))
    for action in ('prepare', 'activate', 'join'):
        with pytest.raises(PostgresDeployError):
            supervisor.request({'action': action, 'operation_id': identifier, 'plan': asdict(plan), 'bootstrap': False})
    assert supervisor.operation is None
    assert journal.read().terminal_result is None


@pytest.mark.parametrize(('service', 'state', 'expected'), [
    ('api', 'running', True),
    ('migrate', 'running', False),
    ('instance-state-init', 'running', False),
    ('migrate', 'exited', True),
])
def test_linux_quiescence_waits_for_one_shot_compose_services(monkeypatch, service, state, expected):
    import json
    from app.ops import postgres_deploy_linux as linux

    effects = object.__new__(linux.LinuxEffects)
    monkeypatch.setattr(
        effects, 'compose',
        lambda *args: json.dumps([{'Service': service, 'State': state, 'Health': ''}]),
    )

    assert effects.quiescent() is expected


def test_failed_bws_activation_reconciles_only_after_worker_and_channel_quiescence(tmp_path, monkeypatch):
    from dataclasses import asdict
    import json
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    _, journal, plan, operation_id = _bws_worker(tmp_path, _BwsVmEffects())
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(operation_id, stage)
    root = tmp_path / 'checkout'
    deploy_dir = root / 'config/deploy'
    deploy_dir.mkdir(parents=True)
    lock_dir = deploy_dir / 'test.env.lock'
    lock_dir.mkdir(mode=0o700)
    (lock_dir / 'bws-owner').touch(mode=0o600)
    pin = deploy_dir / 'test.pin'
    pending_marker = deploy_dir / 'test.migration-pending'
    data = tmp_path / 'data/state'
    for path, content in ((pin, b'prior-pin\n'), (pending_marker, b'forward-only\n'), (data, b'preserve\n')):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    config = SimpleNamespace(channel='test', root=root, journal=journal)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    compose_state = {'rows': [{'Service': 'migrate', 'State': 'exited', 'Health': ''}]}
    monkeypatch.setattr(
        linux.LinuxEffects, 'compose',
        lambda _self, *_args: json.dumps(compose_state['rows']),
    )
    supervisor = linux.DeploymentSupervisor(config)

    request = {
        'action': 'reconcile-failed', 'operation_id': operation_id,
        'plan': asdict(plan), 'bootstrap': False,
    }
    original_retire = linux.LinuxEffects.retire_reconciled_channel_lock

    def interrupt_cleanup(_handle):
        raise PostgresDeployError()

    monkeypatch.setattr(
        linux.LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(interrupt_cleanup)
    )
    with pytest.raises(PostgresDeployError):
        supervisor.request(request)
    assert journal.read().terminal_result == 'failed'
    assert lock_dir.is_dir()

    monkeypatch.setattr(
        linux.LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(original_retire)
    )
    # A terminal receipt can outlive lock retirement. Do not finish cleanup
    # while Docker still owns the one-shot migration container.
    compose_state['rows'] = [{'Service': 'migrate', 'State': 'running', 'Health': ''}]
    with pytest.raises(PostgresDeployError):
        supervisor.request({**request, 'action': 'join'})
    assert lock_dir.is_dir()

    compose_state['rows'] = [{'Service': 'migrate', 'State': 'exited', 'Health': ''}]
    # A normal same-ID join must finish interrupted cleanup before exposing the
    # already-written failed receipt to a host retry.
    ordinary_retry = {**request, 'action': 'join'}
    result = supervisor.request(ordinary_retry)

    assert result['receipt']['stage'] == 'failed'
    assert result['receipt']['terminal_result'] == 'failed'
    assert journal.read().evidence().result == 'failed'
    assert not lock_dir.exists()
    assert pin.read_bytes() == b'prior-pin\n'
    assert pending_marker.read_bytes() == b'forward-only\n'
    assert data.read_bytes() == b'preserve\n'
    assert supervisor.request(request) == result

    # After exact cleanup a new operation can acquire the channel lock.
    from uuid import uuid4
    next_effects = linux.LinuxEffects(config)
    next_effects.operation_id = str(uuid4())
    with next_effects.channel_lock():
        assert lock_dir.is_dir()
    assert lock_dir.is_dir()  # nonterminal new operation keeps its admission lock
    (lock_dir / 'bws-owner').unlink()
    lock_dir.rmdir()


@pytest.mark.parametrize('blocker', [
    'live-worker', 'held-lock', 'non-quiescent', 'running-migrate',
    'running-instance-state-init', 'changed-request', 'different-operation', 'malformed-journal',
])
def test_failed_bws_activation_reconciliation_preserves_ambiguous_state(tmp_path, monkeypatch, blocker):
    from dataclasses import asdict, replace
    import fcntl
    import json
    import os
    import threading
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    _, journal, plan, operation_id = _bws_worker(tmp_path, _BwsVmEffects())
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(operation_id, stage)
    root = tmp_path / 'checkout'
    deploy_dir = root / 'config/deploy'
    deploy_dir.mkdir(parents=True)
    lock_dir = deploy_dir / 'test.env.lock'
    lock_dir.mkdir(mode=0o700)
    marker = lock_dir / 'bws-owner'
    marker.touch(mode=0o600)
    pin = deploy_dir / 'test.pin'
    migration_marker = deploy_dir / 'test.migration-pending'
    data = tmp_path / 'data/state'
    for path, content in ((pin, b'prior-pin\n'), (migration_marker, b'pending\n'), (data, b'preserve\n')):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = {
        'journal': (journal.directory / 'test.json').read_bytes(),
        'request': (journal.directory / 'test.request.json').read_bytes(),
        'marker': marker.read_bytes(), 'pin': pin.read_bytes(),
        'migration': migration_marker.read_bytes(), 'data': data.read_bytes(),
    }
    config = SimpleNamespace(channel='test', root=root, journal=journal)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    compose_row = {'Service': 'api', 'State': 'running', 'Health': ''}
    if blocker == 'non-quiescent':
        compose_row = {'Service': 'api', 'State': 'restarting', 'Health': ''}
    elif blocker in {'running-migrate', 'running-instance-state-init'}:
        service = 'migrate' if blocker == 'running-migrate' else 'instance-state-init'
        compose_row = {'Service': service, 'State': 'running', 'Health': ''}
    monkeypatch.setattr(linux.LinuxEffects, 'compose', lambda _self, *_args: json.dumps([compose_row]))
    supervisor = linux.DeploymentSupervisor(config)
    if blocker == 'live-worker':
        supervisor.operation = SimpleNamespace(
            operation_id=operation_id, plan=plan, bootstrap=False, failed=True,
            finished=threading.Event(), thread=SimpleNamespace(is_alive=lambda: True),
        )
        supervisor.operation.finished.set()
    if blocker == 'malformed-journal':
        (journal.directory / 'test.json').write_text('{"invalid":true}\n')
        before['journal'] = (journal.directory / 'test.json').read_bytes()
    request_plan = replace(plan, revision='b' * 40) if blocker == 'changed-request' else plan
    request = {
        'action': 'reconcile-failed',
        'operation_id': str(uuid4()) if blocker == 'different-operation' else operation_id,
        'plan': asdict(request_plan), 'bootstrap': False,
    }
    held_fd = None
    if blocker == 'held-lock':
        held_fd = os.open(marker, os.O_RDWR)
        fcntl.flock(held_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with pytest.raises(PostgresDeployError):
            supervisor.request(request)
    finally:
        if held_fd is not None:
            os.close(held_fd)

    assert (journal.directory / 'test.json').read_bytes() == before['journal']
    assert (journal.directory / 'test.request.json').read_bytes() == before['request']
    assert marker.read_bytes() == before['marker']
    assert pin.read_bytes() == before['pin']
    assert migration_marker.read_bytes() == before['migration']
    assert data.read_bytes() == before['data']
    assert lock_dir.is_dir()


def test_host_reconciles_matching_failed_bws_deploy_receipt(monkeypatch, tmp_path):
    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController
    from app.ops.postgres_deploy import DeployReceipt, PostgresDeployError

    controller = HostSecretController(tmp_path / 'controller')
    with controller.deploy_operation('test', allow_bootstrap=False) as (operation, resumed):
        assert not resumed
        operation_id = operation.operation_id
        operation.prepare_mutation()
    captured = []
    ordinary_retries = []

    class Admin:
        def __init__(self, _provider, *, controller):
            self.controller = controller

        def check_selected(self, *_args):
            return []

    class Remote:
        def __init__(self, hostname):
            assert hostname == 'ygg-test'

        def prepare(self, selected_id, plan, bootstrap):
            assert selected_id == operation_id
            assert plan.revision == 'a' * 40
            assert bootstrap is False
            ordinary_retries.append(selected_id)
            # Models refusal while the remote failed receipt still owns its lock.
            raise PostgresDeployError()

        def reconcile_failed(self, selected_id, plan):
            assert selected_id == operation_id
            assert plan.revision == 'a' * 40
            captured.append(selected_id)
            return DeployReceipt(selected_id, 'test', 'deploy', 'failed', 'failed')

    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, 'SshDeployRemote', Remote)
    monkeypatch.setattr(host, 'configured_admin', lambda: object())
    monkeypatch.setattr(host, 'SecretAdmin', Admin)

    assert host.main(['dev', 'a' * 40, '--existing-secrets-only', '--reconcile-pending']) == 78
    assert captured == []
    with controller._locked_journal() as descriptor:
        still_pending = controller._pending(descriptor)
    assert still_pending is not None and still_pending['operation_id'] == operation_id

    assert host.main(['test', 'a' * 40, '--existing-secrets-only']) == 78
    assert ordinary_retries == [operation_id]
    with controller._locked_journal() as descriptor:
        still_pending = controller._pending(descriptor)
    assert still_pending is not None and still_pending['operation_id'] == operation_id

    assert host.main(['test', 'a' * 40, '--existing-secrets-only', '--reconcile-pending']) == 0
    assert captured == [operation_id]
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None


def test_ssh_reconcile_failed_sends_exact_same_id_and_existing_secrets_mode(monkeypatch):
    import json
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployPlan

    operation_id = str(uuid4())
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',), True)
    response = {
        'receipt': {
            'operation_id': operation_id, 'channel': 'test', 'kind': 'deploy',
            'stage': 'failed', 'terminal_result': 'failed',
        }
    }
    calls = []

    def ssh(argv, **kwargs):
        calls.append((argv, json.loads(kwargs['input'])))
        return SimpleNamespace(returncode=0, stdout=json.dumps(response))

    monkeypatch.setattr(linux.subprocess, 'run', ssh)
    receipt = linux.SshDeployRemote('ygg-test').reconcile_failed(operation_id, plan)

    assert receipt.operation_id == operation_id
    assert receipt.terminal_result == 'failed'
    assert calls[0][1] == {
        'action': 'reconcile-failed', 'operation_id': operation_id,
        'plan': {
            'channel': 'test', 'revision': 'a' * 40,
            'services': ['db'], 'consumers': ['postgres-db'],
            'ack_forward_only': True,
        },
        'bootstrap': False,
    }


def test_vm_channel_lock_is_retained_until_matching_terminal_receipt(tmp_path):
    from types import SimpleNamespace
    from app.ops.postgres_deploy_linux import LinuxEffects
    _, journal, _, identifier = _bws_worker(tmp_path, _BwsVmEffects())
    root = tmp_path / 'checkout'
    (root / 'config/deploy').mkdir(parents=True)
    cfg = SimpleNamespace(root=root, channel='test', journal=journal)
    effects = LinuxEffects(cfg)
    effects.operation_id = identifier
    journal.write(identifier, 'prepared')
    with effects.channel_lock():
        assert effects.lock_fd is not None
    lock = root / 'config/deploy/test.env.lock'
    assert lock.is_dir()
    with pytest.raises(FileExistsError):
        with effects.channel_lock():
            pytest.fail('a pending predecessor cannot be replaced')
    # Model the only allowed cleanup path: terminal evidence while owner holds it.
    other = tmp_path / 'other'
    (other / 'config/deploy').mkdir(parents=True)
    cfg.root = other
    with effects.channel_lock():
        journal.write(identifier, 'aborted')
    assert not (other / 'config/deploy/test.env.lock').exists()


def test_deploy_does_not_create_plaintext_postgres_env_file(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployPlan
    _, journal, _, identifier = _bws_worker(tmp_path, _BwsVmEffects())
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(identifier, stage)
    source = tmp_path / 'tmpfs'
    source.mkdir()
    cfg = SimpleNamespace(channel='test', journal=journal, source_directory=source, root=tmp_path)
    effects = linux.LinuxEffects(cfg)
    effects.lock_fd = 123
    effects.source = SimpleNamespace(verify=lambda: None)
    effects.environment = lambda: {'HOST_SECRET_PROVIDER': 'bws'}
    effects.consumer_values = {'heimdal-api-ingress': {}, 'heimdal-capture-watch': {}, 'heimdal-raw-migrate': {}}
    effects.active_consumers = (*DATABASE_CONSUMERS, 'heimdal-api-ingress',
                                'heimdal-capture-watch', 'heimdal-raw-migrate')
    plan = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()), tuple(DATABASE_CONSUMERS))
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        assert kwargs['pass_fds'] == (123,)
        for name, value in kwargs['env'].items():
            assert 'PASSWORD' not in name
            assert 'canary' not in value
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in source.iterdir())
        assert all(path.read_text() == '' for path in source.iterdir())
        return ''
    monkeypatch.setattr(linux, '_command', command)
    effects.activate(plan)
    assert len(calls) == 1
    assert list(source.iterdir()) == []


def test_bws_candidate_and_rollback_images_require_file_resolver_protocol(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError
    calls = []
    def command(argv, **kwargs):
        calls.append(argv)
        return 'DATABASE_FILE_CREDENTIAL_PROTOCOL = 1\n' if argv[-1].startswith('a' * 40) else 'legacy = True\n'
    monkeypatch.setattr(linux, '_command', command)
    linux.require_file_protocol(tmp_path, 'a' * 40)
    with pytest.raises(PostgresDeployError):
        linux.require_file_protocol(tmp_path, 'b' * 40)
    with pytest.raises(PostgresDeployError):
        linux.require_file_protocol(tmp_path, '--unsafe')
    assert len(calls) == 2
    assert all(call[:4] == ['git', '-C', str(tmp_path), 'show'] for call in calls)


@pytest.mark.parametrize('source', ['DATABASE_URL', 'DB_DSN', 'both', 'runtime', 'pin'])
@pytest.mark.parametrize('host', ['db', 'database.example.invalid'])
def test_linux_effects_authenticates_effective_compose_connection(tmp_path, monkeypatch, source, host):
    from app.ops import postgres_deploy_linux as linux
    from app.config.database import credential_free_database_fields
    from app.ops.postgres_deploy import PostgresDeployError
    cfg = linux.LinuxConfig('test', tmp_path, tmp_path / 'data', 1000, 1000, '', '')
    (tmp_path / 'config/deploy').mkdir(parents=True)
    pin = tmp_path / 'config/deploy/test.env'
    pin.write_text('APP_IMAGE_TAG=' + 'a' * 40 + '\n')
    for name in ('DATABASE_URL', 'DB_DSN', 'POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'):
        monkeypatch.delenv(name, raising=False)
    override = f'postgresql://reporter@{host}:5432/custom?sslmode=verify-full&application_name=bound-probe'
    if source == 'runtime':
        (tmp_path / 'tmp-test').mkdir()
        (tmp_path / 'tmp-test/runtime.env').write_text('DB_DSN=' + override + '\n')
    elif source == 'pin':
        with pin.open('a') as stream:
            stream.write('DB_DSN=' + override + '\n')
    else:
        monkeypatch.setenv('DB_DSN' if source == 'DB_DSN' else 'DATABASE_URL', override)
        if source == 'both':
            monkeypatch.setenv('DB_DSN', 'postgresql://ignored@ignored.example.invalid/ignored')
    proofs, compose_environments = [], []
    monkeypatch.setattr(linux, 'password_authenticate', lambda env: proofs.append(env))
    def command(argv, **kwargs):
        compose_environments.append(kwargs['env'])
        return ''
    monkeypatch.setattr(linux, '_command', command)
    effects = linux.LinuxEffects(cfg)
    effects.authenticate()
    effects.compose('config', '--format', 'json')
    runtime = credential_free_database_fields(compose_environments[0]['DATABASE_URL'])
    assert compose_environments[0]['DATABASE_URL'] == compose_environments[0]['DB_DSN']
    assert runtime == {'user': 'reporter', 'dbname': 'custom', 'host': host, 'port': '5432',
                       'sslmode': 'verify-full', 'application_name': 'bound-probe'}
    authenticated = credential_free_database_fields(proofs[0]['DATABASE_URL'])
    expected = dict(runtime)
    if host == 'db':
        expected.update(hostaddr='127.0.0.1', port='15434')
    assert authenticated == expected
    assert proofs[0]['DATABASE_PASSWORD_FILE'] == str(cfg.password_file)
    # An effective-target change during the operation cannot borrow prior proof.
    monkeypatch.setenv('DATABASE_URL', 'postgresql://other@other.example.invalid/other')
    with pytest.raises(PostgresDeployError):
        effects.compose('up', '-d', 'api')
    assert len(compose_environments) == 1


@pytest.mark.parametrize('channel', ['dev', 'test', 'prod'])
@pytest.mark.parametrize('reject_recheck', [False, True])
def test_bws_full_deploy_raw_migration_uses_supervised_preflight(tmp_path, channel, reject_recheck):
    root, env, _ = _deploy_harness(tmp_path)
    target = _commit_har_raw_migration(root, 'e7b4c9d2a6f1_heimdal_raw_representation.py')
    env.update(FAKE_SHA=target, DEPLOY_ACK_FORWARD_ONLY='1', HOST_SECRET_PROVIDER='bws', BWS_DATABASE_TARGET='local',
               FAKE_SECURITY_EVENT_LOG=env['FAKE_DEPLOY_EVENT_LOG'])
    _set_bws_consumer_selection(env, raw_migration=True)
    _configure_successful_channel_preflights(root, env, tmp_path, channel=channel)
    if channel == 'prod':
        _configure_bws_retry_driver(tmp_path, env)
    # Fake only the VM credential/FD adapter; run the actual deployment shell and
    # its real pending-HAR classification, pin/migration and Compose branches.
    (root / 'app/ops/postgres_deploy_linux.py').write_text('''
import os,sys
from pathlib import Path
assert sys.argv[1] == 'guard'
log = Path(os.environ['FAKE_DEPLOY_EVENT_LOG'])
prior = log.read_text().count('bws-guard') if log.exists() else 0
with log.open('a') as stream:
    stream.write('bws-guard\\n')
if os.environ.get('FAKE_BWS_REJECT_RECHECK') == '1' and prior == 1:
    raise SystemExit(78)
''')
    handle = tmp_path / 'migration.env'
    handle.write_text('HEIMDAL_RAW_STORE_KEY=' + 'a' * 64 + '\n')
    handle.chmod(0o600)
    env['BWS_MIGRATE_SECRET_ENV_FILE'] = str(handle)
    if reject_recheck:
        env['FAKE_BWS_REJECT_RECHECK'] = '1'
    result = _run_deploy(root, env, target, channel=channel)
    events = _deploy_events(env)
    assert not any(event.startswith('security ') for event in events)
    assert events.count('bws-guard') >= 2
    if reject_recheck:
        assert result.returncode == 78
        assert not any(event.startswith('docker ') for event in events)
        assert 'active secret consumer preflight failed: output=redacted' in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        second_guard = [i for i, event in enumerate(events) if event == 'bws-guard'][1]
        first_docker = next(i for i, event in enumerate(events) if event.startswith('docker '))
        assert second_guard < first_docker
        assert any('exit-code-from migrate' in event for event in events)


@pytest.mark.parametrize('host,empty,authenticated,blocked_key', [
    ('db', False, False, None), ('db', True, False, None),
    ('database.example.invalid', True, False, None), ('database.example.invalid', True, True, None),
    ('127.0.0.2', True, True, 'host'), ('127.0.0.2', True, True, 'hostaddr'),
    ('::ffff:127.0.0.2', True, True, 'host'), ('::ffff:127.0.0.2', True, True, 'hostaddr'),
    ("host=@ygg-review dbname=app_test", True, True, 'dsn'),
    ("host='' dbname=app_test", True, True, 'dsn'),
    ("dbname=app_test", True, True, 'dsn'),
    ("postgresql:///app_test", True, True, 'dsn'),
    ("postgresql:///?host=", True, True, 'dsn'),
    ("postgresql:///?host=%40ygg-review", True, True, 'dsn'),
])
def test_linux_effects_wrong_overridden_role_cannot_borrow_default_role_proof(tmp_path, monkeypatch, host, empty, authenticated, blocked_key):
    from types import SimpleNamespace
    from uuid import uuid4
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, DeployWorker
    for key in ('DATABASE_URL', 'DB_DSN', 'POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'):
        monkeypatch.delenv(key, raising=False)
    from urllib.parse import urlencode
    fields = {'host': host, 'user': 'not-the-default-role', 'port': '5432', 'dbname': 'app_test', 'sslmode': 'require'}
    if blocked_key == 'hostaddr':
        fields.update(host='database.example.invalid', hostaddr=host)
    monkeypatch.setenv('DB_DSN', host if blocked_key == 'dsn' else 'postgresql:///?' + urlencode(fields))
    (tmp_path / 'config/deploy').mkdir(parents=True)
    (tmp_path / 'config/deploy/test.env').write_text('APP_IMAGE_TAG=' + 'a' * 40 + '\n')
    data = tmp_path / 'data'
    data.mkdir()
    if not empty:
        (data / 'PG_VERSION').write_text('16')
    source = tmp_path / 'tmpfs'
    source.mkdir()
    journal = DeployJournal(tmp_path / 'journal', 'test')
    cfg = SimpleNamespace(channel='test', root=tmp_path, data_directory=data, uid=1000, gid=1000,
                          password_file=source / 'password', source_directory=source, journal=journal,
                          reader=lambda: None)
    plan = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'))
    monkeypatch.setattr(linux, 'vm_selected_values', lambda selected, reader:
                        {name: {'postgres.password': 'fake-role-canary'} if name in DATABASE_CONSUMERS else {}
                         for name in selected.consumers})
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _cfg: False)
    monkeypatch.setattr(linux, '_raw_representation_migration_pending', lambda *_args: False)
    commands, connections = [], []
    def command(argv, **kwargs):
        commands.append(argv)
        if argv[0] == 'git':
            return 'DATABASE_FILE_CREDENTIAL_PROTOCOL = 1\n'
        if argv[1:3] == ['volume', 'inspect']:
            return str(data)
        return ''
    monkeypatch.setattr(linux, '_command', command)
    class Connection:
        pgconn = SimpleNamespace(used_password=True)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def cursor(self): return self
        def execute(self, sql): assert sql == 'SELECT 1'
        def fetchone(self): return (1,)
    def connect(dsn, **kwargs):
        fields = conninfo_to_dict(dsn)
        connections.append(fields)
        if fields['user'] != 'app' and not authenticated:
            raise RuntimeError('fake-role-canary')
        return Connection()
    monkeypatch.setattr(psycopg, 'connect', connect)
    effects = linux.LinuxEffects(cfg)
    effects.lock_fd = 123
    effects.source = SimpleNamespace(materialize=lambda value: cfg.password_file.write_text(value), verify=lambda: None)
    activations = []
    effects.activate = lambda selected: activations.append(selected)
    # Actual production initialized() must not offer bootstrap for this target,
    # even though the selected local volume may be genuinely empty.
    assert effects.initialized() is True
    receipt = DeployWorker(journal, effects).run(str(uuid4()), plan)
    if blocked_key:
        # A host-loopback server would accept this password, but that says
        # nothing about the same address inside the workers' network namespace.
        assert receipt.stage == 'aborted'
        assert not connections and not activations
        assert not any(command[-2:] in (['--no-deps', 'db'], ['stop', 'db']) for command in commands)
        assert not any('deploy_channel.sh' in ' '.join(command) for command in commands)
        assert not any(command[1:3] == ['volume', 'inspect'] for command in commands)
        assert (tmp_path / 'config/deploy/test.env').read_text() == 'APP_IMAGE_TAG=' + 'a' * 40 + '\n'
        return
    assert receipt.stage == ('committed' if authenticated else 'aborted')
    expected = {'user': 'not-the-default-role', 'password': 'fake-role-canary', 'dbname': 'app_test',
                'host': host, 'port': '5432', 'sslmode': 'require'}
    if host == 'db':
        expected.update(hostaddr='127.0.0.1', port='15434')
    assert connections == [expected]
    assert bool(activations) is authenticated
    if host == 'db':
        assert any(command[-2:] == ['--no-deps', 'db'] for command in commands)
        assert any(command[-2:] == ['stop', 'db'] for command in commands)
    else:
        assert not any(command[-2:] in (['--no-deps', 'db'], ['stop', 'db']) for command in commands)
        assert not any(command[1:3] == ['volume', 'inspect'] for command in commands)
    assert not any('deploy_channel.sh' in ' '.join(command) for command in commands)

    # Exercise the real supervisor bootstrap admission, not a fake empty flag.
    monkeypatch.setattr('app.ops.host_secret_bootstrap._resolve_bws_consumer_values', lambda *args: {})
    operation = linux.SupervisedOperation(effects, str(uuid4()), plan, True)
    with pytest.raises(linux.PostgresDeployError):
        operation._run_locked()
    assert not operation.ready.is_set()
    assert operation.empty is False


@pytest.mark.parametrize('host', ['db', 'database.example.invalid'])
@pytest.mark.parametrize('failure', ['terminal_rows', 'password_file', 'unreachable', 'query_unavailable'])
def test_bws_prod_retry_preflight_uses_file_connection_and_preserves_availability_policy(tmp_path, host, failure):
    root, env, target = _deploy_harness(tmp_path)
    env.update(FAKE_SHA=target, HOST_SECRET_PROVIDER='bws')
    _set_bws_consumer_selection(env, raw_migration=False)
    _configure_prod_retry_preflight(root, env, tmp_path,
        rows=[('panel.scan.requested', {'_worker_retry_count': 3}, 0)],
        unreachable=failure == 'unreachable')
    _configure_bws_retry_driver(tmp_path, env, host=host)
    if failure == 'password_file':
        Path(env['BWS_POSTGRES_PASSWORD_SOURCE']).unlink()
    if failure == 'query_unavailable':
        env['FAKE_OUTBOX_QUERY_UNAVAILABLE'] = '1'
    # Only the external worker credential/lock seam is fake. The shell, real
    # preflight/resolver, libpq parser and terminal-row classifier all run.
    (root / 'app/ops/postgres_deploy_linux.py').write_text('import sys\nassert sys.argv[1] == "guard"\n')
    pin = root / 'config/deploy/prod.env'
    before = pin.read_bytes() if pin.exists() else None
    result = _run_deploy(root, env, target, channel='prod')
    if failure in {'unreachable', 'query_unavailable'}:
        # #3903 intentionally allows a genuine outage/absent initial schema;
        # malformed DSNs must never enter this driver-error policy by mistake.
        assert result.returncode == 0, result.stdout + result.stderr
        reason = 'db_unreachable' if failure == 'unreachable' else 'outbox_query_failed'
        assert 'skipped:' + reason in result.stdout + result.stderr
        assert Path(env['FAKE_OUTBOX_CONNECT_LOG']).read_text() == 'validated-file-connection\n'
        return
    assert result.returncode == 87, result.stdout + result.stderr
    assert (pin.read_bytes() if pin.exists() else None) == before
    assert not any(event.startswith('docker ') for event in _deploy_events(env))
    assert 'fake-preflight-canary' not in result.stdout + result.stderr
    assert 'skipped:' not in result.stdout + result.stderr
    if failure == 'terminal_rows':
        assert 'terminal_pending_count=1' in result.stdout + result.stderr
        assert Path(env['FAKE_OUTBOX_CONNECT_LOG']).read_text() == 'validated-file-connection\n'
    elif failure == 'password_file':
        assert not Path(env['FAKE_OUTBOX_CONNECT_LOG']).exists()


@pytest.mark.parametrize('channel', ['dev', 'test', 'prod'])
def test_linux_effects_empty_proof_is_bound_to_default_local_initialization(tmp_path, monkeypatch, channel):
    from app.ops import postgres_deploy_linux as linux
    for key in ('DATABASE_URL', 'DB_DSN', 'POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / 'config/deploy').mkdir(parents=True)
    (tmp_path / 'config/deploy' / (channel + '.env')).write_text('APP_IMAGE_TAG=' + 'a' * 40 + '\n')
    data = tmp_path / 'data'
    data.mkdir()
    cfg = linux.LinuxConfig(channel, tmp_path, data, 1000, 1000, '', '')
    monkeypatch.setattr(linux, '_command', lambda argv, **kwargs:
                        str(data) if argv[1:3] == ['volume', 'inspect'] else '')
    effects = linux.LinuxEffects(cfg)
    assert effects.local_database() is True
    assert effects.initialized() is False
    (data / 'PG_VERSION').write_text('16')
    assert effects.initialized() is True


@pytest.mark.parametrize('host,target,profiles,accepted', [
    ('db', 'local', '', True), ('database.example.invalid', 'external', '', True),
    ('db', 'external', '', False), ('database.example.invalid', 'local', '', False),
    ('database.example.invalid', '', '', False),
    ('database.example.invalid', 'external', 'bws-local-database-disabled', False),
])
def test_bws_worker_guard_binds_compose_target_before_provider_access(tmp_path, monkeypatch, host, target, profiles, accepted):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError
    directory = tmp_path / 'config/deploy'
    directory.mkdir(parents=True)
    (directory / 'test.env').write_text('APP_IMAGE_TAG=' + 'a' * 40 + '\n')
    lock = directory / 'test.env.lock'
    lock.mkdir()
    password = tmp_path / 'password'
    password.write_text('fake-target-binding-password')
    runtime_env_file = tmp_path / 'runtime.env'
    runtime_env_file.write_text('LLM_PROVIDER=mock\n', encoding='utf-8')
    cfg = SimpleNamespace(root=tmp_path, channel='test', password_file=password,
                          runtime_env_file=runtime_env_file,
                          reader=lambda: object(), journal=SimpleNamespace(read=lambda:
                          SimpleNamespace(stage='activating', operation_id='operation')))
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda channel: cfg)
    reads = []
    monkeypatch.setattr(linux.PasswordSource, 'verify', lambda self: reads.append('source'))
    monkeypatch.setattr(linux, 'vm_selected_values', lambda *args:
                        {'postgres-db': {'postgres.password': password.read_text()}})
    monkeypatch.setattr(linux, 'require_file_protocol', lambda *args: None)
    with (lock / 'bws-owner').open('w+') as owner:
        monkeypatch.setattr(os, 'environ', {'DATABASE_URL': 'postgresql://app@' + host + ':5432/app_test',
            'BWS_DEPLOY_LOCK_FD': str(owner.fileno()), 'BWS_DEPLOY_OPERATION_ID': 'operation',
            'BWS_DEPLOY_RUNTIME_ENV_FILE': str(runtime_env_file),
            'BWS_DATABASE_TARGET': target, 'COMPOSE_PROFILES': profiles,
            'BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED': '0',
            'BWS_EXPECTED_RAW_MIGRATION_PENDING': '0',
            'BWS_DEPLOY_TARGET_REVISION': 'a' * 40,
            'DEPLOY_HEIMDAL_RAW_MIGRATION_PENDING': '0'})
        if accepted:
            linux.inherited_worker_guard('test', 'up')
            assert reads == ['source']
        else:
            with pytest.raises(PostgresDeployError):
                linux.inherited_worker_guard('test', 'up')
            assert not reads


@pytest.mark.parametrize('key', ['host', 'hostaddr'])
@pytest.mark.parametrize('address', ['127.0.0.2', '::ffff:127.0.0.2'])
def test_bws_prod_preflight_rejects_container_loopback_before_driver(tmp_path, key, address):
    from urllib.parse import urlencode
    root, env, target = _deploy_harness(tmp_path)
    env.update(FAKE_SHA=target, HOST_SECRET_PROVIDER='bws')
    _set_bws_consumer_selection(env, raw_migration=False)
    _configure_prod_retry_preflight(root, env, tmp_path, rows=[])
    _configure_bws_retry_driver(tmp_path, env)
    fields = {'host': 'database.example.invalid', 'port': '5432', 'user': 'reporter', 'dbname': 'custom', key: address}
    env['DATABASE_URL'] = env['DB_DSN'] = 'postgresql:///?' + urlencode(fields)
    (root / 'app/ops/postgres_deploy_linux.py').write_text('import sys\nassert sys.argv[1] == "guard"\n')
    result = _run_deploy(root, env, target, channel='prod')
    assert result.returncode == 87, result.stdout + result.stderr
    assert 'credential_configuration' in result.stderr
    assert not Path(env['FAKE_OUTBOX_CONNECT_LOG']).exists()
    assert not (root / 'config/deploy/prod.env').exists()
    assert not any(event.startswith('docker ') for event in _deploy_events(env))
    assert 'fake-preflight-canary' not in result.stdout + result.stderr


@pytest.mark.parametrize('dsn', [
    "host=@ygg-review dbname=app_test", "host='' dbname=app_test", "dbname=app_test",
    "postgresql:///app_test", "postgresql:///?host=", "postgresql:///?host=%40ygg-review",
])
def test_bws_prod_preflight_rejects_libpq_socket_and_default_targets_before_driver(tmp_path, dsn):
    root, env, target = _deploy_harness(tmp_path)
    env.update(FAKE_SHA=target, HOST_SECRET_PROVIDER='bws')
    _set_bws_consumer_selection(env, raw_migration=False)
    _configure_prod_retry_preflight(root, env, tmp_path, rows=[])
    _configure_bws_retry_driver(tmp_path, env)
    env['DATABASE_URL'] = env['DB_DSN'] = dsn
    (root / 'app/ops/postgres_deploy_linux.py').write_text('import sys\nassert sys.argv[1] == "guard"\n')
    result = _run_deploy(root, env, target, channel='prod')
    assert result.returncode == 87, result.stdout + result.stderr
    assert 'credential_configuration' in result.stderr
    assert not Path(env['FAKE_OUTBOX_CONNECT_LOG']).exists()
    assert not (root / 'config/deploy/prod.env').exists()
    assert not any(event.startswith('docker ') for event in _deploy_events(env))
    assert 'fake-preflight-canary' not in result.stdout + result.stderr


def _install_bws_identity_guard_fixture(root: Path) -> None:
    (root / "app/ops/postgres_deploy_linux.py").write_text(
        "import os, sys\n"
        "assert sys.argv[1] == 'guard'\n"
        "with open(os.environ['FAKE_DEPLOY_EVENT_LOG'], 'a') as stream:\n"
        "    stream.write('bws-guard\\n')\n",
        encoding="utf-8",
    )


def test_runtime_identity_from_runtime_env_is_used_before_instance_state_init(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    runtime_uid = os.getuid()
    runtime_gid = os.getgid()
    inherited_uid = "0" if runtime_uid != 0 else "1"
    inherited_gid = "0" if runtime_gid != 0 else "1"
    (root / "tmp/runtime.env").write_text(
        f"LOCAL_UID={runtime_uid}\nLOCAL_GID={runtime_gid}\nTTS_ENABLED=false\n",
        encoding="utf-8",
    )
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(f"APP_IMAGE_TAG={sha}\n", encoding="utf-8")
    _install_bws_identity_guard_fixture(root)
    env.update(
        FAKE_SHA=sha,
        FAKE_CAPTURE_RUNTIME_IDENTITY="1",
        HOST_SECRET_PROVIDER="bws",
        BWS_DATABASE_TARGET="local",
        BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED="0",
        BWS_EXPECTED_RAW_MIGRATION_PENDING="0",
        LOCAL_UID=inherited_uid,
        LOCAL_GID=inherited_gid,
    )

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    identity_events = [event for event in events if event.startswith("compose identity ")]
    assert identity_events
    assert all(f"uid={runtime_uid} gid={runtime_gid}" in event for event in identity_events)
    assert any("instance-state-init" in event for event in identity_events)
    assert not any(
        f"uid={inherited_uid} gid={inherited_gid}" in event for event in identity_events
    )


def test_root_bws_deploy_accepts_runtime_owned_host_state_before_mutation(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    test_root = runtime_reachable_test_root(tmp_path, request)
    root, env, sha = _deploy_harness(test_root)
    actual_root = os.geteuid() == 0
    runtime_uid = 65534 if actual_root else os.getuid()
    runtime_gid = 65534 if actual_root else os.getgid()
    (root / "tmp/runtime.env").write_text(
        f"LOCAL_UID={runtime_uid}\nLOCAL_GID={runtime_gid}\nTTS_ENABLED=false\n",
        encoding="utf-8",
    )
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(f"APP_IMAGE_TAG={sha}\n", encoding="utf-8")
    ownership = Path(env["INSTANCE_OWNERSHIP_HOST_STATE_DIR"])
    ownership.mkdir(mode=0o700)
    if actual_root:
        os.chown(ownership, runtime_uid, runtime_gid)
    ledger = ownership / "ownership-ledger.json"
    ledger.write_text("existing-runtime-ledger\n", encoding="utf-8")
    ledger.chmod(0o600)
    if actual_root:
        os.chown(ledger, runtime_uid, runtime_gid)

    # The production helper reads its shell caller identity through `id`.
    # Reporting the BWS root supervisor here exercises that branch while its
    # embedded Python still runs as this fixture's runtime UID/GID.
    fake_id = Path(env["PATH"].split(os.pathsep)[0]) / "id"
    fake_id.write_text(
        "#!/usr/bin/env bash\n"
        'case "${1:-}" in\n'
        '  -u) printf "host-state-identity\\n" >> "${FAKE_DEPLOY_EVENT_LOG:?}"; printf "0\\n" ;;\n'
        f'  -g) printf "{runtime_gid}\\n" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_id.chmod(0o755)
    _install_bws_identity_guard_fixture(root)
    env.update(
        FAKE_SHA=sha,
        FAKE_CAPTURE_RUNTIME_IDENTITY="1",
        HOST_SECRET_PROVIDER="bws",
        BWS_DATABASE_TARGET="local",
        BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED="0",
        BWS_EXPECTED_RAW_MIGRATION_PENDING="0",
        LOCAL_UID=str(runtime_uid),
        LOCAL_GID=str(runtime_gid),
    )

    result = _run_deploy(root, env, sha)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    assert "host-state-identity" in events
    assert "bws-guard" in events
    assert any("instance-state-init" in event for event in events)
    assert pin_path.is_file()
    assert ledger.read_text(encoding="utf-8") == "existing-runtime-ledger\n"
    ledger_metadata = ledger.stat()
    assert ledger_metadata.st_uid == runtime_uid
    assert ledger_metadata.st_gid == runtime_gid
    assert ledger_metadata.st_mode & 0o777 == 0o600
    ownership_metadata = ownership.stat()
    assert ownership_metadata.st_uid == runtime_uid
    assert ownership_metadata.st_gid == runtime_gid
    assert ownership_metadata.st_mode & 0o777 == 0o700

    # A later rollback reader must accept a private receipt owned by the
    # configured runtime even though the deployment shell represents root.
    floor_receipt = ownership / "settings-rebind-runtime-floor-dev.json"
    floor_receipt.write_text(
        '{"channel":"dev","minimum_settings_rebind_runtime":"1",'
        '"phase":"pending","schema":"agentic-pkm.settings-rebind-runtime-floor.v1"}\n',
        encoding="utf-8",
    )
    floor_receipt.chmod(0o600)
    if actual_root:
        os.chown(floor_receipt, runtime_uid, runtime_gid)
    original_pin = pin_path.read_text(encoding="utf-8")
    Path(env["FAKE_DEPLOY_EVENT_LOG"]).write_text("", encoding="utf-8")

    rollback = _run_rollback(root, env, sha)

    assert rollback.returncode == 78
    assert "settings rebind floor installation is pending" in rollback.stderr
    assert pin_path.read_text(encoding="utf-8") == original_pin
    assert not any(event.startswith("docker ") for event in _deploy_events(env))
    receipt_metadata = floor_receipt.stat()
    assert receipt_metadata.st_uid == runtime_uid
    assert receipt_metadata.st_gid == runtime_gid
    assert receipt_metadata.st_mode & 0o777 == 0o600
    if actual_root:
        runtime_read = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())",
                str(floor_receipt),
            ],
            user=runtime_uid,
            group=runtime_gid,
            extra_groups=[],
            capture_output=True,
            text=True,
            check=False,
        )
        assert runtime_read.returncode == 0, runtime_read.stderr
        assert '"phase":"pending"' in runtime_read.stdout

        # Preserve rollback from a durable receipt written by the old root
        # supervisor; new receipts above are still runtime-owned.
        floor_receipt.unlink()
        floor_receipt.write_text(
            '{"channel":"dev","minimum_settings_rebind_runtime":"1",'
            '"phase":"pending","schema":"agentic-pkm.settings-rebind-runtime-floor.v1"}\n',
            encoding="utf-8",
        )
        floor_receipt.chmod(0o600)
        assert floor_receipt.stat().st_uid == 0
        assert floor_receipt.stat().st_gid == 0
        Path(env["FAKE_DEPLOY_EVENT_LOG"]).write_text("", encoding="utf-8")

        legacy_receipt_rollback = _run_rollback(root, env, sha)

        assert legacy_receipt_rollback.returncode == 78
        assert "settings rebind floor installation is pending" in legacy_receipt_rollback.stderr
        assert pin_path.read_text(encoding="utf-8") == original_pin
        assert not any(
            event.startswith("docker ") for event in _deploy_events(env)
        )


@pytest.mark.parametrize(
    ("runtime_env", "provider", "expected_returncode"),
    [
        ("TTS_ENABLED=false\n", "bws", 78),
        ("LOCAL_UID=1000\n", "bws", 78),
        ("LOCAL_UID=1000\nLOCAL_GID=1001\nLOCAL_UID=1002\n", "bws", 78),
        ("LOCAL_UID=bad\nLOCAL_GID=1001\n", "bws", 78),
        ("LOCAL_UID=0\nLOCAL_GID=1001\n", "bws", 78),
        ("LOCAL_UID=1000\nLOCAL_GID=0\n", "bws", 78),
        ("LOCAL_UID=0000\nLOCAL_GID=1001\n", "bws", 78),
        ("LOCAL_UID=4294967295\nLOCAL_GID=1001\n", "bws", 78),
        ("LOCAL_UID=1000\nLOCAL_GID=4294967296\n", "bws", 78),
        ("TTS_ENABLED=false\n", "keychain", 0),
    ],
)
def test_bws_runtime_identity_preflight_fails_before_mutation(
    tmp_path: Path,
    runtime_env: str,
    provider: str,
    expected_returncode: int,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    (root / "tmp/runtime.env").write_text(runtime_env, encoding="utf-8")
    pin_path = root / "config/deploy/dev.env"
    original_pin = f"APP_IMAGE_TAG={sha}\n"
    pin_path.write_text(original_pin, encoding="utf-8")
    env.update(
        FAKE_SHA=sha,
        FAKE_CAPTURE_RUNTIME_IDENTITY="1",
        HOST_SECRET_PROVIDER=provider,
        LOCAL_UID="0",
        LOCAL_GID="0",
    )
    if provider == "bws":
        _install_bws_identity_guard_fixture(root)
        env.update(
            BWS_DATABASE_TARGET="local",
            BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED="0",
            BWS_EXPECTED_RAW_MIGRATION_PENDING="0",
        )
    else:
        env.pop("LOCAL_UID", None)
        env.pop("LOCAL_GID", None)

    result = _run_deploy(root, env, sha)

    assert result.returncode == expected_returncode, result.stdout + result.stderr
    if provider == "bws":
        assert "runtime identity preflight: blocked reason=" in result.stderr
        assert pin_path.read_text(encoding="utf-8") == original_pin
        assert not any(event.startswith("docker ") for event in _deploy_events(env))
    else:
        assert "runtime identity preflight: blocked" not in result.stderr
        identity_events = [
            event for event in _deploy_events(env) if event.startswith("compose identity ")
        ]
        assert identity_events
        assert all(
            f"uid={os.getuid()} gid={os.getgid()}" in event
            for event in identity_events
        )


def test_runtime_identity_snapshot_change_is_rejected(tmp_path: Path) -> None:
    snapshot = tmp_path / "runtime.env"
    snapshot.write_text("LOCAL_UID=1001\nLOCAL_GID=1002\n", encoding="utf-8")
    script = REPO_ROOT / "scripts/lib/deploy_channel_compose.sh"
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; LOCAL_UID=1000; LOCAL_GID=1002; export LOCAL_UID LOCAL_GID; '
            'HOST_SECRET_PROVIDER=bws; '
            'if deploy_channel_runtime_identity_matches_snapshot "$2"; then exit 0; '
            'else rc=$?; test "$rc" -eq 78; fi; '
            'test "$LOCAL_UID" = 1000; test "$LOCAL_GID" = 1002',
            "runtime-identity-snapshot-test",
            str(script),
            str(snapshot),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime identity preflight: blocked reason=runtime_identity_changed" in result.stderr
