from __future__ import annotations

import os
import json
import errno
import hashlib
import socket
import subprocess
import sys
import tempfile
from contextlib import ExitStack, contextmanager
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
    # BWS deployment tests run the real shell preflight against the deterministic
    # Docker stub from the shared harness. The selected Product embedding
    # identity is Ollama in these fixtures, so provide only the strict identity
    # receipt the new preflight consumes; all other Compose commands already
    # succeed through the stub's normal default path.
    docker = Path(env["PATH"].split(os.pathsep)[0]) / "docker"
    docker_script = docker.read_text(encoding="utf-8")
    identity_stub = '''if [ "${FAKE_GENERIC_EMBEDDING_IDENTITY:-0}" = "1" ] && \
    [[ "$*" == *"native-source-embedding-identity.v1"* ]]; then
  printf '{"contract":"native-source-embedding-identity.v1","provider":"%s","model":"%s"}\\n' \\
    "${FAKE_EMBEDDING_PROVIDER:-ollama}" "${FAKE_EMBEDDING_MODEL:-nomic-embed-text:latest}"
  exit "${FAKE_EMBEDDING_IDENTITY_RC:-0}"
fi
'''
    case_marker = 'case "$*" in\n'
    assert case_marker in docker_script
    docker.write_text(
        docker_script.replace(case_marker, identity_stub + case_marker, 1),
        encoding="utf-8",
    )
    env["FAKE_GENERIC_EMBEDDING_IDENTITY"] = "1"
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
    assert (
        "production forward-only migration is pending; --ack-forward-only is required"
        in text
    )
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
    forward_only_probe = run_block.index("prepare_prod_forward_only_ack || exit")
    for preflight in (
        "heimdal_raw_migration_secret_preflight || exit $?",
        "scripts/companion_ui_postdeploy_smoke.sh preflight",
        "prod_devui_gateway_preflight",
        "prod_pending_retry_preflight || exit 87",
        "dev_test_environment_env_file_clobber_preflight || exit 90",
    ):
        assert run_block.index(preflight) < forward_only_probe
    assert forward_only_probe < run_block.index("prepare_instance_ownership_host_state_dir")
    assert forward_only_probe < run_block.index("ensure_prod_instance_state_volume")
    assert run_block.index("write_pin") < run_block.index("pull_channel_images")
    assert run_block.index("pull_channel_images") < run_block.index(
        "prepare_instance_state_deployment"
    )
    assert run_block.index("prepare_instance_state_deployment") < run_block.index(
        "migration execution failed"
    )
    assert run_block.index("pull_channel_images") < run_block.index(
        "native_source_embedding_preflight_gate"
    )
    assert run_block.index("native_source_embedding_preflight_gate") < run_block.index(
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
    assert '"$(mktemp "${file}.tmp.XXXXXX")" || return $?' in write_pin
    assert "awk -F=" in write_pin and "rc=$?" in write_pin
    assert write_pin.count('>>"${tmp_file}" || {') == 2


@pytest.mark.parametrize(("failing_command", "failure_status"), [("mktemp", 92), ("awk", 92), ("printf", 93)])
def test_pin_write_propagates_file_write_failures_inside_conditional_call(
    tmp_path: Path, failing_command: str, failure_status: int
) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    write_pin = "write_pin() {" + text.split("write_pin() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    pin_file = tmp_path / "channel.env"
    original_pin = "APP_IMAGE_REPOSITORY=example.invalid/current\nAPP_IMAGE_TAG=old\nKEEP=exact\n"
    pin_file.write_text(original_pin, encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    if failing_command != "printf":
        fake_command = fake_bin / failing_command
        fake_command.write_text(f"#!/usr/bin/env bash\nexit {failure_status}\n", encoding="utf-8")
        fake_command.chmod(0o755)
    harness = tmp_path / "write-pin-failure.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{write_pin}"
        + (
            "printf() { builtin printf \"$@\"; return 93; }\n"
            if failing_command == "printf"
            else ""
        )
        +
        "image_repository=example.invalid/target\n"
        f"pin_file={str(pin_file)!r}\n"
        "if write_pin \"${pin_file}\" new; then\n"
        "  echo 'write_pin reported success after awk failure' >&2\n"
        "  exit 99\n"
        "else\n"
        "  rc=$?\n"
        f"  [ \"${{rc}}\" -eq {failure_status} ] || exit 98\n"
        "fi\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(harness)],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert pin_file.read_text(encoding="utf-8") == original_pin
    assert not list(tmp_path.glob("channel.env.tmp.*"))


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
    full_run_block = run_block.split('elif [ "${activation_scope}" = text-capture ]; then', 1)[1].split('\nelse\n', 1)[1]
    assert run_block.index("recreate_channel_services") < run_block.index("health_gate")
    assert full_run_block.index("health_gate") < full_run_block.index("version_gate")


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
    full_run_block = run_block.split('elif [ "${activation_scope}" = text-capture ]; then', 1)[1].split('\nelse\n', 1)[1]
    assert full_run_block.index("health_gate") < full_run_block.index("version_gate")
    assert full_run_block.index("version_gate") < full_run_block.index("fleet_model_fitness_gate")
    assert full_run_block.index("fleet_model_fitness_gate") < full_run_block.index("record_receipt")


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
        'TTS_ENABLED=false\nHEIMDAL_CAPTURE_WATCH_DIR="   "\n',
        "TTS_ENABLED=false\nHEIMDAL_CAPTURE_WATCH_DIR=' \t '\n",
        'TTS_ENABLED=false\nHEIMDAL_CAPTURE_WATCH_DIR=" \t " # disabled\n',
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


@pytest.mark.parametrize("failure", ["malformed", "divergent"])
@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_raw_migration_production_wrapper_fails_before_compose_and_redacts(
    tmp_path: Path,
    failure: str,
    channel: str,
) -> None:
    """Present malformed or domain-divergent migration authority fails closed."""
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
    if failure == "malformed":
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


def _set_native_bws_operation_context(root: Path, env: dict[str, str]) -> None:
    api_handle = root / "tmp/api-consumer.env"
    api_handle.write_text("", encoding="utf-8")
    api_handle.chmod(0o600)
    env.update(
        HOST_SECRET_RUNTIME_ENV_FILE_API=str(api_handle),
        BWS_DEPLOY_OPERATION_ID="03b3bb2f-6d85-499a-8b45-e397f56812e1",
        BWS_DEPLOY_TARGET_REVISION=env["FAKE_SHA"],
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


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_automatic_deploy_preflights_forward_only_raw_migration(tmp_path: Path, channel: str) -> None:
    root, env, _sha = _deploy_harness(tmp_path)
    target = _commit_har_raw_migration(root, 'e7b4c9d2a6f1_heimdal_raw_representation.py')
    env['FAKE_SHA'] = target
    env['FAKE_SECURITY_EVENT_LOG'] = env['FAKE_DEPLOY_EVENT_LOG']
    _configure_successful_channel_preflights(root, env, tmp_path, channel=channel)
    pin = root / 'config/deploy' / (channel + '.env')
    digest = 'sha256:' + 'b' * 64
    result = _run_deploy(root, env, target, '--automatic', '--image-digest',
                         digest, channel=channel)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'APP_IMAGE_DIGEST_SUFFIX=@' + digest in pin.read_text()
    assert not (root / 'config/deploy' / (channel + '.migration-pending.env')).exists()
    events = _deploy_events(env)
    first_secret = events.index('security migrate-primary')
    first_docker = next(i for i, event in enumerate(events) if event.startswith('docker '))
    assert first_secret < first_docker
    receipt = json.loads((root / 'ops/deployments' / (channel + '-latest.json')).read_text())
    assert receipt['migration_receipt']['forward_only'] == ['e7b4c9d2a6f1_heimdal_raw_representation.py']
    assert receipt['migration_receipt']['ack_forward_only'] is False
    assert receipt['image_digest'] == digest and receipt['automatic'] is True


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_automatic_deploy_refuses_inherited_ack_with_empty_migration_delta(
    tmp_path: Path, channel: str,
) -> None:
    root, env, target = _deploy_harness(tmp_path)
    _configure_successful_channel_preflights(root, env, tmp_path, channel=channel)
    pin = root / 'config/deploy' / (channel + '.env')
    pin.write_text(f'APP_IMAGE_TAG={target}\n', encoding='utf-8')
    pin_before = pin.read_bytes()
    pending = root / 'config/deploy' / (channel + '.migration-pending.env')
    pending.write_text(
        f'FROM_SHA={target}\nTARGET_SHA={target}\nACK_FORWARD_ONLY=1\n',
        encoding='utf-8',
    )
    pending_before = pending.read_bytes()

    result = _run_deploy(
        root, env, target, '--automatic', '--image-digest', 'sha256:' + 'b' * 64,
        channel=channel,
    )

    assert result.returncode == 78, result.stdout + result.stderr
    assert 'refused inherited migration acknowledgement' in result.stderr
    assert pin.read_bytes() == pin_before
    assert pending.read_bytes() == pending_before
    assert not any(event.startswith('docker ') for event in _deploy_events(env))
    assert not (root / 'ops/deployments' / (channel + '-latest.json')).exists()


def test_automatic_deploy_preserves_digest_in_pin_receipt_and_recovery(tmp_path: Path) -> None:
    root, env, target = _deploy_harness(tmp_path)
    _configure_successful_channel_preflights(root, env, tmp_path, channel='dev')
    digest = 'sha256:' + 'b' * 64
    result = _run_deploy(root, env, target, '--automatic', '--image-digest', digest)
    assert result.returncode == 0, result.stdout + result.stderr
    pin = root / 'config/deploy/dev.env'
    assert 'APP_IMAGE_DIGEST_SUFFIX=@' + digest in pin.read_text()
    receipt = json.loads((root / 'ops/deployments/dev-latest.json').read_text())
    assert receipt['image'].endswith(':' + target + '@' + digest)
    assert receipt['image_digest'] == digest and receipt['automatic'] is True
    # Rebuilding the same SHA must retain the previous bytes for compensation.
    env['FAKE_POSTDEPLOY_SMOKE'] = 'fail'
    result = _run_deploy(root, env, target, '--automatic', '--image-digest', 'sha256:' + 'c' * 64)
    assert result.returncode != 0
    assert 'APP_IMAGE_DIGEST_SUFFIX=@' + digest in pin.read_text()
    previous = root / 'config/deploy/dev.previous.env'
    assert 'APP_IMAGE_DIGEST_SUFFIX=@' + digest in previous.read_text()


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
@pytest.mark.parametrize("failure", ["malformed", "divergent"])
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


def test_full_deploy_mixed_migration_inventory_allows_absent_key_to_reach_har02(
    tmp_path: Path,
) -> None:
    """An absent key does not preflight-block the governed HAR-02 invocation."""
    root, env, _initial_sha = _deploy_harness(tmp_path)
    _commit_migration(root, "unrelated_before_har.py")
    target = _commit_har_raw_migration(
        root,
        "e7b4c9d2a6f1_heimdal_raw_representation.py",
    )
    env["FAKE_SHA"] = target
    env["FAKE_SECURITY_MODE"] = "missing"
    env["FAKE_SECURITY_EVENT_LOG"] = env["FAKE_DEPLOY_EVENT_LOG"]
    _configure_successful_channel_preflights(
        root,
        env,
        tmp_path,
        channel="dev",
    )
    runtime_env = root / "tmp" / "runtime.env"
    runtime_env.write_text(
        runtime_env.read_text(encoding="utf-8").replace(
            "HEIMDAL_CAPTURE_WATCH_DIR=/fixture/capture-inbox",
            "HEIMDAL_CAPTURE_WATCH_DIR=",
        ),
        encoding="utf-8",
    )
    # Stop at a deliberate post-migration sentinel so this boundary test does
    # not depend on later runtime health/API fixture completeness.
    env["FAKE_DOCKER_FAIL_MATCH"] = "up -d --force-recreate api worker watcher companion-ui"

    result = _run_deploy(root, env, target, channel="dev")

    combined = result.stdout + result.stderr
    assert "service recreate/liveness gate failed" in combined, combined
    assert "migration raw-key preflight failed" not in combined
    events = _deploy_events(env)
    assert "security migrate-primary" in events
    assert any("exit-code-from migrate" in event for event in events)
    assert any(event.startswith("migration-full ack=") for event in events)
    assert events[0] == "archive-preflight dev"
    assert events.index("security migrate-primary") < next(
        index for index, event in enumerate(events) if event.startswith("docker ")
    )
    stop_index = next(
        index for index, event in enumerate(events) if " stop api worker watcher" in event
    )
    migration_index = next(
        index for index, event in enumerate(events) if "exit-code-from migrate" in event
    )
    assert stop_index < migration_index
    assert (tmp_path / "docker-called").exists()


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
    def __init__(self, *, running=False, auth=True, quiet=True, quiescence=None):
        self.events = []
        self.running = running
        self.auth = auth
        self.quiet = quiet
        self.quiescence = list(quiescence or [])

    def select_active_plan(self, plan):
        return plan

    def require_promotion_admission(self, plan):
        # This fake represents only TEST; production admission uses real effects.
        assert plan.channel == 'test'

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
        if self.quiescence:
            result = self.quiescence.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
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
    from app.ops.postgres_deploy import DeployWorker, PostgresDeployError

    class Clock:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    effects = _BwsVmEffects(quiet=False, quiescence=[RuntimeError('unavailable')])
    _worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    clock = Clock()
    worker = DeployWorker(journal, effects, monotonic=clock.monotonic, sleep=clock.sleep)
    with pytest.raises(PostgresDeployError):
        worker.run(operation_id, plan)
    assert journal.read().stage == 'activating'
    assert 'activate-clients' in effects.events


def test_deploy_waits_for_postactivate_quiescence_before_commit(tmp_path):
    class Clock:
        def __init__(self):
            self.now = 0.0
            self.sleeps = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    from app.ops.postgres_deploy import DeployWorker
    clock = Clock()
    effects = _BwsVmEffects(quiescence=[False, True])
    _worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    worker = DeployWorker(journal, effects, monotonic=clock.monotonic, sleep=clock.sleep)

    receipt = worker.run(operation_id, plan)

    assert receipt.stage == 'committed'
    assert effects.events.count('activate-clients') == 1
    assert effects.events.count('quiescence') == 2
    assert clock.sleeps == [5.0]
    assert journal.read().operation_id == operation_id


def test_deploy_postactivate_quiescence_timeout_preserves_pending(tmp_path):
    class Clock:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    from app.ops.postgres_deploy import DeployWorker, PostgresDeployError
    clock = Clock()
    effects = _BwsVmEffects(quiet=False)
    _worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    worker = DeployWorker(journal, effects, monotonic=clock.monotonic, sleep=clock.sleep)

    with pytest.raises(PostgresDeployError):
        worker.run(operation_id, plan)

    receipt = journal.read()
    assert receipt is not None and receipt.stage == 'activating'
    assert receipt.terminal_result is None
    assert effects.events.count('activate-clients') == 1
    assert clock.now == 360.0


def test_deploy_postactivate_quiescence_does_not_accept_late_true(tmp_path):
    from app.ops.postgres_deploy import DeployWorker, PostgresDeployError

    class Clock:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = Clock()
    effects = _BwsVmEffects()

    def late_quiescent():
        effects.events.append('quiescence')
        clock.now = 360.0
        return True

    effects.quiescent = late_quiescent
    _worker, journal, plan, operation_id = _bws_worker(tmp_path, effects)
    worker = DeployWorker(journal, effects, monotonic=clock.monotonic, sleep=clock.sleep)

    with pytest.raises(PostgresDeployError):
        worker.run(operation_id, plan)

    receipt = journal.read()
    assert receipt is not None and receipt.stage == 'activating'
    assert receipt.terminal_result is None
    assert effects.events.count('activate-clients') == 1


def test_automatic_verification_waits_for_postactivate_quiescence(tmp_path):
    from app.ops import pg_acceptance
    from app.ops.postgres_deploy import DeployPlan, DeployWorker

    class Clock:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = Clock()
    effects = _BwsVmEffects(quiescence=[False, True])
    _worker, journal, _plan, operation_id = _bws_worker(tmp_path, effects)
    digest = 'sha256:' + 'b' * 64
    plan = DeployPlan('test', 'a' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=digest, automatic=True)
    result = {
        **pg_acceptance.identity(plan.revision, digest, plan.channel, operation_id),
        'result': 'passed',
        'selected': pg_acceptance.MINIMUM_SELECTED,
        'passed': pg_acceptance.MINIMUM_SELECTED,
        'resource_tree': 'c' * 40,
        'app_image_id': 'sha256:' + 'd' * 64,
        'report_hash': 'e' * 64,
    }
    effects.verify = lambda _operation_id, _selected: (effects.events.append('verify'), result)[1]
    effects.cleanup_verification = lambda *_args: effects.events.append('cleanup')
    worker = DeployWorker(journal, effects, monotonic=clock.monotonic, sleep=clock.sleep)

    receipt = worker.run(operation_id, plan)

    assert receipt.stage == 'committed'
    assert effects.events.count('activate-clients') == 1
    assert effects.events.count('quiescence') == 2
    assert effects.events.index('verify') > effects.events.index('quiescence', effects.events.index('quiescence') + 1)


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


def test_bws_deploy_requires_raw_key_for_active_capture():
    from app.ops.bws_secret_reader import BwsItemAbsent
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import DeployPlan, PostgresDeployError, vm_selected_values

    plan = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress', 'heimdal-capture-watch'))
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


@pytest.mark.parametrize('quiescent', [True, False])
def test_missing_active_raw_key_stops_supervisor_before_activation(
    tmp_path, monkeypatch, quiescent, admitted_bws_caller
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
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _config: True)
    monkeypatch.setattr(
        linux, '_raw_representation_migration_pending', lambda _config, _revision: False
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

    assert 'heimdal-capture-watch' in effects.active_consumers
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
    from app.ops.postgres_deploy import DeployPlan, deploy_from_host, vm_selected_values

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
    values = vm_selected_values(active, Reader())
    assert values['heimdal-raw-migrate'] == {}


def test_vm_capture_watch_selection_uses_runtime_input_and_fails_on_ambiguity(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError
    from app.heimdal.capture_runtime import CaptureRuntimeConfig, CaptureRuntimeConfigError

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
    for whitespace in ('   ', ' \t '):
        runtime.write_text(f'HEIMDAL_CAPTURE_WATCH_DIR="{whitespace}"\n', encoding='utf-8')
        assert linux._capture_watch_configured(cfg) is False
        monkeypatch.setenv('HEIMDAL_CAPTURE_WATCH_DIR', whitespace)
        with pytest.raises(CaptureRuntimeConfigError, match='must be set'):
            CaptureRuntimeConfig.from_env()
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


@pytest.mark.parametrize('entrypoint', ['deploy', 'compose', 'signboard', 'inventory'])
@pytest.mark.parametrize('ambient_python', ['unset', 'conflicting'])
def test_managed_deploy_child_uses_declared_supervisor_interpreter(
    tmp_path, monkeypatch, entrypoint, ambient_python,
):
    import json
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux

    runtime = tmp_path / 'runtime.env'
    runtime.write_text('LLM_PROVIDER=mock\n', encoding='utf-8')
    trace = tmp_path / 'child.json'
    conflicting_python = tmp_path / 'host-python'
    wrong_interpreter_used = tmp_path / 'wrong-interpreter-used'
    conflicting_python.write_text(
        '#!/bin/sh\n: > "$WRONG_INTERPRETER_USED"\nexit 19\n', encoding='utf-8',
    )
    conflicting_python.chmod(0o755)
    conflicting_bin = tmp_path / 'host-bin'
    conflicting_bin.mkdir()
    (conflicting_bin / 'python3').symlink_to(conflicting_python)
    instrumentation = tmp_path / 'instrumentation'
    instrumentation.mkdir()
    # Observe the real shell-selected interpreter, then refuse the real guard's
    # host-config read before it can reach credentials or other host state.
    (instrumentation / 'sitecustomize.py').write_text(
        'import json, os, sys\n'
        'from pathlib import Path\n'
        'Path(os.environ["CHILD_TRACE"]).write_text(json.dumps({\n'
        '    "executable": sys.executable, "argv": sys.orig_argv,\n'
        '    "prefix": sys.prefix,\n'
        '}))\n'
        'def refuse_host_config(event, args):\n'
        '    if event == "open" and args[0] == "/etc/yggdrasil/bws-deploy/test.json":\n'
        '        raise PermissionError("test refuses host config")\n'
        'sys.addaudithook(refuse_host_config)\n',
        encoding='utf-8',
    )
    ambient = {
        'PATH': os.pathsep.join((str(conflicting_bin), os.environ['PATH'])),
        'HOME': str(tmp_path),
        'PYTHONPATH': os.pathsep.join((str(instrumentation), str(REPO_ROOT))),
        'INSTANCE_OWNERSHIP_HOST_STATE_DIR': str(tmp_path / 'ownership'),
        'CHILD_TRACE': str(trace),
        'WRONG_INTERPRETER_USED': str(wrong_interpreter_used),
        'PLAYWRIGHT_BROWSERS_PATH': str(tmp_path / 'ambient-browsers'),
        'SIGNBOARD_ROOT': str(tmp_path / 'signboard'),
    }
    if ambient_python == 'conflicting':
        ambient['PYTHON'] = str(conflicting_python)
    monkeypatch.setattr(os, 'environ', ambient)
    cfg = SimpleNamespace(
        root=tmp_path, channel='test', uid=os.getuid(), gid=os.getgid(),
        password_file=tmp_path / 'password', runtime_env_file=runtime,
    )
    child_environment = linux.LinuxEffects(cfg).environment()
    assert child_environment['PYTHON'] == sys.executable
    runtime_bin = Path(sys.executable).parent
    assert child_environment['PATH'].split(os.pathsep)[0] == str(runtime_bin)
    assert child_environment['PLAYWRIGHT_BROWSERS_PATH'] == str(runtime_bin.parent / 'browsers')

    if entrypoint == 'deploy':
        argv = ['bash', str(SCRIPT), 'deploy', 'test', 'a' * 40, '--dry-run']
    elif entrypoint == 'compose':
        argv = [
            'bash', '-c',
            'source "$1/scripts/lib/deploy_channel_compose.sh"; '
            'deploy_channel_compose "$1" test docker-compose.test.yml pkm-test "$2" config',
            'test', str(REPO_ROOT), str(tmp_path / 'test.env'),
        ]
    elif entrypoint == 'signboard':
        argv = ['bash', '-c',
                'source "$1/scripts/lib/signboard_root.sh"; '
                'resolve_signboard_root_env; printf "%s" "$SIGNBOARD_ROOT"',
                'test', str(REPO_ROOT)]
    else:
        (tmp_path / 'ownership').mkdir(mode=0o700)
        argv = ['bash', '-c',
                'source "$1/scripts/lib/instance_state_deployment.sh"; '
                '_write_settings_rebind_floor_receipt test pending',
                'test', str(REPO_ROOT)]
    result = subprocess.run(
        argv, cwd=REPO_ROOT, env=child_environment,
        capture_output=True, text=True, check=False,
    )

    if entrypoint in {'deploy', 'compose'}:
        expected_returncode = 120 if entrypoint == 'compose' else 78
        assert result.returncode == expected_returncode, result.stdout + result.stderr
        assert 'database deployment refused; operation remains pending' in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        if entrypoint == 'signboard':
            assert result.stdout == str(tmp_path / 'signboard')
        else:
            receipt = json.loads((tmp_path / 'ownership/settings-rebind-runtime-floor-test.json').read_text())
            assert receipt['channel'] == 'test' and receipt['phase'] == 'pending'
    observed = json.loads(trace.read_text(encoding='utf-8'))
    assert observed['prefix'] == sys.prefix
    if entrypoint in {'deploy', 'compose'}:
        assert observed['executable'] == sys.executable
        assert observed['argv'][1:5] == ['-m', 'app.ops.postgres_deploy_linux', 'guard', 'test']
    else:
        # Bare python3 uses the trusted runtime's sibling alias even when the
        # supervisor was launched as python; both must select the same prefix.
        assert observed['executable'] == str(runtime_bin / 'python3')
        assert observed['argv'][1] == ('-c' if entrypoint == 'signboard' else '-')
    assert not wrong_interpreter_used.exists()


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
def test_bws_token_push_does_not_require_runtime_env_config(
    tmp_path, monkeypatch, runtime_path_state, admitted_bws_caller
):
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


def test_vm_selector_failure_records_abort_and_releases_channel_lock(
    tmp_path, monkeypatch, admitted_bws_caller
):
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


def test_deploy_ssh_loss_joins_same_supervised_operation_until_quiescent(
    tmp_path, monkeypatch, admitted_bws_caller
):
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
    monkeypatch.setattr(host, '_configured_deploy_admin', lambda _plan, _controller: object())
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


def test_source_identity_persistence_operation_is_dev_test_authority_bound(
    monkeypatch, tmp_path,
):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host

    operation_id = str(uuid4())
    calls = []

    class Controller:
        directory = tmp_path

        @contextmanager
        def source_persistence_operation(self, channel, *, operation_id):
            calls.append(("host-admit", channel, operation_id))
            operation = SimpleNamespace(
                operation_id=operation_id,
                completed_result=None,
                completed_source=None,
                prepare_mutation=lambda: calls.append(("host-sent", channel, operation_id)),
                finish=lambda evidence: calls.append(("host-finish", evidence)),
            )
            yield operation, False

    class Remote:
        def __init__(self, hostname):
            calls.append(("remote", hostname))

        def persist_source_identity(self, requested_id, revision, image_digest, selected):
            calls.append(("persist", requested_id, revision, image_digest, selected))
            return {
                "contract": "native-source-identity-persistence.v1",
                "operation_id": requested_id,
                "channel": "dev",
                "revision": revision,
                "terminal_state": "committed",
                "eligible": True,
                "reason": None,
                "selected_count": 1,
                "persisted_count": 1,
                "missing_count": 0,
                "invalid_count": 0,
                "ambiguous_count": 0,
                "producer_error_count": 0,
            }

    monkeypatch.setattr(host, "HostSecretController", Controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    monkeypatch.setattr(
        host, "deploy_from_host",
        lambda *_args, **_kwargs: pytest.fail("source persistence must not start a deployment"),
    )
    args = [
        "dev", "a" * 40, "--automatic", "--existing-secrets-only",
        "--persist-source-identity", "--operation-id", operation_id,
        "--image-digest", "sha256:" + "1" * 64,
        "--authority-cutover-binding", "vault-alpha",
        "--authority-cutover-root", "/srv/vault-alpha",
        "--authority-cutover-ownership-root", "/srv/instance-ownership",
    ]
    assert host.main(args) == 0
    assert ("remote", "ygg-dev") in calls
    assert any(call[0] == "persist" and call[1] == operation_id for call in calls)

    without_digest = args[:]
    digest_index = without_digest.index("--image-digest")
    del without_digest[digest_index:digest_index + 2]
    assert host.main(without_digest) == 78
    assert host.main([value for value in args if value != "--existing-secrets-only"]) == 78
    assert host.main(["prod", *args[1:]]) == 78
    malformed = ["bad" if value == operation_id else value for value in args]
    assert host.main(malformed) == 78


def test_source_identity_persistence_accepts_optional_docker_unsets():
    from app.ops import postgres_deploy_linux as linux

    normalized, unset = linux._installed_container_environment([
        "PKM_ENVIRONMENT=dev",
        "VAULT_ROOT=/srv/vault-alpha",
        "POSTGRES_PASSWORD",
        "PGPASSWORD",
        "OPTIONAL_PROVIDER",
        "EXPLICIT_EMPTY=",
        "VCS_REF",
        "BUILT_AT",
    ])
    assert normalized == {
        "PKM_ENVIRONMENT": "dev",
        "VAULT_ROOT": "/srv/vault-alpha",
        "EXPLICIT_EMPTY": "",
    }
    assert unset == ("OPTIONAL_PROVIDER", "PGPASSWORD", "POSTGRES_PASSWORD")


def test_source_identity_unsets_preserve_closed_helper_environment(monkeypatch):
    from app.ops import postgres_deploy_linux as linux

    monkeypatch.setenv("OPTIONAL_PROVIDER", "ambient-must-not-cross-boundary")
    installed, unset = linux._installed_container_environment([
        "PKM_ENVIRONMENT=dev",
        "VAULT_ROOT=/srv/vault-alpha",
        "OPTIONAL_PROVIDER",
        "EXPLICIT_EMPTY=",
    ])
    child = dict(linux._closed_source_helper_environment(installed, installed))
    assert "OPTIONAL_PROVIDER" not in child
    assert child["EXPLICIT_EMPTY"] == ""
    assert child["PKM_ENVIRONMENT"] == "dev"
    with pytest.raises(linux.PostgresDeployError):
        linux._closed_source_helper_environment(
            installed, {**installed, "OPTIONAL_PROVIDER": "env-file-value"},
        )
    snapshot = linux.SourceIdentityRuntimeSnapshot(
        "c" * 64, "d" * 64, ("api", "watcher", "worker"),
        ("api", "watcher", "worker"), "/srv/vault-alpha",
        "docker-compose.full-host-vault.yml", tuple(child.items()), unset,
    )
    effects = linux.LinuxEffects(type("Config", (), {"channel": "dev", "root": Path("/")})())
    captured = {}
    monkeypatch.setattr(
        effects, "environment", lambda *_args: {
            "BWS_DATABASE_TARGET": "local",
            "OPTIONAL_PROVIDER": "ambient-must-not-cross-boundary",
        },
    )
    monkeypatch.setattr(
        linux, "_command",
        lambda argv, **kwargs: captured.update(argv=argv, env=kwargs["env"]) or "",
    )
    effects.compose("run", "-e", "OPTIONAL_PROVIDER", "api", source_snapshot=snapshot)
    assert "OPTIONAL_PROVIDER" not in captured["env"]
    assert captured["argv"][-3:] == ["-e", "OPTIONAL_PROVIDER", "api"]
    legacy_payload = linux._source_identity_execution_payload(
        files=[("runtime.env", "e" * 64)],
        child_environment=(("PKM_ENVIRONMENT", "dev"),),
        resolved_environment={"PKM_ENVIRONMENT": "dev"},
        container_root="/srv/vault-alpha",
        vault_overlay="docker-compose.full-host-vault.yml",
        unset_environment=(),
    )
    assert legacy_payload == {
        "files": [("runtime.env", "e" * 64)],
        "child_environment": [("PKM_ENVIRONMENT", "dev")],
        "resolved_service_environment": [("PKM_ENVIRONMENT", "dev")],
        "container_root": "/srv/vault-alpha",
        "vault_overlay": "docker-compose.full-host-vault.yml",
    }
    assert "unset_environment" not in legacy_payload


@pytest.mark.parametrize("entries", [
    ["OPTIONAL_PROVIDER", "OPTIONAL_PROVIDER=value"],
    ["OPTIONAL_PROVIDER=value", "OPTIONAL_PROVIDER"],
    ["OPTIONAL_PROVIDER", "OPTIONAL_PROVIDER"],
    ["BAD KEY=value"],
    [""],
    [None],
    ["OPTIONAL_PROVIDER=bad\x00value"],
    {"OPTIONAL_PROVIDER": "value"},
    ["PKM_ENVIRONMENT"],
    ["VAULT_ROOT"],
    ["LLM_PROVIDER"],
    ["STORE_BACKEND"],
    ["BWS_ACCESS_TOKEN"],
    ["BWS_ACCESS_TOKEN="],
    ["BWS_ACCESS_TOKEN=secret"],
])
def test_source_identity_environment_normalization_refuses_unsafe_entries(entries):
    from app.ops import postgres_deploy_linux as linux

    with pytest.raises(linux.PostgresDeployError):
        linux._installed_container_environment(entries)


def test_source_identity_absence_proof_retires_only_exact_pending_host_operation(
    monkeypatch, tmp_path,
):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host

    operation_id = str(uuid4())
    calls = []

    class Controller:
        directory = tmp_path

        @contextmanager
        def source_persistence_operation(self, channel, *, operation_id):
            calls.append(("host-admit", channel, operation_id))
            operation = SimpleNamespace(
                operation_id=operation_id,
                completed_result=None,
                mutation_started=True,
                finish=lambda evidence: calls.append(("host-finish", evidence)),
            )
            yield operation, True

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-test"

        def prove_source_identity_absence(self, requested_id):
            calls.append(("prove", requested_id))
            return {
                "contract": "native-source-identity-absence.v1",
                "operation_id": requested_id,
                "channel": "test",
                "native_request_absent": True,
                "native_producer_receipt_absent": True,
                "native_terminal_receipt_absent": True,
                "native_worker_absent": True,
                "native_lock_absent": True,
            }

    monkeypatch.setattr(host, "HostSecretController", Controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    monkeypatch.setattr(
        host, "deploy_from_host",
        lambda *_args, **_kwargs: pytest.fail("absence proof must not deploy"),
    )
    args = [
        "test", "a" * 40, "--automatic", "--existing-secrets-only",
        "--prove-source-persistence-never-admitted", "--operation-id", operation_id,
    ]
    assert host.main(args) == 0
    assert calls[:2] == [("host-admit", "test", operation_id), ("prove", operation_id)]
    evidence = calls[-1][1]
    assert (evidence.operation_id, evidence.kind, evidence.target, evidence.result) == (
        operation_id, "source-persistence", "test", "failed",
    )
    assert host.main([*args, "--persist-source-identity"]) == 78


def test_source_identity_retired_host_operation_never_replays_producer(
    monkeypatch, tmp_path,
):
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController

    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    controller = HostSecretController(state)
    operation_id = str(uuid4())
    with controller.source_persistence_operation(
        "test", operation_id=operation_id,
    ) as (operation, resumed):
        assert resumed is False
        operation.prepare_mutation()

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-test"

        def prove_source_identity_absence(self, requested_id):
            assert requested_id == operation_id
            return {
                "contract": "native-source-identity-absence.v1",
                "operation_id": requested_id,
                "channel": "test",
                "native_request_absent": True,
                "native_producer_receipt_absent": True,
                "native_terminal_receipt_absent": True,
                "native_worker_absent": True,
                "native_lock_absent": True,
            }

        def persist_source_identity(self, *_args, **_kwargs):
            pytest.fail("a retired host operation must never replay the producer")

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    base = [
        "test", "a" * 40, "--automatic", "--existing-secrets-only",
        "--operation-id", operation_id,
    ]
    assert host.main([*base, "--prove-source-persistence-never-admitted"]) == 0
    assert host.main([*base, "--prove-source-persistence-never-admitted"]) == 0
    persist = [
        *base, "--persist-source-identity",
        "--image-digest", "sha256:" + "1" * 64,
        "--authority-cutover-binding", "vault-alpha",
        "--authority-cutover-root", "/srv/vault-alpha",
        "--authority-cutover-ownership-root", "/srv/instance-ownership",
    ]
    assert host.main(persist) == 78
    records = [json.loads(line) for line in (state / "operations.jsonl").read_text().splitlines()]
    assert [record["stage"] for record in records] == ["prepared", "sent", "failed"]
    assert records[-1]["source"] == "native-absence-proof"


def test_source_identity_admitted_failed_operation_can_finish_retained_cleanup(
    monkeypatch, tmp_path,
):
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController

    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    controller = HostSecretController(state)
    operation_id = str(uuid4())
    lifecycle = {
        "request": False,
        "receipt": False,
        "fence": False,
        "producer_calls": 0,
        "cleanup_calls": 0,
    }

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-test"

        def persist_source_identity(self, requested_id, revision, _digest, _selected):
            assert requested_id == operation_id
            if not lifecycle["receipt"]:
                lifecycle.update({
                    "request": True,
                    "receipt": True,
                    "fence": True,
                    "producer_calls": lifecycle["producer_calls"] + 1,
                })
            else:
                assert lifecycle["request"] and lifecycle["fence"]
                lifecycle["cleanup_calls"] += 1
                lifecycle["fence"] = False
            return {
                "contract": "native-source-identity-persistence.v1",
                "operation_id": requested_id,
                "channel": "test",
                "revision": revision,
                "terminal_state": "failed",
                "eligible": False,
                "reason": "source_operation_conflict",
                "selected_count": 1,
                "persisted_count": 0,
                "missing_count": 0,
                "invalid_count": 0,
                "ambiguous_count": 0,
                "producer_error_count": 1,
            }

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    args = [
        "test", "a" * 40, "--automatic", "--existing-secrets-only",
        "--persist-source-identity", "--operation-id", operation_id,
        "--image-digest", "sha256:" + "1" * 64,
        "--authority-cutover-binding", "vault-alpha",
        "--authority-cutover-root", "/srv/vault-alpha",
        "--authority-cutover-ownership-root", "/srv/instance-ownership",
    ]
    assert host.main(args) == 78
    assert lifecycle == {
        "request": True,
        "receipt": True,
        "fence": True,
        "producer_calls": 1,
        "cleanup_calls": 0,
    }
    assert host.main(args) == 78
    assert lifecycle == {
        "request": True,
        "receipt": True,
        "fence": False,
        "producer_calls": 1,
        "cleanup_calls": 1,
    }
    records = [json.loads(line) for line in (state / "operations.jsonl").read_text().splitlines()]
    assert [record["stage"] for record in records] == ["prepared", "sent", "failed"]
    assert records[-1]["source"] == "remote-terminal"


def test_source_identity_absence_proof_holds_host_lock_across_remote_read(
    monkeypatch, tmp_path,
):
    import threading
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController
    from app.ops.postgres_deploy import PostgresDeployError

    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    controller = HostSecretController(state)
    operation_id = str(uuid4())
    with controller.source_persistence_operation(
        "test", operation_id=operation_id,
    ) as (operation, _resumed):
        operation.prepare_mutation()

    proof_called = threading.Event()
    native_request_present = threading.Event()

    class Remote:
        def __init__(self, hostname):
            assert hostname == "ygg-test"

        def prove_source_identity_absence(self, requested_id):
            assert requested_id == operation_id
            proof_called.set()
            if native_request_present.is_set():
                raise PostgresDeployError()
            pytest.fail("proof ran before the competing host lock was released")

    monkeypatch.setattr(host, "HostSecretController", lambda: controller)
    monkeypatch.setattr(host, "SshDeployRemote", Remote)
    args = [
        "test", "a" * 40, "--automatic", "--existing-secrets-only",
        "--prove-source-persistence-never-admitted", "--operation-id", operation_id,
    ]
    result = []
    with controller.source_persistence_operation(
        "test", operation_id=operation_id,
    ):
        thread = threading.Thread(target=lambda: result.append(host.main(args)))
        thread.start()
        assert proof_called.wait(0.2) is False
        native_request_present.set()
    thread.join(timeout=2)
    assert thread.is_alive() is False
    assert result == [78]
    assert proof_called.is_set()
    records = [json.loads(line) for line in (state / "operations.jsonl").read_text().splitlines()]
    assert [record["stage"] for record in records] == ["prepared", "sent"]


def test_source_identity_absence_proof_refuses_partial_ambiguous_or_mismatched_state(
    monkeypatch, tmp_path,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    operation_id = str(uuid4())
    directory = tmp_path / "journal"
    directory.mkdir()
    terminal = SimpleNamespace(operation_id=str(uuid4()), terminal_result="failed")
    config = SimpleNamespace(
        channel="dev", journal=SimpleNamespace(directory=directory, read=lambda: terminal),
    )
    effects = object.__new__(linux.LinuxEffects)
    effects.config = config
    monkeypatch.setattr(effects, "channel_lock_owner", lambda: None)
    monkeypatch.setattr(linux, "_command", lambda _args, **_kwargs: "")
    proof = effects.prove_source_identity_absence(operation_id)
    assert proof["native_request_absent"] is True

    class RoutedEffects:
        def __init__(self, selected):
            assert selected is config

        def prove_source_identity_absence(self, requested_id):
            assert requested_id == operation_id
            return proof

    monkeypatch.setattr(linux, "LinuxEffects", RoutedEffects)
    supervisor = linux.DeploymentSupervisor(config)
    monkeypatch.setattr(supervisor, "_require_current_config", lambda: None)
    assert supervisor.request({
        "action": "source-identity-prove-absence", "operation_id": operation_id,
    }) == {"source_identity_absence": proof}
    with pytest.raises(PostgresDeployError):
        supervisor.request({
            "action": "source-identity-prove-absence",
            "operation_id": operation_id,
            "unexpected": True,
        })

    request = directory / f"dev-source-identity-{operation_id}.request.json"
    request.write_text("{}")
    with pytest.raises(PostgresDeployError):
        effects.prove_source_identity_absence(operation_id)
    request.unlink()
    monkeypatch.setattr(effects, "channel_lock_owner", lambda: b"foreign")
    with pytest.raises(PostgresDeployError):
        effects.prove_source_identity_absence(operation_id)
    monkeypatch.setattr(effects, "channel_lock_owner", lambda: None)
    monkeypatch.setattr(linux, "_command", lambda _args, **_kwargs: "a" * 64)
    with pytest.raises(PostgresDeployError):
        effects.prove_source_identity_absence(operation_id)


def test_source_identity_absence_reconciliation_is_content_free_and_never_replays(
    monkeypatch,
):
    import json
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    operation_id = str(uuid4())
    expected = {
        "contract": "native-source-identity-absence.v1",
        "operation_id": operation_id,
        "channel": "dev",
        "native_request_absent": True,
        "native_producer_receipt_absent": True,
        "native_terminal_receipt_absent": True,
        "native_worker_absent": True,
        "native_lock_absent": True,
    }
    calls = []

    def run(command, **kwargs):
        calls.append((command, json.loads(kwargs["input"])))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"source_identity_absence": expected}),
        )

    monkeypatch.setattr(linux.subprocess, "run", run)
    remote = linux.SshDeployRemote("ygg-dev")
    assert remote.prove_source_identity_absence(operation_id) == expected
    assert calls == [(
        ["ssh", "-o", "BatchMode=yes", "--", "ygg-dev", "sudo", "-n",
         "/usr/local/libexec/yggdrasil-bws-deploy", "rpc", "dev"],
        {"action": "source-identity-prove-absence", "operation_id": operation_id},
    )]
    assert set(expected) == {
        "contract", "operation_id", "channel", "native_request_absent",
        "native_producer_receipt_absent", "native_terminal_receipt_absent",
        "native_worker_absent", "native_lock_absent",
    }
    with pytest.raises(PostgresDeployError):
        remote.prove_source_identity_absence("bad")
    monkeypatch.setattr(
        linux.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({
                "source_identity_absence": {**expected, "private_path": "/forbidden"},
            }),
        ),
    )
    with pytest.raises(PostgresDeployError):
        remote.prove_source_identity_absence(operation_id)

    malformed_proofs = []
    for numeric in (1, 1.0):
        malformed_proofs.append({**expected, "native_request_absent": numeric})
    missing = dict(expected)
    missing.pop("native_lock_absent")
    malformed_proofs.append(missing)
    malformed_proofs.append({**expected, "extra": True})
    malformed_proofs.append({
        **expected,
        "native_request_absent": 1,
        "native_lock_absent": False,
    })
    for malformed_proof in malformed_proofs:
        monkeypatch.setattr(
            linux.subprocess,
            "run",
            lambda *_args, proof=malformed_proof, **_kwargs: SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"source_identity_absence": proof}),
            ),
        )
        with pytest.raises(PostgresDeployError):
            remote.prove_source_identity_absence(operation_id)


def test_native_deploy_reports_source_projection_identity_refusal() -> None:
    from app.ops.native_source_bootstrap import (
        SOURCE_PROJECTION_FAILURE_CODES, source_terminal_reason,
    )

    status = SOURCE_PROJECTION_FAILURE_CODES["legacy_identity_persistence_refused"]
    assert status == 109
    assert source_terminal_reason(status) == "legacy_identity_persistence_refused"


def test_test_recovery_reset_is_candidate_and_operation_bound(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, DeployReceipt, PostgresDeployError, TestRecoveryRequest,
    )

    failed_operation_id = str(uuid4())
    digest = 'sha256:' + '1' * 64
    plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False, digest, True,
    )
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    controller = SimpleNamespace(directory=tmp_path)
    recovered: list[TestRecoveryRequest] = []
    deployed: list[tuple[DeployPlan, bool, str]] = []

    class Remote:
        def __init__(self, hostname):
            assert hostname == 'ygg-test'

        def test_recovery_reset(self, request):
            request.validate()
            if request.plan != plan:
                raise PostgresDeployError()
            recovered.append(request)
            return DeployReceipt(failed_operation_id, 'test', 'deploy', 'failed', 'failed')

    class Operation:
        completed_result = None

        def finish(self, evidence):
            assert evidence.operation_id == failed_operation_id
            self.completed_result = evidence.result

    @contextmanager
    def deploy_operation(target, *, allow_bootstrap, operation_id):
        assert (target, allow_bootstrap, operation_id) == ('test', False, failed_operation_id)
        yield Operation(), True

    def deploy(_admin, _remote, selected, *, qualified, allow_bootstrap, operation_id):
        qualified()
        deployed.append((selected, allow_bootstrap, operation_id))
        return DeployReceipt(operation_id, 'test', 'deploy', 'committed', 'committed')

    controller.deploy_operation = deploy_operation
    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, 'SshDeployRemote', Remote)
    monkeypatch.setattr(host, '_configured_deploy_admin', lambda _plan, _controller: object())
    monkeypatch.setattr(host, 'SecretAdmin', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(host, 'require_qualification', lambda _controller: None)
    monkeypatch.setattr(host, 'deploy_from_host', deploy)

    args = [
        'test', plan.revision, '--automatic', '--image-digest', digest,
        '--existing-secrets-only', '--recover-test-source',
        '--failed-operation-id', failed_operation_id,
        '--authority-cutover-binding', authority.binding_id,
        '--authority-cutover-root', authority.root,
        '--authority-cutover-ownership-root', authority.ownership_root,
    ]
    assert host.main(args) == 0
    assert len(recovered) == 1
    assert recovered[0] == TestRecoveryRequest(failed_operation_id, plan, authority)
    assert len(deployed) == 1
    assert deployed[0][:2] == (plan, False)
    assert deployed[0][2] != failed_operation_id

    # A changed candidate is a new request, never an alias for the failed operation.
    assert host.main([*args[:1], 'b' * 40, *args[2:]]) == 78
    assert len(recovered) == 1


def test_missing_instance_state_recovery_reconstructs_dormant_registry_and_starts_fresh_successor(monkeypatch, tmp_path, capsys):
    from contextlib import contextmanager
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, TestRecoveryRequest

    failed_operation_id = str(uuid4())
    digest = 'sha256:' + 'a' * 64
    plan = DeployPlan(
        'test', 'b' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False, digest, True,
    )
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    controller = SimpleNamespace(directory=tmp_path)
    failed_successor_operation_id = str(uuid4())
    class Operation:
        completed_result = 'failed'

        def finish(self, evidence):
            self.completed_result = evidence.result

    @contextmanager
    def deploy_operation(target, *, allow_bootstrap, operation_id):
        assert (target, allow_bootstrap, operation_id) == (
            'test', False, failed_successor_operation_id,
        )
        yield Operation(), True

    controller.deploy_operation = deploy_operation
    calls: list[TestRecoveryRequest] = []
    releases: list[TestRecoveryRequest] = []
    release_successors: list[str] = []
    events: list[str] = []
    deployed: list[tuple[DeployPlan, str]] = []

    class Remote:
        def __init__(self, hostname):
            assert hostname == 'ygg-test'

        def test_recovery_reset(self, request):
            assert request.failed_operation_id == failed_operation_id
            return host.DeployReceipt(
                failed_operation_id, 'test', 'deploy', 'failed', 'failed'
            )

        def test_recovery_reconstruct_instance_state(self, request):
            calls.append(request)
            events.append('reconstruct')
            return {
                'schema': 'test-instance-state-recovery.v1',
                'channel': 'test',
                'activation': 'inactive_fenced',
                'request': {'failed_operation_id': request.failed_operation_id},
                'registry_revision': 1,
                'registry_sha256': 'c' * 64,
                'registered_bindings': ['test-binding'],
            }

        def test_recovery_release_instance_state(self, request, *, successor_operation_id):
            releases.append(request)
            release_successors.append(successor_operation_id)
            events.append('release')
            return {'channel': 'test', 'released': True, 'reason': 'abandoned-deployment'}

    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, 'SshDeployRemote', Remote)
    monkeypatch.setattr(host, '_configured_deploy_admin', lambda _plan, _controller: object())
    monkeypatch.setattr(host, 'SecretAdmin', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(host, 'require_qualification', lambda _controller: None)

    def deploy(_admin, _remote, selected, *, qualified, allow_bootstrap, operation_id):
        qualified()
        assert allow_bootstrap is False
        events.append('deploy')
        deployed.append((selected, operation_id))
        return host.DeployReceipt(operation_id, 'test', 'deploy', 'committed', 'committed')

    monkeypatch.setattr(host, 'deploy_from_host', deploy)
    source_request = TestRecoveryRequest(
        failed_operation_id,
        replace(
            plan, revision='a' * 40,
            image_digest='sha256:' + 'd' * 64,
        ),
        authority,
    )
    marker = host._test_recovery_marker_path(controller, source_request)
    marker.write_text(json.dumps({
        'schema': host._TEST_RECOVERY_MARKER_SCHEMA,
        'state': 'ready',
        'request': source_request.payload(),
        'fresh_operation_id': failed_successor_operation_id,
    }, sort_keys=True) + '\n')
    marker.chmod(0o600)
    args = [
        'test', plan.revision, '--automatic', '--image-digest', digest,
        '--existing-secrets-only', '--reconstruct-missing-instance-state',
        '--failed-operation-id', failed_operation_id,
        '--authority-cutover-binding', authority.binding_id,
        '--authority-cutover-root', authority.root,
        '--authority-cutover-ownership-root', authority.ownership_root,
    ]
    assert host.main(args) == 0
    expected_lineage = TestRecoveryRequest(
        failed_successor_operation_id, plan, authority,
        source_operation_id=failed_operation_id,
        source_plan=source_request.plan,
    )
    assert calls == [expected_lineage]
    assert releases == [expected_lineage]
    assert release_successors == [deployed[0][1]]
    assert events == ['reconstruct', 'release', 'deploy']
    assert len(deployed) == 1
    assert deployed[0][0] == plan
    assert deployed[0][1] != failed_operation_id
    assert capsys.readouterr().out

    # The producer is never a general startup side effect and cannot be used
    # for another channel or a non-automatic candidate.
    assert host.main(['dev', plan.revision, '--reconstruct-missing-instance-state']) == 78


def test_missing_instance_state_recovery_refuses_authority_drift_without_mutation(monkeypatch, tmp_path):
    """The VM producer rejects a changed authority tuple before Compose."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, DeployReceipt, PostgresDeployError,
        TestRecoveryRequest,
    )

    operation_id = str(uuid4())
    source_operation_id = str(uuid4())
    digest = 'sha256:' + 'b' * 64
    plan = DeployPlan(
        'test', 'c' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False, digest, True,
    )
    ownership_root = tmp_path / 'ownership'
    ownership_root.mkdir(mode=0o700)
    (ownership_root / 'legacy-owner-inventory.json').write_text('{}\n')
    (ownership_root / 'deployment-quiescence-proof.json').write_text('{}\n')
    authority = AuthorityCutover(
        'test-binding', str(tmp_path / 'vault'), str(ownership_root),
    )
    failed = plan
    receipt = DeployReceipt(
        operation_id, 'test', 'deploy', 'failed', 'failed',
        source_failure='legacy_identity_persistence_refused',
    )

    class Journal:
        directory = tmp_path / 'journal'
        channel = 'test'

        def read(self):
            return receipt

        def bound_plan(self, selected):
            assert selected == operation_id
            return failed

    effects = linux.LinuxEffects(SimpleNamespace(
        channel='test', root=tmp_path, journal=Journal(),
        uid=os.geteuid(), gid=os.getegid(),
    ))
    effects.local_database = lambda: True
    effects.recovery_quiescent = lambda: True
    effects._read_test_recovery_disposition = lambda _request: {'state': 'complete'}
    composed: list[object] = []
    effects.compose = lambda *args: composed.append(args) or ''
    drifted = AuthorityCutover('other-binding', authority.root, authority.ownership_root)
    request = TestRecoveryRequest(
        operation_id, plan, drifted,
        source_operation_id=source_operation_id, source_plan=plan,
    )
    observed: list[AuthorityCutover] = []

    def refuse_drift(selected, **_kwargs):
        observed.append(selected.authority_cutover)
        raise PostgresDeployError()

    effects._validate_test_instance_state_recovery_authority = refuse_drift
    with pytest.raises(PostgresDeployError):
        effects.reconstruct_missing_test_instance_state(request)
    assert observed == [drifted]
    assert composed == []


def test_missing_instance_state_recovery_is_crash_idempotent(monkeypatch, tmp_path, capsys):
    """A host retry reuses the durable successor checkpoint."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, TestRecoveryRequest

    operation_id = str(uuid4())
    digest = 'sha256:' + 'd' * 64
    plan = DeployPlan(
        'test', 'e' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False, digest, True,
    )
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    controller = SimpleNamespace(directory=tmp_path)
    failed_successor_operation_id = str(uuid4())
    class Operation:
        completed_result = 'failed'

        def finish(self, evidence):
            self.completed_result = evidence.result

    @contextmanager
    def deploy_operation(target, *, allow_bootstrap, operation_id):
        assert (target, allow_bootstrap, operation_id) == (
            'test', False, failed_successor_operation_id
        )
        yield Operation(), True

    controller.deploy_operation = deploy_operation
    reconstruct_calls: list[object] = []
    release_calls: list[object] = []
    release_successors: list[str] = []
    deploy_calls: list[str] = []

    class Remote:
        def __init__(self, _hostname):
            pass

        def test_recovery_reset(self, request):
            assert request.failed_operation_id == operation_id
            return host.DeployReceipt(operation_id, 'test', 'deploy', 'failed', 'failed')

        def test_recovery_reconstruct_instance_state(self, _request):
            reconstruct_calls.append('reconstruct')
            return {
                'schema': 'test-instance-state-recovery.v1',
                'channel': 'test',
                'activation': 'inactive_fenced',
                'request': {'failed_operation_id': operation_id},
            }

        def test_recovery_release_instance_state(self, request, *, successor_operation_id):
            release_calls.append(request)
            release_successors.append(successor_operation_id)
            return {
                'channel': 'test', 'released': False,
                'reason': 'already-released-after-reconstruction',
            }

    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, 'SshDeployRemote', Remote)
    monkeypatch.setattr(host, '_configured_deploy_admin', lambda _plan, _controller: object())
    monkeypatch.setattr(host, 'SecretAdmin', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(host, 'require_qualification', lambda _controller: None)

    def deploy(_admin, _remote, _selected, *, qualified, allow_bootstrap, operation_id):
        qualified()
        deploy_calls.append(operation_id)
        return host.DeployReceipt(operation_id, 'test', 'deploy', 'committed', 'committed')

    monkeypatch.setattr(host, 'deploy_from_host', deploy)
    args = [
        'test', plan.revision, '--automatic', '--image-digest', digest,
        '--existing-secrets-only', '--reconstruct-missing-instance-state',
        '--failed-operation-id', operation_id,
        '--authority-cutover-binding', authority.binding_id,
        '--authority-cutover-root', authority.root,
        '--authority-cutover-ownership-root', authority.ownership_root,
    ]
    # An older source-reset-only checkpoint is still a valid reset receipt, but
    # it is not reconstruction evidence.  The explicit producer must run once
    # and upgrade the marker before the successor deploy is admitted.
    old_request = TestRecoveryRequest(operation_id, plan, authority)
    old_marker = host._test_recovery_marker_path(controller, old_request)
    old_marker.write_text(
        json.dumps({
            'schema': host._TEST_RECOVERY_MARKER_SCHEMA,
            'state': 'ready',
            'request': old_request.payload(),
            'fresh_operation_id': failed_successor_operation_id,
        }, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    old_marker.chmod(0o600)
    assert host.main(args) == 0
    assert host.main(args) == 0
    assert reconstruct_calls == ['reconstruct']
    assert len(release_calls) == 2
    assert release_calls[0] == release_calls[1]
    assert release_successors == deploy_calls
    assert len(deploy_calls) == 2
    assert deploy_calls[0] == deploy_calls[1]
    capsys.readouterr()


def test_test_recovery_accepts_exact_failed_cutover_plan_with_automatic_successor(tmp_path):
    from contextlib import contextmanager
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, DeployReceipt, PostgresDeployError, TestRecoveryRequest,
    )

    operation_id = str(uuid4())
    successor = DeployPlan(
        'test', 'f' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'f' * 64, True,
    )
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    failed = replace(successor, automatic=False, ack_forward_only=True, image_digest=None,
                     authority_cutover=authority)
    receipt = DeployReceipt(
        operation_id, 'test', 'deploy', 'failed', 'failed',
        source_failure='legacy_identity_persistence_refused',
    )

    class Journal:
        directory = tmp_path / 'journal'
        channel = 'test'

        def read(self):
            return receipt

        def bound_plan(self, selected):
            assert selected == operation_id
            return failed

    effects = linux.LinuxEffects(SimpleNamespace(channel='test', root=tmp_path, journal=Journal()))
    request = TestRecoveryRequest(operation_id, successor, authority)
    qualified: list = []
    observed: list = []
    effects.local_database = lambda: True
    effects.qualify_authority_cutover = lambda plan: qualified.append(plan)
    effects.quiescent = lambda: True
    effects.recover_source_terminal = lambda operation, plan: observed.append((operation, plan))
    effects._read_test_recovery_disposition = lambda _request: {'state': 'complete'}
    effects.retire_reconciled_channel_lock = lambda _handle: None
    @contextmanager
    def lock():
        yield object()
    effects.failed_reconciliation_lock = lock

    result = effects.reset_test_source_projection(request)

    assert result == receipt
    assert qualified == []
    assert observed == []
    request.validate_failed_plan(failed)
    with pytest.raises(PostgresDeployError):
        request.validate_failed_plan(successor)


def test_test_recovery_refuses_failed_cutover_plan_drift_without_mutation(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, DeployReceipt, PostgresDeployError, TestRecoveryRequest,
    )

    operation_id = str(uuid4())
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    successor = DeployPlan(
        'test', 'e' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'e' * 64, True,
    )
    failed = replace(successor, automatic=False, authority_cutover=authority)
    receipt = DeployReceipt(
        operation_id, 'test', 'deploy', 'failed', 'failed',
        source_failure='legacy_identity_persistence_refused',
    )

    class Journal:
        directory = tmp_path / 'journal'
        channel = 'test'

        def read(self):
            return receipt

        def bound_plan(self, selected):
            assert selected == operation_id
            return failed

    effects = linux.LinuxEffects(SimpleNamespace(channel='test', root=tmp_path, journal=Journal()))
    effects.local_database = lambda: True
    mutations: list[str] = []
    effects.qualify_authority_cutover = lambda _plan: mutations.append('authority')
    effects.quiescent = lambda: mutations.append('quiescent') or True
    effects.compose = lambda *_args: mutations.append('compose')
    effects._write_test_recovery_disposition = lambda *_args: mutations.append('disposition')
    effects._test_recovery_remove_volume = lambda *_args: mutations.append('volume')
    request = TestRecoveryRequest(operation_id, successor, authority)

    drifts = (
        replace(successor, revision='d' * 40),
        replace(successor, image_digest='sha256:' + 'd' * 64),
        replace(successor, services=('db', 'api')),
    )
    for candidate in drifts:
        with pytest.raises(PostgresDeployError):
            effects.reset_test_source_projection(replace(request, plan=candidate))
    with pytest.raises(PostgresDeployError):
        effects.reset_test_source_projection(replace(request, authority_cutover=replace(
            authority, binding_id='other-binding')))
    assert mutations == []


def test_recover_test_source_rejects_plan_mismatch_before_host_marker(monkeypatch, tmp_path):
    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController
    from app.ops.postgres_deploy import AuthorityCutover, PostgresDeployError

    controller = HostSecretController(tmp_path / 'controller')
    with controller.deploy_operation('test', allow_bootstrap=False) as (operation, resumed):
        assert resumed is False
        failed_operation_id = operation.operation_id
        operation.prepare_mutation()
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    retained_failed_revision = 'b' * 40
    reset_requests = []
    admin_resolutions = []

    class Remote:
        def __init__(self, hostname):
            assert hostname == 'ygg-test'

        def test_recovery_reset(self, request):
            # Model the VM refusing the candidate because it does not match the
            # retained failed plan. The host must not publish a ready marker.
            reset_requests.append(request)
            assert request.plan.revision == 'a' * 40
            assert request.plan.revision != retained_failed_revision
            raise PostgresDeployError()

    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, 'SshDeployRemote', Remote)
    monkeypatch.setattr(
        host, '_configured_deploy_admin',
        lambda plan, selected: admin_resolutions.append((plan.channel, selected)) or object(),
    )
    args = [
        'test', 'a' * 40, '--automatic', '--image-digest', 'sha256:' + 'a' * 64,
        '--existing-secrets-only', '--recover-test-source',
        '--failed-operation-id', failed_operation_id,
        '--authority-cutover-binding', authority.binding_id,
        '--authority-cutover-root', authority.root,
        '--authority-cutover-ownership-root', authority.ownership_root,
    ]

    assert host.main(args) == 78
    assert admin_resolutions == [('test', controller)]
    assert len(reset_requests) == 1
    assert reset_requests[0].failed_operation_id == failed_operation_id
    assert reset_requests[0].authority_cutover == authority
    marker = controller.directory / ('test-source-recovery-' + failed_operation_id + '.json')
    assert not marker.exists()


def test_test_recovery_reset_retry_survives_host_crash_before_fresh_deploy(monkeypatch, tmp_path):
    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.host_secret_controller import HostSecretController
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, DeployReceipt,
        TestRecoveryRequest,
    )

    controller = HostSecretController(tmp_path / 'controller')
    with controller.deploy_operation('test', allow_bootstrap=False) as (operation, resumed):
        assert resumed is False
        operation.prepare_mutation()
    failed_operation_id = operation.operation_id
    digest = 'sha256:' + '4' * 64
    plan = DeployPlan(
        'test', 'c' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False, digest, True,
    )
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    request = TestRecoveryRequest(failed_operation_id, plan, authority)
    recovered: list[TestRecoveryRequest] = []
    deployed: list[str] = []

    class Remote:
        def __init__(self, hostname):
            assert hostname == 'ygg-test'

        def test_recovery_reset(self, selected):
            selected.validate()
            recovered.append(selected)
            return DeployReceipt(failed_operation_id, 'test', 'deploy', 'failed', 'failed')

    deploy_attempts: list[str] = []

    def deploy(_admin, _remote, selected, *, qualified, allow_bootstrap, operation_id):
        deploy_attempts.append(operation_id)
        if len(deploy_attempts) == 1:
            # Crash after reset checkpoint, at the fresh-deploy boundary.
            raise RuntimeError('simulated host interruption before fresh deploy')
        qualified()
        assert selected == plan
        assert allow_bootstrap is False
        deployed.append(operation_id)
        return DeployReceipt(operation_id, 'test', 'deploy', 'committed', 'committed')

    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, 'SshDeployRemote', Remote)
    monkeypatch.setattr(host, '_configured_deploy_admin', lambda _plan, _controller: object())
    monkeypatch.setattr(host, 'SecretAdmin', lambda *_args, **_kwargs: object())
    monkeypatch.setattr(host, 'require_qualification', lambda _controller: None)
    monkeypatch.setattr(host, 'deploy_from_host', deploy)
    args = [
        'test', plan.revision, '--automatic', '--image-digest', digest,
        '--existing-secrets-only', '--recover-test-source',
        '--failed-operation-id', failed_operation_id,
        '--authority-cutover-binding', authority.binding_id,
        '--authority-cutover-root', authority.root,
        '--authority-cutover-ownership-root', authority.ownership_root,
    ]

    assert host.main(args) == 78
    marker = host._read_test_recovery_marker(controller, request)
    assert marker is not None and marker['state'] == 'ready'
    fresh_operation_id = marker['fresh_operation_id']
    assert recovered == [request]
    assert deploy_attempts == [fresh_operation_id]
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None

    assert host.main(args) == 0
    assert recovered == [request]
    assert deploy_attempts == [fresh_operation_id, fresh_operation_id]
    assert deployed == [fresh_operation_id]


def test_test_recovery_reset_refuses_boundary_drift_without_mutation(monkeypatch, tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, DeployReceipt, PostgresDeployError,
        TestRecoveryRequest,
    )

    operation_id = str(uuid4())
    digest = 'sha256:' + '2' * 64
    plan = DeployPlan(
        'test', 'c' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False, digest, True,
    )
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    failed_plan = replace(plan, automatic=False, authority_cutover=authority)
    receipt = DeployReceipt(
        operation_id, 'test', 'deploy', 'activating', None,
        source_failure='legacy_identity_persistence_refused',
    )

    class Journal:
        directory = tmp_path / 'journal'
        channel = 'test'

        def read(self):
            return receipt

        def bound_plan(self, selected):
            assert selected == operation_id
            return failed_plan

        def write(self, *_args, **_kwargs):
            raise AssertionError('journal mutation must not occur on boundary drift')

    cfg = SimpleNamespace(root=tmp_path, channel='test', journal=Journal())
    effects = linux.LinuxEffects(cfg)
    mutations: list[str] = []
    effects.local_database = lambda: True
    effects.qualify_authority_cutover = lambda _plan: mutations.append('authority')
    effects.quiescent = lambda: mutations.append('quiescent') or True
    effects.recover_source_terminal = lambda *_args: mutations.append('source')
    effects.compose = lambda *_args: mutations.append('compose')
    effects._write_test_recovery_disposition = lambda *_args: mutations.append('disposition')
    effects._test_recovery_remove_volume = lambda *_args: mutations.append('volume')
    request = TestRecoveryRequest(operation_id, plan, authority)

    # Candidate and operation mismatches fail before authority qualification or effects.
    for drifted in (
        replace(request, plan=replace(plan, revision='d' * 40)),
        replace(request, failed_operation_id=str(uuid4())),
    ):
        with pytest.raises(PostgresDeployError):
            effects.reset_test_source_projection(drifted)
    assert mutations == []

    # A changed authority is admitted only through the live qualification gate;
    # a refusal there is still before any source, journal, service, or volume effect.
    effects.qualify_authority_cutover = lambda _plan: (_ for _ in ()).throw(PostgresDeployError())
    with pytest.raises(PostgresDeployError):
        effects.reset_test_source_projection(replace(request, authority_cutover=replace(
            authority, binding_id='other-binding'
        )))
    assert mutations == []

    # Embedding identity/model preflight runs before writer drain and is not
    # evidence that a source projection was ever attempted.
    monkeypatch.setattr(effects.config.journal, 'read', lambda: replace(
        receipt, source_failure='embedding_identity_unavailable'
    ))
    with pytest.raises(PostgresDeployError):
        effects.reset_test_source_projection(request)
    assert mutations == []

    # A non-TEST supervisor cannot route the canonical reset action at all.
    non_test = SimpleNamespace(channel='dev', journal=Journal())
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: non_test)
    supervisor = linux.DeploymentSupervisor(non_test)
    with pytest.raises(PostgresDeployError):
        supervisor.request({'action': 'test-recovery-reset', **request.payload()})


def test_test_recovery_reset_preserves_instance_state_authority(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployJournal, DeployPlan,
        TestRecoveryRequest,
    )

    root = tmp_path / 'checkout'
    lock_dir = root / 'config/deploy/test.env.lock'
    lock_dir.mkdir(parents=True, mode=0o700)
    (lock_dir / 'bws-owner').touch(mode=0o600)
    journal = DeployJournal(tmp_path / 'journal', 'test')
    operation_id = str(uuid4())
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',), image_digest='sha256:' + '1' * 64,
                      automatic=True)
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    failed_plan = replace(plan, automatic=False, authority_cutover=authority)
    journal.bind_request(operation_id, failed_plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(operation_id, stage)
    journal.record_source_failure(operation_id, plan.revision, 'legacy_identity_persistence_refused')
    journal.write(operation_id, 'failed')
    config = SimpleNamespace(channel='test', root=root, journal=journal)
    effects = linux.LinuxEffects(config)
    request = TestRecoveryRequest(operation_id, plan, authority)
    effects.local_database = lambda: True
    disposition_states = ['prepared']
    effects._read_test_recovery_disposition = lambda _request: {'state': disposition_states[-1]}
    effects._write_test_recovery_disposition = lambda _request, state: disposition_states.append(state)
    effects.qualify_authority_cutover = lambda _plan: (_ for _ in ()).throw(
        AssertionError('prepared recovery must not re-qualify removed containers')
    )
    effects.recover_source_terminal = lambda *_args: (_ for _ in ()).throw(
        AssertionError('prepared recovery must not replay the source one-shot')
    )
    effects.quiescent = lambda: True
    composed: list[tuple[str, ...]] = []
    effects.compose = lambda *args: composed.append(args) or ''
    effects.initialized = lambda: False
    removed: list[str] = []
    effects._test_recovery_remove_volume = lambda name: removed.append(name)
    recreated: list[str] = []
    effects._test_recovery_recreate_empty_pgdata = lambda: recreated.append('pkm-test_pgdata')

    receipt = effects.reset_test_source_projection(request)

    assert receipt.terminal_result == 'failed'
    assert removed == ['pkm-test_pgdata', 'pkm-test_runtime-tmp']
    assert recreated == ['pkm-test_pgdata']
    assert len(composed) == 2
    assert disposition_states == ['prepared', 'complete']


def test_test_recovery_recreates_empty_pgdata_before_completion(tmp_path, monkeypatch):
    from dataclasses import replace
    import json
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployJournal, DeployPlan, TestRecoveryRequest,
    )

    root = tmp_path / 'checkout'
    lock_dir = root / 'config/deploy/test.env.lock'
    lock_dir.mkdir(parents=True, mode=0o700)
    (lock_dir / 'bws-owner').touch(mode=0o600)
    data_directory = tmp_path / 'pgdata'
    data_directory.mkdir()
    journal = DeployJournal(tmp_path / 'journal', 'test')
    operation_id = str(uuid4())
    plan = DeployPlan('test', 'b' * 40, ('db',), ('postgres-db',), image_digest='sha256:' + '2' * 64,
                      automatic=True)
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    failed_plan = replace(plan, automatic=False, authority_cutover=authority)
    journal.bind_request(operation_id, failed_plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(operation_id, stage)
    journal.record_source_failure(operation_id, plan.revision, 'legacy_identity_persistence_refused')
    journal.write(operation_id, 'failed')
    config = SimpleNamespace(
        channel='test', root=root, data_directory=data_directory, journal=journal,
    )
    effects = linux.LinuxEffects(config)
    request = TestRecoveryRequest(operation_id, plan, authority)
    expected_fields = {'host': 'db', 'port': '5432', 'user': 'app', 'dbname': 'app_test'}
    def local_database():
        effects.database_fields = expected_fields
        return True
    effects.local_database = local_database
    disposition_states = ['prepared']
    effects._read_test_recovery_disposition = lambda _request: {'state': disposition_states[-1]}
    effects._write_test_recovery_disposition = lambda _request, state: disposition_states.append(state)
    effects.quiescent = lambda: True
    effects.compose = lambda *_args: ''
    volume_rows = {
        name: [{
            'Name': name,
            'Driver': 'local',
            'Mountpoint': str(data_directory) if name == 'pkm-test_pgdata' else str(tmp_path / name),
            'Labels': {
                'com.docker.compose.project': 'pkm-test',
                'com.docker.compose.volume': 'pgdata',
            },
        }]
        for name in ('pkm-test_pgdata', 'pkm-test_instance-state', 'pkm-test_runtime-tmp')
    }
    commands: list[list[str]] = []

    def command(argv, **_kwargs):
        commands.append(argv)
        if argv[1:3] == ['volume', 'ls']:
            name = argv[-1].removeprefix('name=^').removesuffix('$')
            return name
        if argv[1:3] == ['volume', 'inspect']:
            if '--format' in argv:
                return str(data_directory)
            return json.dumps(volume_rows[argv[-1]])
        if argv[1:3] == ['volume', 'rm']:
            return argv[-1]
        if argv[1:3] == ['volume', 'create']:
            return argv[-1]
        raise AssertionError(argv)

    monkeypatch.setattr(linux, '_command', command)
    receipt = effects.reset_test_source_projection(request)

    assert receipt.terminal_result == 'failed'
    assert any(
        argv[:4] == ['docker', 'volume', 'create', '--driver'] and argv[-1] == 'pkm-test_pgdata'
        for argv in commands
    )
    assert effects.database_fields == expected_fields

    # The recreated external volume is now a valid empty local target: the
    # normal production initializer may bootstrap it and Compose can inspect
    # the external volume before starting db.
    effects.local_database = lambda: True
    effects.database_fields = {'host': 'db', 'port': '5432', 'user': 'app', 'dbname': 'app_test'}
    effects.compose = lambda *args: '' if args == ('ps', '--all', '-q', 'db') else pytest.fail(args)
    assert effects.initialized() is False


def test_test_recovery_reset_refuses_external_database_before_mutation(tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, PostgresDeployError, TestRecoveryRequest,
    )

    operation_id = str(uuid4())
    plan = DeployPlan('test', 'b' * 40, ('db',), ('postgres-db',), image_digest='sha256:' + '2' * 64,
                      automatic=True)
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')

    class Journal:
        directory = tmp_path / 'journal'
        channel = 'test'

        def read(self):
            raise AssertionError('external target must be refused before journal inspection')

    effects = linux.LinuxEffects(SimpleNamespace(channel='test', root=tmp_path, journal=Journal()))
    effects.local_database = lambda: False
    request = TestRecoveryRequest(operation_id, plan, authority)
    with pytest.raises(PostgresDeployError):
        effects.reset_test_source_projection(request)
    assert not effects._test_recovery_disposition_path(request).exists()


def test_source_projection_refusal_retains_authenticated_recoverable_state(tmp_path, monkeypatch):
    import threading
    from dataclasses import asdict
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError

    root = tmp_path / 'checkout'
    lock_dir = root / 'config/deploy/test.env.lock'
    lock_dir.mkdir(parents=True, mode=0o700)
    (lock_dir / 'bws-owner').touch(mode=0o600)
    journal = DeployJournal(tmp_path / 'journal', 'test')
    operation_id = str(uuid4())
    plan = DeployPlan('test', 'e' * 40, ('db',), ('postgres-db',))
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(operation_id, stage)
    config = SimpleNamespace(channel='test', root=root, journal=journal)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    supervisor = linux.DeploymentSupervisor(config)
    not_ready = threading.Event()
    supervisor.operation = SimpleNamespace(
        operation_id=operation_id, plan=plan, bootstrap=False, failed=False,
        finished=not_ready, thread=SimpleNamespace(is_alive=lambda: True),
    )
    request = {
        'action': 'reconcile-failed', 'operation_id': operation_id,
        'plan': asdict(plan), 'bootstrap': False,
    }
    with pytest.raises(PostgresDeployError):
        supervisor.request(request)
    assert journal.read().stage == 'activating'
    assert journal.read().terminal_result is None
    assert lock_dir.is_dir()


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
    assert supervisor.request(request)['receipt'] == receipt.payload()
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
    plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), ack_forward_only,
    )
    journal.bind_request(operation_id, plan, False, create=True)
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
    kwargs['retain_source_failure']('embedding_probe_cleanup_failed')
    assert journal.read().source_failure == 'embedding_probe_cleanup_failed'
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


@pytest.mark.parametrize("hostile_marker,expected_stage,sink", [
    ("", "service_recreate", "ready"),
    ("YGGDRASIL_DEPLOY_FAILURE_STAGE=service_recreate secret-canary", "unknown", "ready"),
    ("YGGDRASIL_DEPLOY_FAILURE_STAGE=https://private.invalid/secret-canary", "unknown", "ready"),
    ("YGGDRASIL_DEPLOY_FAILURE_STAGE=committed", "unknown", "ready"),
    ("YGGDRASIL_DEPLOY_FAILURE_STAGE=health", "unknown", "ready"),
    ("INVALID_UTF8", "unknown", "ready"),
    ("", "service_recreate", "missing"),
    ("", "service_recreate", "refused"),
    ("", "service_recreate", "full"),
])
def test_supervised_failure_diagnostics_expose_only_allowlisted_stage(
    tmp_path: Path, hostile_marker: str, expected_stage: str, sink: str,
) -> None:
    from app.ops.postgres_deploy import DeployJournal

    unit = (REPO_ROOT / "config/systemd/yggdrasil-bws-deploy@.service").read_text().splitlines()
    assert "StandardOutput=null" in unit
    assert "StandardError=null" in unit
    root, env, previous_sha = _deploy_harness(tmp_path)
    target_sha = _commit_prefloor_successor(root, "native failed-child diagnostic")
    _seed_previous_pin(root, previous_sha)
    env.update(FAKE_SHA=target_sha, FAKE_DOCKER_FAIL_MATCH="up -d --force-recreate api worker watcher",
               FAKE_DEPLOY_HOSTILE_MARKER=hostile_marker)
    # Compose already captures its own command diagnostics. Inject hostile
    # captured child streams at the script boundary that the adapter reads.
    script = root / "scripts/deploy_channel.sh"
    injection = '''printf '%s\\n' 'raw-stdout-canary'
printf '%s\\n' 'postgresql://fixture:secret-canary@private.invalid/db /private/fixture' >&2
if [ "${FAKE_DEPLOY_HOSTILE_MARKER:-}" = "INVALID_UTF8" ]; then
  printf 'YGGDRASIL_DEPLOY_FAILURE_STAGE=\\377\\n' >&2
elif [ -n "${FAKE_DEPLOY_HOSTILE_MARKER:-}" ]; then
  printf '%s\\n' "$FAKE_DEPLOY_HOSTILE_MARKER" >&2
fi
'''
    script.write_text(script.read_text().replace("set -euo pipefail\n", "set -euo pipefail\n" + injection, 1))
    source = tmp_path / "private-handles"
    source.mkdir()
    journal_dir = tmp_path / "journal"
    journal = DeployJournal(journal_dir, "dev")
    child = '''import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4
from app.ops import postgres_deploy_linux as linux
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.postgres_deploy import DeployJournal, DeployPlan, DeployWorker, PostgresDeployError
root, journal_socket, revision, source, journal_dir = sys.argv[1:6]
linux._DEPLOY_JOURNAL_SOCKET = journal_socket  # private test seam, no runtime selector
journal = DeployJournal(Path(journal_dir), "dev")
effects = linux.LinuxEffects(SimpleNamespace(channel="dev", root=Path(root),
                                            source_directory=Path(source), journal=journal))
effects.source = SimpleNamespace(verify=lambda: None)
effects.environment = lambda: os.environ.copy()
effects.active_consumers = (*DATABASE_CONSUMERS, "heimdal-api-ingress")
effects.consumer_values = {"heimdal-api-ingress": {}, "heimdal-capture-watch": {}, "heimdal-raw-migrate": {}}
effects.preflight = lambda _plan: "synthetic-postgres-canary"
effects.initialized = lambda: False
effects.materialize = lambda _password: None
effects.quiescent = lambda: True
plan = DeployPlan("dev", revision, tuple(DATABASE_CONSUMERS.values()),
                  (*DATABASE_CONSUMERS, "heimdal-api-ingress"))
operation_id = str(uuid4())
journal.bind_request(operation_id, plan, False, create=True)
worker = DeployWorker(journal, effects)
with (Path(source).parent / "lock-handle").open("w") as lock:
    effects.lock_fd = lock.fileno()
    worker.prepare(operation_id)
    try:
        worker.run(operation_id, plan)
    except PostgresDeployError:
        raise SystemExit(73)
raise SystemExit(99)
'''
    # Short private paths satisfy the platform Unix-socket address limit.
    with tempfile.TemporaryDirectory(prefix="j5915-", dir="/tmp") as socket_dir:
        journal_socket = Path(socket_dir) / "journal.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver, ExitStack() as fillers:
            if sink in {"ready", "full"}:
                receiver.bind(str(journal_socket))
            elif sink == "refused":
                journal_socket.touch()
            prefill = b"queue-prefill"
            if sink == "full":
                receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                # A sender can exhaust its own buffer before the receiver is
                # full. Retain each sender and require a fresh empty sender to
                # fail its first send, as the native emitter must do below.
                for _ in range(64):
                    filler = fillers.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM))
                    filler.setblocking(False)
                    for sent in range(4096):
                        try:
                            filler.sendto(prefill, str(journal_socket))
                        except OSError as error:
                            assert error.errno in {errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS}
                            break
                    else:
                        pytest.fail("private datagram sender did not saturate")
                    if sent == 0:
                        break
                else:
                    pytest.fail("private datagram receiver did not saturate for a fresh sender")
            result = subprocess.run(
                [sys.executable, "-c", child, str(root), str(journal_socket), target_sha,
                 str(source), str(journal_dir), "argv-secret-canary"],
                cwd=REPO_ROOT, env={**env, "ENV_SECRET_CANARY": "env-secret-canary"},
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False, timeout=20,
            )
            assert result.returncode == 73
            if sink == "ready":
                receiver.settimeout(2)
                payload = receiver.recv(4096)
                assert payload == (
                    "PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n"
                    f"MESSAGE=native deployment failure: stage={expected_stage} class=command_failed\n"
                ).encode("ascii")
                receiver.settimeout(0.05)
                with pytest.raises(socket.timeout):
                    receiver.recv(4096)  # exactly one event, no retry
            elif sink == "full":
                receiver.setblocking(False)
                while True:
                    try:
                        assert receiver.recv(4096) == prefill
                    except BlockingIOError:
                        break
    assert journal.read().stage == "activating"
    assert journal.read().terminal_result is None
    assert list(source.iterdir()) == []


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
    monkeypatch.setattr(effects, '_running_one_shots', lambda: False)
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
    monkeypatch.setattr(linux.LinuxEffects, '_running_one_shots', lambda _self: False)
    supervisor = linux.DeploymentSupervisor(config)

    request = {
        'action': 'reconcile-failed', 'operation_id': operation_id,
        'plan': asdict(plan), 'bootstrap': False,
    }
    def source_absent(argv, **kwargs):
        assert argv == ['docker', 'ps', '--all', '--filter',
                        f'name=^/pkm-test-source-bootstrap-{operation_id}$', '--format', '{{.ID}}']
        assert kwargs == {'timeout': 15}
        return ''

    monkeypatch.setattr(linux, '_command', source_absent)
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
    monkeypatch.setattr(linux.LinuxEffects, '_running_one_shots', lambda _self: False)
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
    monkeypatch.setattr(
        host, '_configured_deploy_admin',
        lambda _plan, selected: Admin(None, controller=selected),
    )
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


def test_ssh_test_recovery_reset_sends_exact_candidate_operation_authority(monkeypatch):
    import json
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, DeployReceipt, TestRecoveryRequest

    operation_id = str(uuid4())
    plan = DeployPlan(
        'test', 'f' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + '3' * 64, True,
    )
    authority = AuthorityCutover('test-binding', '/srv/ygg/test-vault', '/srv/ygg/test-state')
    request = TestRecoveryRequest(operation_id, plan, authority)
    calls = []
    response = {
        'recovery': 'test-derived-reset-complete',
        'receipt': {
            **DeployReceipt(
                operation_id, 'test', 'deploy', 'failed', 'failed',
                source_failure='legacy_identity_persistence_refused',
            ).payload(),
        },
    }

    def ssh(argv, **kwargs):
        calls.append((argv, json.loads(kwargs['input'])))
        return SimpleNamespace(returncode=0, stdout=json.dumps(response))

    monkeypatch.setattr(linux.subprocess, 'run', ssh)
    receipt = linux.SshDeployRemote('ygg-test').test_recovery_reset(request)
    assert receipt.operation_id == operation_id
    assert calls[0][0][-2:] == ['rpc', 'test']
    assert calls[0][1] == json.loads(json.dumps({'action': 'test-recovery-reset', **request.payload()}))


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


def test_operator_identity_restoration_owner_is_dev_only_and_typed(tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops.postgres_deploy import PostgresDeployError
    from app.ops.postgres_deploy_linux import LinuxEffects

    operation_id = str(uuid4())

    def effects_for(channel: str, suffix: str):
        root = tmp_path / suffix
        (root / 'config/deploy').mkdir(parents=True)
        journal = SimpleNamespace(channel=channel, directory=root / 'journal', read=lambda: None)
        effects = LinuxEffects(SimpleNamespace(root=root, channel=channel, journal=journal))
        effects.operation_id = operation_id
        return effects, journal

    effects, journal = effects_for('dev', 'accepted')
    owner = {
        'kind': 'operator-identity-restoration',
        'channel': 'dev',
        'operation_id': operation_id,
    }
    with effects.channel_lock(journal=journal, owner_marker=owner, retire_terminal=False):
        assert effects.channel_lock_owner() == (json.dumps(owner, sort_keys=True) + '\n').encode()

    for channel, marker in (
        ('test', {**owner, 'channel': 'test'}),
        ('dev', {**owner, 'kind': 'operator-identity-restoration-other'}),
        ('dev', {**owner, 'unexpected': 'field'}),
    ):
        candidate, candidate_journal = effects_for(channel, channel + marker.get('kind', 'malformed'))
        with pytest.raises(PostgresDeployError):
            with candidate.channel_lock(
                journal=candidate_journal, owner_marker=marker, retire_terminal=False,
            ):
                pass


def _operator_restoration_effects(tmp_path, worker_receipt):
    from types import SimpleNamespace

    operation_id = worker_receipt['operation_id']
    writers = ('api', 'watcher', 'worker')

    class Effects:
        def __init__(self):
            directory = tmp_path / 'journal'
            directory.mkdir(parents=True)
            self.config = SimpleNamespace(
                channel='dev', uid=1000, gid=1000,
                journal=SimpleNamespace(directory=directory),
            )
            self.operation_id = None
            self.owner = None
            self.running = writers
            self.calls = []

        def qualify_source_identity_authority(self, *_args):
            return SimpleNamespace()

        def source_identity_runtime_snapshot(self, _selected, *, require_running_capture):
            if require_running_capture and not self.running:
                raise AssertionError('running writers required')
            return SimpleNamespace(
                installed_fingerprint='installed',
                observed_installed_fingerprint='installed',
                legacy_installed_fingerprints=frozenset(),
                execution_fingerprint='execution',
                existing_writers=writers,
                running_writers=self.running,
                container_root='/app/vault',
                vault_overlay='docker-compose.full-host-vault.yml',
                child_environment=(('DATABASE_URL_FILE', '/run/secrets/db'),),
                unset_environment=('DATABASE_URL',),
            )

        def require_source_identity_candidate(self, *_args, **_kwargs):
            return None

        @contextmanager
        def channel_lock(self, *, journal, owner_marker, retire_terminal):
            assert journal is self.config.journal and retire_terminal is False
            self.owner = (json.dumps(owner_marker, sort_keys=True) + '\n').encode()
            yield

        def channel_lock_owner(self):
            return self.owner

        @contextmanager
        def failed_reconciliation_lock(self, *, expected_owner):
            assert self.owner == (json.dumps(expected_owner, sort_keys=True) + '\n').encode()
            yield object()

        def retire_reconciled_channel_lock(self, _handle, *, expected_owner):
            assert self.owner == (json.dumps(expected_owner, sort_keys=True) + '\n').encode()
            self.owner = None

        def compose(self, action, *args, input_text=None, **_kwargs):
            self.calls.append((action, args, input_text))
            if action == 'stop':
                self.running = ()
                return ''
            if action == 'start':
                self.running = writers
                return ''
            assert action == 'run'
            attempt = self.config.journal.directory / (
                f'dev-operator-identity-restoration-{operation_id}.attempt.json'
            )
            assert attempt.exists()
            assert input_text is not None and 'target_rel' in json.loads(input_text)
            return json.dumps(worker_receipt)

    return Effects()


def test_operator_identity_restoration_fences_and_restores_exact_writers(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import native_source_bootstrap
    from app.ops.native_operator_identity_restoration import run_host_operation

    operation_id = str(uuid4())
    revision = 'a' * 40
    worker = {
        'contract': 'native-operator-identity-restoration.v1',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision,
        'result': 'unknown', 'write_phase': 'written', 'cleanup': 'not_started',
        'reason': None, 'automatic_producer_started': False,
        'automatic_deployment_started': False,
    }
    effects = _operator_restoration_effects(tmp_path, worker)
    monkeypatch.setattr(native_source_bootstrap, 'quiesce_owned_container', lambda *_args: True)
    selected = SimpleNamespace(
        binding_id='vault-alpha', root='/srv/vault', ownership_root='/srv/state',
        validate=lambda: None,
    )
    receipt = run_host_operation(
        effects, operation_id=operation_id, revision=revision,
        image_digest='sha256:' + '1' * 64, selected=selected,
        command={
            'target_rel': 'rewritten/target.md',
            'expected_old_scalar': 'legacy-identity',
            'replacement_uuid': str(uuid4()),
        },
    )
    assert receipt['result'] == 'committed'
    assert [call[0] for call in effects.calls] == ['stop', 'run', 'start']
    assert effects.running == ('api', 'watcher', 'worker') and effects.owner is None
    request = json.loads(next(effects.config.journal.directory.glob('*.request.json')).read_text())
    assert 'command' not in request and len(request['command_sha256']) == 64


def test_operator_identity_restoration_write_phase_and_cleanup_only_recovery(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import native_source_bootstrap
    from app.ops.native_operator_identity_restoration import run_host_operation, validate_receipt

    operation_id = str(uuid4())
    revision = 'b' * 40
    worker = {
        'contract': 'native-operator-identity-restoration.v1',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision,
        'result': 'unknown', 'write_phase': 'indeterminate', 'cleanup': 'not_started',
        'reason': 'worker_transport_failed', 'automatic_producer_started': False,
        'automatic_deployment_started': False,
    }
    effects = _operator_restoration_effects(tmp_path, worker)
    monkeypatch.setattr(native_source_bootstrap, 'quiesce_owned_container', lambda *_args: True)
    selected = SimpleNamespace(
        binding_id='vault-alpha', root='/srv/vault', ownership_root='/srv/state',
        validate=lambda: None,
    )
    command = {
        'target_rel': 'rewritten/target.md',
        'expected_old_scalar': 'legacy-identity',
        'replacement_uuid': str(uuid4()),
    }
    first = run_host_operation(
        effects, operation_id=operation_id, revision=revision,
        image_digest='sha256:' + '2' * 64, selected=selected, command=command,
    )
    assert first['write_phase'] == 'indeterminate' and first['result'] == 'unknown'
    run_calls = sum(call[0] == 'run' for call in effects.calls)
    second = run_host_operation(
        effects, operation_id=operation_id, revision=revision,
        image_digest='sha256:' + '2' * 64, selected=selected, command=command,
    )
    assert second == first
    assert sum(call[0] == 'run' for call in effects.calls) == run_calls
    for phase in ('not_started', 'not_written', 'written', 'indeterminate'):
        payload = {**worker, 'write_phase': phase}
        if phase == 'written':
            payload['reason'] = None
        assert validate_receipt(payload)['write_phase'] == phase


def test_operator_identity_restoration_request_only_crash_cleans_without_dispatch(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import native_source_bootstrap
    from app.ops.native_operator_identity_restoration import run_host_operation
    from app.ops.postgres_deploy import PostgresDeployError

    operation_id = str(uuid4())
    revision = 'c' * 40
    command = {
        'target_rel': 'rewritten/target.md',
        'expected_old_scalar': 'legacy-identity',
        'replacement_uuid': str(uuid4()),
    }
    worker = {
        'contract': 'native-operator-identity-restoration.v1',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision,
        'result': 'unknown', 'write_phase': 'written', 'cleanup': 'not_started',
        'reason': None, 'automatic_producer_started': False,
        'automatic_deployment_started': False,
    }
    effects = _operator_restoration_effects(tmp_path, worker)
    selected = SimpleNamespace(
        binding_id='vault-alpha', root='/srv/vault', ownership_root='/srv/state',
        validate=lambda: None,
    )
    command_hash = hashlib.sha256(
        json.dumps(command, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    request = {
        'contract': 'native-operator-identity-restoration-request.v1',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision,
        'image_digest': 'sha256:' + '3' * 64,
        'authority_cutover': {
            'binding_id': selected.binding_id, 'root': selected.root,
            'ownership_root': selected.ownership_root,
        },
        'installed_fingerprint': 'installed',
        'execution_fingerprint': 'execution',
        'writers': ['api', 'watcher', 'worker'],
        'container_root': '/app/vault',
        'vault_overlay': 'docker-compose.full-host-vault.yml',
        'command_sha256': command_hash,
    }
    request_path = effects.config.journal.directory / (
        f'dev-operator-identity-restoration-{operation_id}.request.json'
    )
    request_path.write_text(json.dumps(request), encoding='utf-8')
    request_path.chmod(0o600)
    owner = {
        'kind': 'operator-identity-restoration', 'channel': 'dev',
        'operation_id': operation_id,
    }
    effects.owner = (json.dumps(owner, sort_keys=True) + '\n').encode()
    monkeypatch.setattr(native_source_bootstrap, 'quiesce_owned_container', lambda *_args: True)
    with pytest.raises(PostgresDeployError):
        run_host_operation(
            effects, operation_id=operation_id, revision=revision,
            image_digest='sha256:' + '3' * 64, selected=selected, command=command,
        )
    assert [call[0] for call in effects.calls] == ['start']
    assert effects.owner is None


def test_operator_identity_restoration_written_evidence_commits_after_later_cleanup(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import native_source_bootstrap
    from app.ops.native_operator_identity_restoration import run_host_operation

    operation_id = str(uuid4())
    revision = 'd' * 40
    worker = {
        'contract': 'native-operator-identity-restoration.v1',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision,
        'result': 'unknown', 'write_phase': 'written', 'cleanup': 'not_started',
        'reason': None, 'automatic_producer_started': False,
        'automatic_deployment_started': False,
    }
    effects = _operator_restoration_effects(tmp_path, worker)
    selected = SimpleNamespace(
        binding_id='vault-alpha', root='/srv/vault', ownership_root='/srv/state',
        validate=lambda: None,
    )
    command = {
        'target_rel': 'rewritten/target.md',
        'expected_old_scalar': 'legacy-identity',
        'replacement_uuid': str(uuid4()),
    }
    quiesced = {'value': False}
    monkeypatch.setattr(
        native_source_bootstrap, 'quiesce_owned_container',
        lambda *_args: quiesced['value'],
    )
    first = run_host_operation(
        effects, operation_id=operation_id, revision=revision,
        image_digest='sha256:' + '4' * 64, selected=selected, command=command,
    )
    assert first['result'] == 'unknown' and first['cleanup'] == 'retained'
    quiesced['value'] = True
    second = run_host_operation(
        effects, operation_id=operation_id, revision=revision,
        image_digest='sha256:' + '4' * 64, selected=selected, command=command,
    )
    assert second['result'] == 'committed'
    assert second['write_phase'] == 'written' and second['cleanup'] == 'complete'
    assert sum(call[0] == 'run' for call in effects.calls) == 1


def test_operator_identity_restoration_orphan_dangling_and_foreign_lineage_refuse(
    tmp_path,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops.native_operator_identity_restoration import run_host_operation
    from app.ops.postgres_deploy import PostgresDeployError

    operation_id = str(uuid4())
    revision = 'e' * 40
    command = {
        'target_rel': 'rewritten/target.md',
        'expected_old_scalar': 'legacy-identity',
        'replacement_uuid': str(uuid4()),
    }
    worker = {
        'contract': 'native-operator-identity-restoration.v1',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision,
        'result': 'unknown', 'write_phase': 'not_written', 'cleanup': 'not_started',
        'reason': 'worker_refused', 'automatic_producer_started': False,
        'automatic_deployment_started': False,
    }
    selected = SimpleNamespace(
        binding_id='vault-alpha', root='/srv/vault', ownership_root='/srv/state',
        validate=lambda: None,
    )

    def invoke(effects):
        return run_host_operation(
            effects, operation_id=operation_id, revision=revision,
            image_digest='sha256:' + '5' * 64, selected=selected, command=command,
        )

    orphan = _operator_restoration_effects(tmp_path / 'orphan', worker)
    prefix = f'dev-operator-identity-restoration-{operation_id}'
    for suffix, payload in (
        ('.attempt.json', {
            'contract': 'native-operator-identity-restoration-attempt.v1',
            'operation_id': operation_id, 'dispatch_staged': True,
        }),
        ('.worker.json', worker),
    ):
        path = orphan.config.journal.directory / (prefix + suffix)
        path.write_text(json.dumps(payload), encoding='utf-8')
        path.chmod(0o600)
    with pytest.raises(PostgresDeployError):
        invoke(orphan)
    assert orphan.calls == [] and orphan.owner is None

    dangling = _operator_restoration_effects(tmp_path / 'dangling', worker)
    (dangling.config.journal.directory / (prefix + '.request.json')).symlink_to(
        dangling.config.journal.directory / 'missing-private-entry'
    )
    with pytest.raises(Exception):
        invoke(dangling)
    assert dangling.calls == [] and dangling.owner is None

    foreign = _operator_restoration_effects(tmp_path / 'foreign', worker)
    command_hash = hashlib.sha256(
        json.dumps(command, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    request = {
        'contract': 'native-operator-identity-restoration-request.v1',
        'operation_id': operation_id, 'channel': 'dev', 'revision': revision,
        'image_digest': 'sha256:' + '5' * 64,
        'authority_cutover': {
            'binding_id': selected.binding_id, 'root': selected.root,
            'ownership_root': selected.ownership_root,
        },
        'installed_fingerprint': 'installed', 'execution_fingerprint': 'execution',
        'writers': ['api', 'watcher', 'worker'], 'container_root': '/app/vault',
        'vault_overlay': 'docker-compose.full-host-vault.yml',
        'command_sha256': command_hash,
    }
    path = foreign.config.journal.directory / (prefix + '.request.json')
    path.write_text(json.dumps(request), encoding='utf-8')
    path.chmod(0o600)
    foreign.owner = b'foreign-owner\n'
    with pytest.raises(PostgresDeployError):
        invoke(foreign)
    assert foreign.calls == [] and foreign.owner == b'foreign-owner\n'

    poison = _operator_restoration_effects(tmp_path / 'phase-poison', worker)
    request_path = poison.config.journal.directory / (prefix + '.request.json')
    request_path.write_text(json.dumps(request), encoding='utf-8')
    request_path.chmod(0o600)
    terminal = {**worker, 'write_phase': 'indeterminate', 'cleanup': 'retained'}
    terminal_path = poison.config.journal.directory / (prefix + '.json')
    terminal_path.write_text(json.dumps(terminal), encoding='utf-8')
    terminal_path.chmod(0o600)
    with pytest.raises(PostgresDeployError):
        invoke(poison)
    assert poison.calls == [] and poison.owner is None


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


def test_linux_recovery_compose_binds_authenticated_cutover_ownership_root(tmp_path, monkeypatch):
    """The recovery one-shot cannot inherit an ambient host-global root."""
    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan

    cfg = linux.LinuxConfig('test', tmp_path, tmp_path / 'data', 1000, 1000, '', '')
    (tmp_path / 'config/deploy').mkdir(parents=True)
    (tmp_path / 'config/deploy/test.env').write_text('APP_IMAGE_TAG=' + 'a' * 40 + '\n')
    monkeypatch.delenv('INSTANCE_OWNERSHIP_HOST_STATE_DIR', raising=False)
    commands, environments = [], []

    def command(argv, **kwargs):
        commands.append(argv)
        environments.append(kwargs['env'])
        return ''

    monkeypatch.setattr(linux, '_command', command)
    cutover = AuthorityCutover(
        'test-binding', str(tmp_path / 'vault'), str(tmp_path / 'authenticated-ownership'),
    )
    candidate = DeployPlan(
        'test', 'b' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'c' * 64, True,
    )
    linux.LinuxEffects(cfg).compose(
        'run', 'instance-state-init', cutover=cutover, candidate=candidate,
    )

    assert len(commands) == 1
    assert environments[0]['INSTANCE_OWNERSHIP_HOST_STATE_DIR'] == cutover.ownership_root
    assert environments[0]['APP_IMAGE_TAG'] == candidate.revision
    assert environments[0]['APP_IMAGE_DIGEST_SUFFIX'] == '@' + candidate.image_digest


def test_linux_recovery_prepares_new_volume_before_runtime_uid(monkeypatch, tmp_path):
    """A fresh named volume is permission-prepared before reconstruction."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, TestRecoveryRequest

    operation_id = str(uuid4())
    source_operation_id = str(uuid4())
    digest = 'sha256:' + 'a' * 64
    plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False, digest, True,
    )
    cutover = AuthorityCutover(
        'test-binding', str(tmp_path / 'vault'), str(tmp_path / 'authenticated-ownership'),
    )
    request = TestRecoveryRequest(
        operation_id, plan, cutover, source_operation_id=source_operation_id,
        source_plan=plan,
    )
    config = SimpleNamespace(channel='test', root=tmp_path, uid=1000, journal=object())
    effects = linux.LinuxEffects(config)
    effects.local_database = lambda: True
    effects._write_test_instance_state_recovery_receipt = lambda _request: (
        tmp_path / 'receipt.json', 'a' * 64, 'b' * 64, 'c' * 64,
    )
    effects.recovery_quiescent = lambda: True
    effects._validate_test_instance_state_recovery_authority = (
        lambda *_args, **_kwargs: 'c' * 64
    )
    calls = []

    def compose(*args, **kwargs):
        calls.append((args, kwargs))
        if '--user' in args:
            return json.dumps({
                'schema': 'test-instance-state-recovery.v2',
                'channel': 'test',
                'activation': 'inactive_fenced',
                'request': {
                    'source_operation_id': source_operation_id,
                    'failed_successor_operation_id': operation_id,
                },
                'ledger_sha256': 'c' * 64,
            })
        return ''

    effects.compose = compose
    assert effects.reconstruct_missing_test_instance_state(request)['activation'] == 'inactive_fenced'

    assert calls[0][0] == ('run', '--rm', '--no-deps', '-T', 'instance-state-init')
    assert '--user' not in calls[0][0]
    assert '--user' in calls[1][0]
    assert calls[0][1]['cutover'] == cutover
    assert calls[1][1]['cutover'] == cutover
    assert calls[0][1]['candidate'] == plan
    assert calls[1][1]['candidate'] == plan


def test_linux_recovery_releases_authenticated_lease_after_durable_result(tmp_path):
    """Lease handoff reuses the exact reconstruction evidence and controller."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, TestRecoveryRequest

    failed_operation_id = str(uuid4())
    source_operation_id = str(uuid4())
    ownership_root = tmp_path / 'ownership'
    ownership_root.mkdir(mode=0o700)
    public_root = ownership_root / 'deployment-public'
    public_root.mkdir(mode=0o700)
    plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'b' * 64, True,
    )
    authority = AuthorityCutover('test-binding', str(tmp_path / 'vault'), str(ownership_root))
    request = TestRecoveryRequest(
        failed_operation_id, plan, authority,
        source_operation_id=source_operation_id, source_plan=plan,
    )
    proof = {
        'channel_id': 'test',
        'nonce': 'n' * 32,
        'controller': {'pid': 4242, 'start_token': 'linux:' + 'c' * 64},
    }
    proof_path = ownership_root / 'deployment-quiescence-proof.json'
    proof_path.write_text(json.dumps(proof, sort_keys=True) + '\n', encoding='utf-8')
    proof_path.chmod(0o600)
    owner = {
        'deployment_nonce': proof['nonce'],
        'controller': proof['controller'],
    }
    owner_path = ownership_root / 'legacy-owner-inventory.json'
    owner_path.write_text(json.dumps(owner, sort_keys=True) + '\n', encoding='utf-8')
    owner_path.chmod(0o600)
    receipt = {
        'schema': 'test-instance-state-recovery.v2',
        'channel': 'test',
        'source_operation_id': source_operation_id,
        'failed_successor_operation_id': failed_operation_id,
        'candidate_revision': plan.revision,
        'candidate_image_digest': plan.image_digest,
        'authority_cutover': {
            'binding_id': authority.binding_id,
            'root': authority.root,
            'ownership_root': authority.ownership_root,
        },
        'disposition': 'complete',
        'owner_receipt_sha256': hashlib.sha256(owner_path.read_bytes()).hexdigest(),
        'quiescence_proof_sha256': hashlib.sha256(proof_path.read_bytes()).hexdigest(),
        'ledger_sha256': 'e' * 64,
    }
    receipt_path = ownership_root / (
        'test-instance-state-recovery-' + failed_operation_id + '.json'
    )
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + '\n', encoding='utf-8')
    receipt_path.chmod(0o600)
    result_path = ownership_root / (
        'test-instance-state-recovery-result-' + failed_operation_id + '.json'
    )
    result_path.write_text(json.dumps({
        'schema': 'test-instance-state-recovery.v2',
        'channel': 'test',
        'request': receipt,
        'registry_revision': 1,
        'registry_sha256': 'f' * 64,
        'ledger_sha256': receipt['ledger_sha256'],
        'activation': 'inactive_fenced',
        'registered_bindings': [authority.binding_id],
    }, sort_keys=True) + '\n', encoding='utf-8')
    result_path.chmod(0o600)
    (public_root / 'deployment-host-global-lease.json').write_text('{}\n')
    (ownership_root / 'deployment-host-global-lease.json').write_text('{}\n')
    (public_root / 'deployment-host-global-lease.json').chmod(0o600)
    (ownership_root / 'deployment-host-global-lease.json').chmod(0o600)

    config = SimpleNamespace(
        channel='test', root=tmp_path, uid=os.geteuid(), gid=os.getegid(), journal=object(),
    )
    effects = linux.LinuxEffects(config)
    effects.local_database = lambda: True
    effects.recovery_quiescent = lambda: True
    calls = []

    def compose(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps({
            'channel': 'test', 'released': True,
            'reason': 'abandoned-deployment',
        })

    effects.compose = compose
    released = effects.release_test_instance_state_recovery_lease(request)

    assert released['released'] is True
    assert len(calls) == 1
    assert calls[0][0][-4:] == (
        '--controller-pid', '4242', '--controller-start-token', 'linux:' + 'c' * 64,
    )
    assert calls[0][1] == {'cutover': authority, 'candidate': plan}

    cleanup_result = {
        'channel': 'test', 'restart_fence_cleared': True, 'aborted': True,
    }
    controller = proof['controller']
    public_cleanup = {
        'schema': 'agentic-pkm.host-deployment-lease.v3',
        'channel_id': 'test', 'nonce': 'n' * 32, 'phase': 'cleanup',
        'controller': controller, 'result': cleanup_result,
    }
    root_cleanup = {
        **public_cleanup,
        'schema': 'agentic-pkm.host-deployment-compatibility-block.v1',
        'compatibility_v3_nonce': 'n' * 32,
    }
    (public_root / 'deployment-host-global-lease.json').write_text(
        json.dumps(public_cleanup) + '\n', encoding='utf-8',
    )
    (ownership_root / 'deployment-host-global-lease.json').write_text(
        json.dumps(root_cleanup) + '\n', encoding='utf-8',
    )
    (public_root / 'deployment-host-global-lease.json').chmod(0o600)
    (ownership_root / 'deployment-host-global-lease.json').chmod(0o600)
    proof_path.unlink()
    effects.compose = lambda *_args, **_kwargs: json.dumps({
        **cleanup_result, 'released': True, 'reason': 'already-in-cleanup',
    })
    assert effects.release_test_instance_state_recovery_lease(request)['reason'] == (
        'already-in-cleanup'
    )

    (public_root / 'deployment-host-global-lease.json').unlink()
    assert effects.release_test_instance_state_recovery_lease(request)['reason'] == (
        'already-in-cleanup'
    )

    foreign_cleanup = {
        **public_cleanup,
        'nonce': 'x' * 32,
        'controller': {'pid': 4343, 'start_token': 'linux:' + 'f' * 64},
    }
    foreign_root_cleanup = {
        **foreign_cleanup,
        'schema': 'agentic-pkm.host-deployment-compatibility-block.v1',
        'compatibility_v3_nonce': 'x' * 32,
    }
    (ownership_root / 'deployment-host-global-lease.json').write_text(
        json.dumps(foreign_root_cleanup) + '\n', encoding='utf-8',
    )
    (ownership_root / 'deployment-host-global-lease.json').chmod(0o600)
    effects.compose = lambda *_args, **_kwargs: pytest.fail(
        'foreign root-only cleanup reached Compose'
    )
    with pytest.raises(linux.PostgresDeployError):
        effects.release_test_instance_state_recovery_lease(request)

    (public_root / 'deployment-host-global-lease.json').write_text(
        json.dumps(foreign_cleanup) + '\n', encoding='utf-8',
    )
    (public_root / 'deployment-host-global-lease.json').chmod(0o600)
    with pytest.raises(linux.PostgresDeployError):
        effects.release_test_instance_state_recovery_lease(request)

    (public_root / 'deployment-host-global-lease.json').unlink()
    (ownership_root / 'deployment-host-global-lease.json').unlink()
    effects.recovery_quiescent = lambda: False
    effects.compose = lambda *_args, **_kwargs: pytest.fail('idempotent release called Compose')
    assert effects.release_test_instance_state_recovery_lease(request) == {
        'channel': 'test', 'released': False,
        'reason': 'already-released-after-reconstruction',
    }


def test_linux_recovery_quiescence_rejects_running_state_writers(monkeypatch, tmp_path):
    """Healthy long-lived services are still writers during reconstruction."""
    from types import SimpleNamespace

    from app.ops import postgres_deploy_linux as linux

    effects = linux.LinuxEffects(SimpleNamespace(channel='test', root=tmp_path))
    effects._running_one_shots = lambda: False
    effects.compose = lambda *_args, **_kwargs: json.dumps([
        {'Service': service, 'State': 'running', 'Health': 'healthy'}
        for service in ('api', 'worker', 'watcher')
    ])

    assert effects.recovery_quiescent() is False


def test_linux_recovery_refuses_before_first_effect_when_writers_are_live(tmp_path):
    """The stopped-writer proof precedes receipt and Compose effects."""
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, PostgresDeployError, TestRecoveryRequest,
    )

    plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'a' * 64, True,
    )
    authority = AuthorityCutover(
        'test-binding', str(tmp_path / 'vault'), str(tmp_path / 'ownership'),
    )
    request = TestRecoveryRequest(
        str(uuid4()), plan, authority, source_operation_id=str(uuid4()),
        source_plan=plan,
    )
    effects = linux.LinuxEffects(SimpleNamespace(channel='test', root=tmp_path))
    effects.local_database = lambda: True
    effects.recovery_quiescent = lambda: False
    mutations = []
    effects._write_test_instance_state_recovery_receipt = (
        lambda _request: mutations.append('receipt')
    )
    effects.compose = lambda *_args, **_kwargs: mutations.append('compose') or ''

    with pytest.raises(PostgresDeployError):
        effects.reconstruct_missing_test_instance_state(request)
    assert mutations == []


def test_linux_recovery_rejects_active_supervised_operation(monkeypatch, tmp_path):
    """The reconstruction RPC cannot race a newly admitted deployment."""
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, PostgresDeployError

    plan = DeployPlan(
        'test', 'b' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'c' * 64, True,
    )
    authority = AuthorityCutover(
        'test-binding', str(tmp_path / 'vault'), str(tmp_path / 'authenticated-ownership'),
    )
    failed_operation_id = str(uuid4())
    source_operation_id = str(uuid4())
    config = SimpleNamespace(channel='test', root=tmp_path, journal=object())
    supervisor = linux.DeploymentSupervisor(config)
    active = linux.SupervisedOperation(
        linux.LinuxEffects(config), failed_operation_id, plan, False,
    )
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    monkeypatch.setattr(
        linux.LinuxEffects,
        'reconstruct_missing_test_instance_state',
        lambda *_args: pytest.fail('active deployment must block reconstruction'),
    )

    request = {
        'action': 'test-recovery-reconstruct-instance-state',
        **{
            'failed_operation_id': failed_operation_id,
            'source_operation_id': source_operation_id,
            'source_plan': plan.payload(),
            'plan': plan.payload(),
            'authority_cutover': {
                'binding_id': authority.binding_id,
                'root': authority.root,
                'ownership_root': authority.ownership_root,
            },
        },
    }
    foreign = linux.SupervisedOperation(
        linux.LinuxEffects(config), str(uuid4()), plan, False,
    )
    mismatched = linux.SupervisedOperation(
        linux.LinuxEffects(config), failed_operation_id,
        replace(plan, revision='d' * 40, image_digest='sha256:' + 'd' * 64), False,
    )
    for operation in (foreign, mismatched):
        operation.failed = True
        operation.finished.set()
    for operation in (active, foreign, mismatched):
        supervisor.operation = operation
        with pytest.raises(PostgresDeployError):
            supervisor.request(request)


def test_linux_recovery_accepts_runtime_owned_receipt_under_root_supervisor(monkeypatch, tmp_path):
    """A retry accepts the runtime-owned checkpoint after permission preparation."""
    import hashlib
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployPlan, DeployReceipt, TestRecoveryRequest,
    )

    operation_id = str(uuid4())
    source_operation_id = str(uuid4())
    authority = AuthorityCutover(
        'test-binding', str(tmp_path / 'vault'), str(tmp_path / 'authenticated-ownership'),
    )
    ownership_root = Path(authority.ownership_root)
    ownership_root.mkdir(mode=0o700)
    owner_bytes = b'{"owner":"runtime"}\n'
    proof_bytes = b'{"proof":"quiescent"}\n'
    (ownership_root / 'legacy-owner-inventory.json').write_bytes(owner_bytes)
    (ownership_root / 'deployment-quiescence-proof.json').write_bytes(proof_bytes)
    plan = DeployPlan(
        'test', 'd' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'e' * 64, True,
    )
    request = TestRecoveryRequest(
        operation_id, plan, authority, source_operation_id=source_operation_id,
        source_plan=replace(plan, revision='c' * 40, image_digest='sha256:' + 'd' * 64),
    )

    class Journal:
        def read(self):
            return DeployReceipt(operation_id, 'test', 'deploy', 'failed', 'failed')

        def bound_plan(self, selected):
            assert selected == operation_id
            return plan

    config = SimpleNamespace(
        channel='test', uid=os.geteuid(), gid=os.getegid(), journal=Journal(), root=tmp_path,
    )
    effects = linux.LinuxEffects(config)
    monkeypatch.setattr(effects, '_read_test_recovery_disposition', lambda _request: {'state': 'complete'})
    monkeypatch.setattr(
        effects, '_validate_test_instance_state_recovery_authority',
        lambda *_args, **_kwargs: 'f' * 64,
    )
    effects.recovery_quiescent = lambda: True
    receipt_path = ownership_root / ('test-instance-state-recovery-' + operation_id + '.json')
    payload = {
        'schema': 'test-instance-state-recovery.v2',
        'channel': 'test',
        'source_operation_id': source_operation_id,
        'failed_successor_operation_id': operation_id,
        'candidate_revision': plan.revision,
        'candidate_image_digest': plan.image_digest,
        'authority_cutover': {
            'binding_id': authority.binding_id,
            'root': authority.root,
            'ownership_root': authority.ownership_root,
        },
        'disposition': 'complete',
        'owner_receipt_sha256': hashlib.sha256(owner_bytes).hexdigest(),
        'quiescence_proof_sha256': hashlib.sha256(proof_bytes).hexdigest(),
        'ledger_sha256': 'f' * 64,
    }
    receipt_path.write_text(json.dumps(payload, sort_keys=True) + '\n')
    receipt_path.chmod(0o600)
    monkeypatch.setattr(linux.os, 'geteuid', lambda: 0)

    result = effects._write_test_instance_state_recovery_receipt(request)
    assert result == (
        receipt_path,
        hashlib.sha256(owner_bytes).hexdigest(),
        hashlib.sha256(proof_bytes).hexdigest(),
        'f' * 64,
    )
    assert receipt_path.stat().st_uid == config.uid


def test_linux_reconstruction_uses_retained_reset_request_after_journal_rollover(
    monkeypatch, tmp_path,
):
    """The single-slot journal authenticates the failed successor, not history."""
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.postgres_deploy import (
        AuthorityCutover, DeployJournal, DeployPlan, PostgresDeployError,
        TestRecoveryRequest,
    )

    source_operation_id = str(uuid4())
    failed_successor_operation_id = str(uuid4())
    authority = AuthorityCutover(
        'test-binding', str(tmp_path / 'vault'), str(tmp_path / 'ownership'),
    )
    source_request_plan = DeployPlan(
        'test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
        (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), False,
        'sha256:' + 'a' * 64, True,
    )
    source_cutover_plan = replace(
        source_request_plan, automatic=False, image_digest=None,
        ack_forward_only=True, authority_cutover=authority,
    )
    fresh_candidate = replace(
        source_request_plan, revision='b' * 40,
        image_digest='sha256:' + 'b' * 64,
    )
    journal = DeployJournal(tmp_path / 'journal', 'test')

    def fail_operation(operation_id, plan):
        journal.bind_request(operation_id, plan, False, create=True)
        for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'failed'):
            journal.write(operation_id, stage)

    fail_operation(source_operation_id, source_cutover_plan)
    config = SimpleNamespace(
        channel='test', root=tmp_path, uid=os.geteuid(), gid=os.getegid(), journal=journal,
    )
    effects = linux.LinuxEffects(config)
    source_request = TestRecoveryRequest(
        source_operation_id, source_request_plan, authority,
    )
    effects._write_test_recovery_disposition(source_request, 'complete')
    fail_operation(failed_successor_operation_id, source_request_plan)

    with pytest.raises(PostgresDeployError):
        journal.bound_plan(source_operation_id)
    request = TestRecoveryRequest(
        failed_successor_operation_id, fresh_candidate, authority,
        source_operation_id=source_operation_id,
        source_plan=source_request_plan,
    )
    ownership_root = Path(authority.ownership_root)
    ownership_root.mkdir(mode=0o700)
    (ownership_root / 'legacy-owner-inventory.json').write_text('{}\n')
    (ownership_root / 'deployment-quiescence-proof.json').write_text('{}\n')
    monkeypatch.setattr(
        linux, '_private_json', lambda path: json.loads(path.read_text()),
    )
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    monkeypatch.setattr(
        linux.LinuxEffects, 'local_database', lambda _self: True,
    )
    monkeypatch.setattr(
        linux.LinuxEffects, 'recovery_quiescent', lambda _self: True,
    )
    monkeypatch.setattr(
        linux.LinuxEffects, '_validate_test_instance_state_recovery_authority',
        lambda *_args, **_kwargs: 'c' * 64,
    )

    def compose(_self, *args, **_kwargs):
        if '--user' not in args:
            return ''
        return json.dumps({
            'schema': 'test-instance-state-recovery.v2',
            'channel': 'test',
            'activation': 'inactive_fenced',
            'request': {
                'source_operation_id': source_operation_id,
                'failed_successor_operation_id': failed_successor_operation_id,
            },
            'ledger_sha256': 'c' * 64,
        })

    monkeypatch.setattr(linux.LinuxEffects, 'compose', compose)
    supervisor = linux.DeploymentSupervisor(config)
    retained = linux.SupervisedOperation(
        linux.LinuxEffects(config), failed_successor_operation_id,
        source_request_plan, False,
    )
    retained.failed = True
    retained.finished.set()
    supervisor.operation = retained

    def run_rpc(_argv, **kwargs):
        response = supervisor.request(json.loads(kwargs['input']))
        return SimpleNamespace(returncode=0, stdout=json.dumps(response))

    monkeypatch.setattr(linux.subprocess, 'run', run_rpc)
    result = linux.SshDeployRemote('ygg-test').test_recovery_reconstruct_instance_state(request)

    receipt_path = ownership_root / (
        'test-instance-state-recovery-' + failed_successor_operation_id + '.json'
    )

    payload = json.loads(receipt_path.read_text())
    assert result['activation'] == 'inactive_fenced'
    assert supervisor.operation is None
    assert payload['source_operation_id'] == source_operation_id
    assert payload['failed_successor_operation_id'] == failed_successor_operation_id
    assert payload['candidate_revision'] == fresh_candidate.revision

    # A normal same-plan successor remains as a terminal in-memory object.
    # The identical recovery retry must still reach the evidence-bound,
    # idempotent release instead of failing at the supervisor shell.
    successor_operation_id = str(uuid4())
    terminal = linux.SupervisedOperation(
        linux.LinuxEffects(config), successor_operation_id, fresh_candidate, False,
    )
    terminal.finished.set()
    supervisor.operation = terminal
    release_calls = []

    def release(_self, selected):
        release_calls.append(selected)
        return {
            'channel': 'test', 'released': False,
            'reason': 'already-released-after-reconstruction',
        }

    monkeypatch.setattr(
        linux.LinuxEffects, 'release_test_instance_state_recovery_lease', release,
    )
    with pytest.raises(PostgresDeployError):
        linux.SshDeployRemote('ygg-test').test_recovery_release_instance_state(
            request, successor_operation_id=str(uuid4()),
        )
    terminal.finished.clear()
    with pytest.raises(PostgresDeployError):
        linux.SshDeployRemote('ygg-test').test_recovery_release_instance_state(
            request, successor_operation_id=successor_operation_id,
        )
    terminal.finished.set()
    assert release_calls == []
    released = linux.SshDeployRemote('ygg-test').test_recovery_release_instance_state(
        request, successor_operation_id=successor_operation_id,
    )
    assert released['reason'] == 'already-released-after-reconstruction'
    assert release_calls == [request]
    assert supervisor.operation is terminal


@pytest.mark.parametrize('channel', ['dev', 'test', 'prod'])
@pytest.mark.parametrize('reject_recheck', [False, True])
def test_bws_full_deploy_raw_migration_uses_supervised_preflight(tmp_path, channel, reject_recheck):
    root, env, _ = _deploy_harness(tmp_path)
    target = _commit_har_raw_migration(root, 'e7b4c9d2a6f1_heimdal_raw_representation.py')
    env.update(FAKE_SHA=target, DEPLOY_ACK_FORWARD_ONLY='1', HOST_SECRET_PROVIDER='bws', BWS_DATABASE_TARGET='local',
               FAKE_SECURITY_EVENT_LOG=env['FAKE_DEPLOY_EVENT_LOG'])
    _set_bws_consumer_selection(env, raw_migration=True)
    _set_native_bws_operation_context(root, env)
    _configure_successful_channel_preflights(root, env, tmp_path, channel=channel)
    if channel == 'prod':
        _configure_bws_retry_driver(tmp_path, env)
    # Fake only the VM credential/FD adapter; run the actual deployment shell and
    # its real pending-HAR classification, pin/migration and Compose branches.
    _install_bws_identity_guard_fixture(root)
    guard = root / 'app/ops/postgres_deploy_linux.py'
    guard.write_text(guard.read_text() + '''
if __name__ == '__main__':
    from pathlib import Path
    count = Path(os.environ['FAKE_DEPLOY_EVENT_LOG']).read_text().count('bws-guard')
    if os.environ.get('FAKE_BWS_REJECT_RECHECK') == '1' and count == 2:
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
    _set_native_bws_operation_context(root, env)
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
    _install_bws_identity_guard_fixture(root)
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
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    directory = tmp_path / 'config/deploy'
    directory.mkdir(parents=True)
    (directory / 'test.env').write_text('APP_IMAGE_TAG=' + 'a' * 40 + '\n')
    lock = directory / 'test.env.lock'
    lock.mkdir()
    password = tmp_path / 'password'
    password.write_text('fake-target-binding-password')
    runtime_env_file = tmp_path / 'runtime.env'
    runtime_env_file.write_text('LLM_PROVIDER=mock\n', encoding='utf-8')
    journal = DeployJournal(tmp_path / 'journal', 'test')
    identifier = str(uuid4())
    plan = DeployPlan('test', 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'))
    journal.bind_request(identifier, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(identifier, stage)
    cfg = SimpleNamespace(root=tmp_path, channel='test', password_file=password,
                          runtime_env_file=runtime_env_file,
                          reader=lambda: object(), journal=journal)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda channel: cfg)
    reads = []
    monkeypatch.setattr(linux.PasswordSource, 'verify', lambda self: reads.append('source'))
    monkeypatch.setattr(linux, 'vm_selected_values', lambda *args:
                        {'postgres-db': {'postgres.password': password.read_text()}})
    monkeypatch.setattr(linux, 'require_file_protocol', lambda *args: None)
    with (lock / 'bws-owner').open('w+') as owner:
        monkeypatch.setattr(os, 'environ', {'DATABASE_URL': 'postgresql://app@' + host + ':5432/app_test',
            'BWS_DEPLOY_LOCK_FD': str(owner.fileno()), 'BWS_DEPLOY_OPERATION_ID': identifier,
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
        "def record_source_terminal(channel, name, status):\n"
        "    from app.ops.native_source_bootstrap import quiesce_owned_container, source_terminal_reason, SOURCE_PROJECTION_FAILURE_CODES\n"
        "    if not quiesce_owned_container(channel, name, os.environ['BWS_DEPLOY_OPERATION_ID'], os.environ['BWS_DEPLOY_TARGET_REVISION']): return 78\n"
        "    reason = source_terminal_reason(status)\n"
        "    return SOURCE_PROJECTION_FAILURE_CODES[reason] if reason else 0\n"
        "if __name__ == '__main__':\n"
        "    assert sys.argv[1] == 'guard'\n"
        "    if sys.argv[-1] == 'run' and os.environ.get('FAKE_BWS_COMPOSE_GUARD_RC', '0') != '0':\n"
        "        raise SystemExit(int(os.environ['FAKE_BWS_COMPOSE_GUARD_RC']))\n"
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
    _set_native_bws_operation_context(root, env)

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
    _set_native_bws_operation_context(root, env)

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


def _native_source_harness(
    tmp_path: Path, *, channel: str, ready: bool = False
) -> tuple[Path, dict[str, str], str]:
    root, env, sha = _deploy_harness(tmp_path)
    ollama_model_state = tmp_path / "ollama-model-present"
    ollama_model_state.touch()
    _configure_successful_channel_preflights(root, env, tmp_path, channel=channel)
    _install_bws_identity_guard_fixture(root)
    api_handle = tmp_path / "api-consumer.env"
    api_handle.write_text("", encoding="utf-8")
    api_handle.chmod(0o600)
    env.update(
        HOST_SECRET_PROVIDER="bws",
        HOST_SECRET_RUNTIME_ENV_FILE_API=str(api_handle),
        BWS_DATABASE_TARGET="local",
        BWS_DEPLOY_TARGET_REVISION=sha,
        BWS_DEPLOY_OPERATION_ID="03b3bb2f-6d85-499a-8b45-e397f56812e1",
        BWS_EXPECTED_CAPTURE_WATCH_CONFIGURED="1",
        BWS_EXPECTED_RAW_MIGRATION_PENDING="0",
        APP_IMAGE_TAG=sha,
        PKM_ENVIRONMENT=channel,
        FAKE_SOURCE_PROJECTION_READY="1" if ready else "0",
        FAKE_EMBEDDING_PROVIDER="ollama",
        FAKE_EMBEDDING_MODEL="nomic-embed-text:latest",
        FAKE_OLLAMA_MODEL_STATE_FILE=str(ollama_model_state),
        FAKE_OLLAMA_PULL_RC="0",
        FAKE_EMBEDDING_PROBE_RC="0",
        FAKE_EMBEDDING_IDENTITY_RC="0",
    )
    if channel == "prod":
        _configure_bws_retry_driver(tmp_path, env)
    (root / "scripts/start_api.sh").write_text(
        (REPO_ROOT / "scripts/start_api.sh").read_text(encoding="utf-8"), encoding="utf-8",
    )
    (root / "scripts/run_migrations.sh").write_text(
        'printf "api-migrations\\n" >> "${FAKE_DEPLOY_EVENT_LOG:?}"\n', encoding="utf-8",
    )
    python = tmp_path / "bin/python"
    python.write_text(python.read_text(encoding="utf-8").replace(
        "set -eu\n",
        '''set -eu
if [ "${1:-}" = -m ] && [ "${2:-}" = app.instance.runtime ]; then
  printf 'api-instance-preflight %s\\n' "$*" >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  exit "${FAKE_API_INSTANCE_RC:-0}"
fi
''', 1,
    ), encoding="utf-8")
    site = tmp_path / "api-python-fixture"
    site.mkdir()
    (site / "sitecustomize.py").write_text(
        '''import os
from pathlib import Path
from types import SimpleNamespace
from app.config import paths
from app import objects, rebuildability
from app.instance import runtime
def instance_preflight(**kwargs):
    if os.environ.get("FAKE_API_CONTEXT_RC", "0") != "0":
        raise ValueError("hostile context diagnostic")
runtime._preflight_runtime = instance_preflight
paths.resolve_optional_vault_root = lambda: (None if os.environ.get("FAKE_API_UNBOUND") == "1"
                                           else Path(os.environ["FAKE_API_VAULT"]))
objects.resolve_store_backend = lambda: os.environ.get("FAKE_API_BACKEND", "pg")
def resolve_object_store_port():
    if os.environ.get("FAKE_API_UNBOUND") == "1":
        raise RuntimeError("unbound preflight must not construct a StorePort")
    return SimpleNamespace(
        backend=os.environ.get("FAKE_API_BACKEND", "pg"),
        store=SimpleNamespace(list_objects=lambda **kwargs: []),
    )
objects.resolve_object_store_port = resolve_object_store_port
rebuildability.evaluate_product_store_readiness = lambda root, rows: SimpleNamespace(
    ready=Path(os.environ["FAKE_API_READY_FILE"]).exists(),
    state="ready" if Path(os.environ["FAKE_API_READY_FILE"]).exists() else "refused")
''', encoding="utf-8",
    )
    (root / "app/cli.py").write_text(
        '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_DEPLOY_EVENT_LOG"], "a") as stream:
    stream.write("api-cli " + " ".join(args) + "\\n")
if args[:1] == ["vault-alpha-ingest"]:
    with open(os.environ["FAKE_DEPLOY_EVENT_LOG"], "a") as stream:
        stream.write("source-rebuild\\n")
        stream.write(
            "source-rebuild-identity "
            + os.environ.get("FAKE_EMBEDDING_PROVIDER", "unset")
            + " "
            + os.environ.get("FAKE_EMBEDDING_MODEL", "unset")
            + "\\n"
        )
    if os.environ.get("FAKE_SOURCE_PREADINESS", "1") == "1":
        Path(os.environ["FAKE_API_READY_FILE"]).touch()
    print(os.environ.get("FAKE_SOURCE_SUMMARY", '{"scanned":2,"ingested":2,"errors":0,"malformed":0,"skipped_locked":0,"skipped_invalid":0}'))
    print("hostile-child-canary /private/vault password=do-not-leak", file=sys.stderr)
    raise SystemExit(int(os.environ.get("FAKE_SOURCE_RC", "0")))
elif args[:2] == ["index", "doctor"]:
    strict = "--strict" in args
    summary_name = "FAKE_SOURCE_INDEX_SUMMARY" if strict else "FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"
    if not strict and Path(os.environ["FAKE_API_READY_FILE"]).exists():
        events = Path(os.environ["FAKE_DEPLOY_EVENT_LOG"]).read_text().rsplit("api-cli settings validate --json\\n", 1)[-1]
        if "source-rebuild\\n" in events:
            summary_name = "FAKE_SOURCE_REPLAY_INDEX_SUMMARY"
    default_summary = '{"backend":"PgVectorIndex","issues":[],"rebuild_required":false,"unembedded_object_count":0,"non_vector_issue_count":0,"pg_state":{"rows":2}}'
    print(os.environ.get(summary_name, default_summary))
    rc_name = "FAKE_SOURCE_INDEX_RC" if strict else "FAKE_SOURCE_INDEX_PREFLIGHT_RC"
    raise SystemExit(int(os.environ.get(rc_name, "0")))
elif args[:2] == ["index", "reconcile-legacy"]:
    print(os.environ.get("FAKE_LEGACY_RECONCILIATION_SUMMARY", '{"processed":0}'))
    raise SystemExit(int(os.environ.get("FAKE_LEGACY_RECONCILIATION_RC", "0")))
elif args[:2] == ["index", "repair-missing"]:
    print(os.environ.get("FAKE_MISSING_REPAIR_SUMMARY", '{"processed":1}'))
    print("hostile-child-canary /private/vault password=do-not-leak", file=sys.stderr)
    raise SystemExit(int(os.environ.get("FAKE_MISSING_REPAIR_RC", "0")))
elif args[:2] == ["settings", "validate"]:
    print('{}')
    raise SystemExit(int(os.environ.get("FAKE_SOURCE_SETTINGS_RC", "0")))
else:
    raise SystemExit(78)
''', encoding="utf-8",
    )
    ready_file = tmp_path / "projection-ready"
    if ready:
        ready_file.touch()
    env.update(
        FAKE_API_VAULT=str(root / "tmp"), FAKE_API_READY_FILE=str(ready_file),
        FAKE_API_PYTHONPATH=f"{site}:{root}:{REPO_ROOT}", VCS_REF=sha,
        FAKE_GENERIC_EMBEDDING_IDENTITY="0",
    )
    command = _compose("docker-compose.yaml")["services"]["api"]["command"][2]
    (root / "api-command.sh").write_text(
        command.replace("$$", "$").replace("/app", str(root)), encoding="utf-8",
    )
    docker = tmp_path / "bin/docker"
    text = docker.read_text(encoding="utf-8")
    text = text.replace(
        'case "$*" in\n',
        '''if [[ "$*" == *"NATIVE_SOURCE_BOOTSTRAP="* ]]; then
  previous=""
  for argument in "$@"; do
    if [ "${previous}" = -f ] && [ -f "${argument}" ]; then
      scope="$(awk '/PKM_ACTIVATION_SCOPE:/ {gsub(/"/, "", $2); print $2}' "${argument}")"
      if [ -n "${scope}" ]; then export PKM_ACTIVATION_SCOPE="${scope}"; fi
    fi
    previous="${argument}"
  done
  printf 'source-probe channel=%s image=%s api-context=%s\\n' \
    "${PKM_ENVIRONMENT:-unset}" "${APP_IMAGE_TAG:-unset}" \
    "${HOST_SECRET_RUNTIME_ENV_FILE_API:-unset}" >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  for argument in "$@"; do
    case "${argument}" in NATIVE_SOURCE_BOOTSTRAP=*) export "${argument}";; esac
  done
  export PYTHONPATH="${FAKE_API_PYTHONPATH:?}"
  bash "${PWD}/api-command.sh"
  exit $?
fi
if [[ "$*" == *"native-source-embedding-identity.v1"* ]]; then
  printf 'embedding-identity-read provider=%s model=%s\\n' \\
    "${FAKE_EMBEDDING_PROVIDER:-ollama}" "${FAKE_EMBEDDING_MODEL:-nomic-embed-text:latest}" \\
    >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  printf '{"contract":"native-source-embedding-identity.v1","provider":"%s","model":"%s"}\\n' \\
    "${FAKE_EMBEDDING_PROVIDER:-ollama}" "${FAKE_EMBEDDING_MODEL:-nomic-embed-text:latest}"
  if [ -n "${FAKE_EMBEDDING_IDENTITY_EXTRA_OUTPUT:-}" ]; then
    printf '%s\\n' "${FAKE_EMBEDDING_IDENTITY_EXTRA_OUTPUT}"
  fi
  exit "${FAKE_EMBEDDING_IDENTITY_RC:-0}"
fi
if [[ "$*" == *" up -d --no-deps ollama"* ]]; then
  printf 'ollama-up\\n' >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  exit "${FAKE_OLLAMA_UP_RC:-0}"
fi
if [[ "$*" == *"ollama list"* ]]; then
  printf 'ollama-list\\n' >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  exit "${FAKE_OLLAMA_LIST_RC:-0}"
fi
if [[ "$*" == *"ollama show "* ]]; then
  printf 'ollama-show\\n' >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  if [ -f "${FAKE_OLLAMA_MODEL_STATE_FILE:?}" ]; then
    exit 0
  fi
  exit 1
fi
if [[ "$*" == *"ollama pull "* ]]; then
  printf 'ollama-pull model=%s\\n' "${FAKE_EMBEDDING_MODEL:-nomic-embed-text:latest}" \\
    >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  pull_rc="${FAKE_OLLAMA_PULL_RC:-0}"
  if [ "${pull_rc}" = "0" ]; then
    : > "${FAKE_OLLAMA_MODEL_STATE_FILE:?}"
  fi
  exit "${pull_rc}"
fi
if [[ "$*" == *"NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER"* ]]; then
  printf 'embedding-probe provider=%s model=%s\\n' \\
    "${FAKE_EMBEDDING_PROVIDER:-ollama}" "${FAKE_EMBEDDING_MODEL:-nomic-embed-text:latest}" \\
    >> "${FAKE_DEPLOY_EVENT_LOG:?}"
  exit "${FAKE_EMBEDDING_PROBE_RC:-0}"
fi
case "$*" in
''',
        1,
    )
    docker.write_text(text, encoding="utf-8")
    return root, env, sha


def _native_source_harness_with_prior_deployment(
    tmp_path: Path, *, ready: bool = True
) -> tuple[Path, dict[str, str], str, str, str]:
    root, env, current_sha = _native_source_harness(tmp_path, channel="dev", ready=ready)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-qm", "candidate deployment"],
        cwd=root,
        check=True,
    )
    target_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    (root / "config/deploy/dev.env").write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/current\n"
        f"APP_IMAGE_TAG={current_sha}\n",
        encoding="utf-8",
    )
    with (root / "config/deploy/dev.env").open("a", encoding="utf-8") as pin:
        pin.write("CHANNEL_SETTING=preserve-exactly\n")
    previous_pin = root / "config/deploy/dev.previous.env"
    previous_pin_before = (
        "APP_IMAGE_REPOSITORY=example.invalid/previous-anchor\n"
        f"APP_IMAGE_TAG={current_sha}\n"
        "ROLLBACK_ANCHOR_NOTE=preserve\n"
    )
    previous_pin.write_text(previous_pin_before, encoding="utf-8")
    env.update(
        APP_IMAGE_REPOSITORY="example.invalid/target-image",
    )
    env.update(
        APP_IMAGE_TAG=target_sha,
        BWS_DEPLOY_TARGET_REVISION=target_sha,
        FAKE_SHA=target_sha,
        VCS_REF=target_sha,
    )
    return root, env, current_sha, target_sha, previous_pin_before


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
@pytest.mark.parametrize("ready", [False, True])
def test_native_deploy_rebuilds_source_projection_before_health_gate(
    tmp_path: Path, channel: str, ready: bool
) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel=channel, ready=ready)

    result = _run_deploy(root, env, sha, channel=channel)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    source_calls = [
        (i, event) for i, event in enumerate(events)
        if event.startswith("docker ") and "NATIVE_SOURCE_BOOTSTRAP=" in event
    ]
    assert len(source_calls) == 1, events
    source_pos, command = source_calls[0]
    assert "run --no-deps -T" in command
    assert "--rm" not in command.split()
    assert f"NATIVE_SOURCE_BOOTSTRAP={channel}:{sha}" in command
    assert command.endswith(" api")
    assert "--entrypoint" not in command
    assert f"-p pkm-{channel}" in command
    assert "docker-compose.bws.yml" in command
    runtime_start = next(
        i for i, event in enumerate(events)
        if "up -d --force-recreate api worker watcher" in event
    )
    final_readiness = next(i for i, event in enumerate(events) if "/readyz" in event)
    source_census = next(i for i, event in enumerate(events)
                        if event.startswith('docker ps --all --filter name=^/pkm-')
                        and 'source-bootstrap-' in event)
    assert source_pos < source_census < runtime_start < final_readiness
    assert events.count("source-rebuild") == (0 if ready else 1)
    assert any("api-instance-preflight -m app.instance.runtime preflight" in event for event in events)
    assert events.count("api-migrations") == 1
    assert any(event == "api-cli index doctor --json --strict" for event in events)
    if not ready:
        assert f"api-cli vault-alpha-ingest --vault-root {(root / 'tmp').resolve()} --max-notes 0 --force --source-backed-rebuild --json" in events
    assert "hostile-child-canary" not in result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("channel", ["dev", "test", "prod"])
def test_native_source_projection_prepares_ollama_before_stopping_services(
    tmp_path: Path, channel: str
) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel=channel, ready=True)
    selected_model = "nomic-embed-text:deployment-test"
    env.update(FAKE_EMBEDDING_MODEL=selected_model)
    Path(env["FAKE_OLLAMA_MODEL_STATE_FILE"]).unlink()

    result = _run_deploy(root, env, sha, channel=channel)

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    identity = events.index(f"embedding-identity-read provider=ollama model={selected_model}")
    identity_command = next(
        event for event in events
        if event.startswith("docker ") and "native-source-embedding-identity.v1" in event
    )
    service_up = next(
        index for index, event in enumerate(events)
        if event.startswith("docker ") and " up -d --no-deps ollama" in event
    )
    model_pull = events.index(f"ollama-pull model={selected_model}")
    embedding_probe = events.index(f"embedding-probe provider=ollama model={selected_model}")
    embedding_probe_command = next(
        event for event in events
        if event.startswith("docker ") and "NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER" in event
    )
    first_stop = next(
        index for index, event in enumerate(events)
        if event.startswith("docker ") and " stop api worker watcher" in event
    )
    assert identity < service_up < model_pull < embedding_probe < first_stop
    assert 'LLMRouter().route(LLMTaskIntent(task_kind="embed", strict_identity_required=True))' in identity_command
    assert "SETTINGS_RELOAD_SIGNAL_PATH" not in identity_command
    assert "SETTINGS_RELOAD_SIGNAL_PATH" not in embedding_probe_command
    assert '"dim"' not in identity_command
    assert f"ollama show {selected_model}" in "\n".join(events)
    assert not any("hostile-child-canary" in event for event in events)


@pytest.mark.parametrize(
    (
        "actual_provider",
        "actual_model",
        "actual_dimension",
        "vector_length",
        "expected_rc",
        "embedding_runs",
    ),
    [
        ("ollama", "nomic-embed-text:deployment-test", 3, 3, 0, True),
        ("mock", "nomic-embed-text:deployment-test", 3, 3, 115, False),
        ("ollama", "other-model", 3, 3, 115, False),
        ("ollama", "nomic-embed-text:deployment-test", 4, 4, 0, True),
        ("ollama", "nomic-embed-text:deployment-test", 3, 2, 117, True),
    ],
)
def test_native_source_embedding_probe_checks_actual_identity_and_dimension(
    tmp_path: Path,
    actual_provider: str,
    actual_model: str,
    actual_dimension: int,
    vector_length: int,
    expected_rc: int,
    embedding_runs: bool,
) -> None:
    assignment = next(
        line.strip()
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("probe_command=$'")
    )
    extracted = subprocess.run(
        ["bash", "-c", f'{assignment}\nprintf "%s" "$probe_command"'],
        check=False,
        capture_output=True,
        text=True,
    )
    assert extracted.returncode == 0, extracted.stderr

    app = tmp_path / "app"
    components = app / "components"
    llm = components / "llm"
    llm.mkdir(parents=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (components / "__init__.py").write_text("", encoding="utf-8")
    (llm / "__init__.py").write_text("", encoding="utf-8")
    (llm / "fabric.py").write_text(
        '''import os
from pathlib import Path
from types import SimpleNamespace

IDENTITY = SimpleNamespace(
    provider=os.environ["FAKE_ACTUAL_PROVIDER"],
    model=os.environ["FAKE_ACTUAL_MODEL"],
    dim=int(os.environ["FAKE_ACTUAL_DIMENSION"]),
)
class RemoteEmbeddingIdentityError(Exception): pass
class RemoteEmbeddingVectorError(Exception): pass

class ProductEmbeddingClient:
    identity = IDENTITY

    def embed_text(self, text):
        Path(os.environ["FAKE_PROBE_CAPTURE"]).write_text(
            f"{IDENTITY.provider}\\t{IDENTITY.model}\\t{text}",
            encoding="utf-8",
        )
        return [0.0] * int(os.environ["FAKE_VECTOR_LENGTH"])

    def close(self):
        Path(os.environ["FAKE_PROBE_CLOSED"]).write_text("closed", encoding="utf-8")

def get_product_embedding_client():
    return ProductEmbeddingClient()
''',
        encoding="utf-8",
    )
    capture = tmp_path / "embedding-probe.txt"
    env = {
        **os.environ,
        "PYTHONPATH": str(tmp_path),
        "NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER": "ollama",
        "NATIVE_SOURCE_EXPECTED_EMBEDDING_MODEL": "nomic-embed-text:deployment-test",
        "FAKE_ACTUAL_PROVIDER": actual_provider,
        "FAKE_ACTUAL_MODEL": actual_model,
        "FAKE_ACTUAL_DIMENSION": str(actual_dimension),
        "FAKE_VECTOR_LENGTH": str(vector_length),
        "FAKE_PROBE_CAPTURE": str(capture),
        "FAKE_PROBE_CLOSED": str(tmp_path / "probe-closed"),
    }

    result = subprocess.run(
        [sys.executable, "-c", extracted.stdout],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == expected_rc, result.stdout + result.stderr
    assert capture.exists() is embedding_runs
    assert (tmp_path / "probe-closed").exists()
    if embedding_runs:
        assert capture.read_text(encoding="utf-8") == (
            "ollama\tnomic-embed-text:deployment-test\tYggdrasil deployment preflight"
        )


@pytest.mark.parametrize("failure", ["service", "pull", "probe"])
def test_native_source_projection_refuses_unavailable_ollama_before_stopping_services(
    tmp_path: Path, failure: str
) -> None:
    root, env, _current_sha, sha, previous_pin_before = \
        _native_source_harness_with_prior_deployment(tmp_path)
    pin_file = root / "config/deploy/dev.env"
    original_pin = pin_file.read_text(encoding="utf-8") if pin_file.exists() else None
    if failure == "service":
        env.update(FAKE_OLLAMA_UP_RC="43")
    elif failure == "pull":
        Path(env["FAKE_OLLAMA_MODEL_STATE_FILE"]).unlink()
        env.update(FAKE_OLLAMA_PULL_RC="43")
    else:
        env.update(FAKE_EMBEDDING_PROBE_RC="44")

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode != 0
    events = _deploy_events(env)
    assert not any(
        event.startswith("docker ") and " stop api worker watcher" in event
        for event in events
    )
    assert not any(
        event.startswith("docker ") and " up -d --force-recreate api worker watcher" in event
        for event in events
    )
    assert "source-rebuild" not in events
    if original_pin is None:
        assert not pin_file.exists()
    else:
        assert pin_file.read_text(encoding="utf-8") == original_pin
    assert (root / "config/deploy/dev.previous.env").read_text(encoding="utf-8") == previous_pin_before
    assert not (root / "config/deploy/dev.migration-pending.env").exists()
    assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr
    assert "pre-migration pin state restored and app services were not stopped" in result.stderr
    assert "hostile-child-canary" not in result.stdout + result.stderr


def test_native_source_projection_retains_pin_snapshot_when_restore_fails(
    tmp_path: Path,
) -> None:
    root, env, current_sha, target_sha, previous_pin_before = \
        _native_source_harness_with_prior_deployment(tmp_path)
    primary_pin_before = (root / "config/deploy/dev.env").read_text(encoding="utf-8")
    mv = tmp_path / "bin/mv"
    mv.write_text(
        '''#!/usr/bin/env bash
set -eu
if [ "${FAKE_FAIL_PIN_RESTORE:-0}" = "1" ] &&
   [ "${1:-}" = "-f" ] && [ "${2:-}" = "--" ] &&
   [[ "${3:-}" == *"/config/deploy/dev.env.preflight."* ]] &&
   [ "${4:-}" = "${PWD}/config/deploy/dev.env" ] &&
   grep -q "embedding-identity-read" "${FAKE_DEPLOY_EVENT_LOG:?}"; then
  exit 91
fi
exec /bin/mv "$@"
''',
        encoding="utf-8",
    )
    mv.chmod(0o755)
    env.update(FAKE_OLLAMA_UP_RC="43", FAKE_FAIL_PIN_RESTORE="1")

    result = _run_deploy(root, env, target_sha, channel="dev")

    assert result.returncode == 78
    assert "pre-migration pin/marker restoration failed" in result.stderr
    events = _deploy_events(env)
    assert not any(
        event.startswith("docker ") and " stop api worker watcher" in event
        for event in events
    )
    assert not any(
        event.startswith("docker ") and " up -d --force-recreate api worker watcher" in event
        for event in events
    )
    assert _read_pin_tag(root / "config/deploy/dev.env") == target_sha
    assert _read_pin_tag(root / "config/deploy/dev.previous.env") == current_sha
    assert (root / "config/deploy/dev.env").read_text(encoding="utf-8") != primary_pin_before
    primary_snapshots = list((root / "config/deploy").glob("dev.env.preflight.*"))
    previous_snapshots = list((root / "config/deploy").glob("dev.previous.env.preflight.*"))
    assert len(primary_snapshots) == len(previous_snapshots) == 1
    assert primary_snapshots[0].read_text(encoding="utf-8") == primary_pin_before
    assert previous_snapshots[0].read_text(encoding="utf-8") == previous_pin_before


def test_native_same_target_preflight_failure_preserves_inherited_marker_and_pins(
    tmp_path: Path,
) -> None:
    root, env, current_sha, target_sha, previous_pin_before = \
        _native_source_harness_with_prior_deployment(tmp_path)
    pin_file = root / "config/deploy/dev.env"
    pin_file_before = (
        "APP_IMAGE_REPOSITORY=example.invalid/inherited-retry\n"
        f"APP_IMAGE_TAG={target_sha}\n"
        "CHANNEL_SETTING=retry-pin-preserve\n"
    )
    pin_file.write_text(pin_file_before, encoding="utf-8")
    marker = root / "config/deploy/dev.migration-pending.env"
    marker_before = (
        f"FROM_SHA={current_sha}\n"
        f"TARGET_SHA={target_sha}\n"
        "ACK_FORWARD_ONLY=0\n"
    )
    marker.write_text(marker_before, encoding="utf-8")
    env.update(FAKE_OLLAMA_UP_RC="43")

    result = _run_deploy(root, env, target_sha, channel="dev")

    assert result.returncode == 78
    assert "pre-migration pin state restored and app services were not stopped" in result.stderr
    events = _deploy_events(env)
    assert not any(
        event.startswith("docker ") and " stop api worker watcher" in event
        for event in events
    )
    assert pin_file.read_text(encoding="utf-8") == pin_file_before
    assert (root / "config/deploy/dev.previous.env").read_text(encoding="utf-8") == previous_pin_before
    assert marker.read_text(encoding="utf-8") == marker_before
    assert not list((root / "config/deploy").glob("dev.env.preflight.*"))
    assert not list((root / "config/deploy").glob("dev.previous.env.preflight.*"))


def test_native_source_embedding_identity_receipt_rejects_unrelated_compose_output(
    tmp_path: Path,
) -> None:
    root, env, _current_sha, sha, previous_pin_before = \
        _native_source_harness_with_prior_deployment(tmp_path)
    pin_file = root / "config/deploy/dev.env"
    original_pin = pin_file.read_text(encoding="utf-8") if pin_file.exists() else None
    canary = "private-compose-output-canary"
    env["FAKE_EMBEDDING_IDENTITY_EXTRA_OUTPUT"] = canary

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode != 0
    events = _deploy_events(env)
    assert not any("ollama-up" in event for event in events)
    assert not any(
        event.startswith("docker ") and " stop api worker watcher" in event
        for event in events
    )
    if original_pin is None:
        assert not pin_file.exists()
    else:
        assert pin_file.read_text(encoding="utf-8") == original_pin
    assert (root / "config/deploy/dev.previous.env").read_text(encoding="utf-8") == previous_pin_before
    assert not (root / "config/deploy/dev.migration-pending.env").exists()
    assert canary not in result.stdout + result.stderr
    assert "receipt=invalid" not in result.stdout + result.stderr
    assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr


def test_native_source_projection_preserves_selected_embedding_identity(
    tmp_path: Path,
) -> None:
    root, env, current_sha, sha, _previous_pin_before = \
        _native_source_harness_with_prior_deployment(tmp_path, ready=False)
    selected_model = "nomic-embed-text:deployment-test"
    env.update(FAKE_EMBEDDING_MODEL=selected_model)

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    assert f"embedding-identity-read provider=ollama model={selected_model}" in events
    assert f"embedding-probe provider=ollama model={selected_model}" in events
    assert f"source-rebuild-identity ollama {selected_model}" in events
    assert f"ollama-pull model={selected_model}" not in events
    assert not any("provider=mock" in event for event in events)
    assert _read_pin_tag(root / "config/deploy/dev.previous.env") == current_sha
    assert not list((root / "config/deploy").glob("dev.previous.env.preflight.*"))


def _wire_real_missing_repair(root: Path, env: dict[str, str]) -> None:
    # Exercise the real CLI, canonical-store consumer and PgVectorIndex insert.
    # Only provider/database infrastructure is replaced by the focused SQL fixture.
    (root / "app/ops/__init__.py").write_text("from pkgutil import extend_path\n__path__ = extend_path(__path__, __name__)\n")
    site = root.parent / "api-python-fixture/sitecustomize.py"
    site.write_text(site.read_text() + '''
paths.resolve_optional_vault_root = lambda **kwargs: Path(os.environ["FAKE_API_VAULT"])
from app.settings import runtime as settings_runtime
from app.settings.models import SettingsBundle
settings_runtime.get_settings_bundle = lambda: SettingsBundle()
''')
    stub = root / "app/cli.py"
    stub.write_text(stub.read_text().replace(
        'elif args[:2] == ["index", "repair-missing"]:',
        '''elif args[:2] == ["index", "repair-missing"]:
    import importlib.util, pytest
    package = Path(os.environ["REAL_CLI_PACKAGE"])
    spec = importlib.util.spec_from_file_location("app.cli", package / "__init__.py", submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["app.cli"] = module
    spec.loader.exec_module(module)
    fixture_spec = importlib.util.spec_from_file_location("missing_repair_fixture", os.environ["REAL_REPAIR_FIXTURE"])
    fixture = importlib.util.module_from_spec(fixture_spec)
    fixture_spec.loader.exec_module(fixture)
    patch = pytest.MonkeyPatch()
    repair, state, identity = fixture._missing_repair_fixture(patch)
    state.fail = os.environ.get("REAL_REPAIR_FAILURE")
    if state.fail == "ineligible":
        state.rows[0]["payload"]["candidate_only"] = True
    module.cli()
elif args[:2] == ["index", "repair-missing"]:'''))
    env.update(REAL_CLI_PACKAGE=str(REPO_ROOT / "app/cli"),
               REAL_REPAIR_FIXTURE=str(REPO_ROOT / "tests/cli/test_index_rebuild_cli.py"))


def test_native_deploy_repairs_indexable_object_outside_selected_source_inventory(tmp_path: Path) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    missing = json.dumps(dict(backend="PgVectorIndex", issues=["missing vector"],
        rebuild_required=True, unembedded_object_count=1, non_vector_issue_count=0,
        pg_state={"rows": 79}))
    env["FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"] = missing
    env["FAKE_SOURCE_REPLAY_INDEX_SUMMARY"] = missing
    _wire_real_missing_repair(root, env)
    result = _run_deploy(root, env, sha, channel="dev")
    assert result.returncode == 0, result.stderr
    events = _deploy_events(env)
    replay = events.index("source-rebuild")
    repair = events.index("api-cli index repair-missing --json")
    strict = events.index("api-cli index doctor --json --strict")
    activation = next(i for i, event in enumerate(events)
                      if "up -d --force-recreate api worker watcher" in event)
    assert replay < repair < strict < activation
    assert "hostile-child-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize("summary, rc, reason", [
    ('{"reason":"legacy_producer_policy_refused"}', "79", "legacy_producer_policy_refused"),
    ('{"reason":"legacy_source_refused"}', "79", "legacy_source_refused"),
    ('{"reason":"legacy_admission_refused"}', "79", "legacy_admission_refused"),
    ('{"reason":"legacy_identity_refused"}', "79", "legacy_identity_refused"),
    ('{"reason":"legacy_race_refused"}', "79", "legacy_race_refused"),
    ('{"reason":"legacy_write_failed"}', "79", "legacy_write_failed"),
    ('{"reason":"source_post_rebuild_failed"}', "79", "source_post_rebuild_failed"),
    ('{"processed":true}', "0", "source_summary_invalid"),
    ('{"reason":"private-canary"}', "79", "source_summary_invalid"),
])
def test_native_legacy_reconciliation_refusal_is_private_and_blocks_activation(tmp_path, summary, rc, reason):
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    missing = json.dumps(dict(backend="PgVectorIndex", issues=["missing vector"],
        rebuild_required=True, unembedded_object_count=1, non_vector_issue_count=0, pg_state={}))
    env.update(FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY=missing, FAKE_SOURCE_REPLAY_INDEX_SUMMARY=missing,
               FAKE_LEGACY_RECONCILIATION_SUMMARY=summary, FAKE_LEGACY_RECONCILIATION_RC=rc)
    result = _run_deploy(root, env, sha, channel="dev")
    assert result.returncode != 0
    assert f"YGGDRASIL_DEPLOY_FAILURE_REASON={reason}" in result.stderr
    assert "private-canary" not in result.stdout + result.stderr
    events = _deploy_events(env)
    assert "api-cli index repair-missing --json" not in events
    assert not any("up -d --force-recreate api worker watcher" in event for event in events)


@pytest.mark.pg
@pytest.mark.parametrize("selected", [True, False])
def test_native_legacy_eligible_source_reprojects_before_missing_vector_repair(tmp_path, monkeypatch, selected, *, broader=False, preserve_existing=False, registry_enabled=False):
    """Native ordering reaches the real producer, PG CAS and strict doctor.

    Retained replay is isolated here to leave one evidence-free
    candidate for the new stage; all reconciliation and doctor SQL is real.
    """
    from types import SimpleNamespace
    import psycopg
    from click.testing import CliRunner
    from tests.cli.test_index_rebuild_cli import _legacy_source_fixture
    from app.cli import cli
    from app.cli import index_rebuild as repair
    from app.index import doctor
    from app.ops import native_source_bootstrap as native
    from app.stores import pg
    from app.db.dsn import resolve_dsn
    from app.db.db import ensure_schema
    from app.rebuildability.product_total_loss import evaluate_product_store_readiness

    recovery, state, root, source, raw, original, _, _, factory = _legacy_source_fixture(
        monkeypatch, tmp_path, selected=selected)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "1" if broader else "0")
    monkeypatch.setenv("VAULT_DIR", str(root))
    if registry_enabled:
        from tests.rebuildability.test_legacy_source_reconciliation import _enable_registry
        _enable_registry(monkeypatch, root)
    pg._TABLES_READY = False
    pg._ensure_tables()
    pg.truncate_pg_tables()
    store, index = pg.PgObjectStore(), pg.PgVectorIndex()
    store.put(original["object_id"], kind="note", source_ref=str(source), payload=original["payload"])
    healthy_id = None
    healthy_payload = None
    if preserve_existing:
        from uuid import uuid4
        from app.ingest.vault_alpha import _ingest_single
        from app.index.artifact_metadata import build_indexed_unit_payload, canonicalize_indexable_text
        healthy_id = uuid4()
        healthy_source = root / "Notes" / "existing.md"
        healthy_source.parent.mkdir(exist_ok=True)
        healthy_raw = f"---\nuuid: {healthy_id}\ntrust: human\nreview_state: reviewed\n---\nPreserved retained note.\n"
        healthy_source.write_text(healthy_raw)
        prepared = []
        _ingest_single(healthy_source, vault_root=root, trace_id="native-fixture",
                      raw_text=healthy_raw, write_companion_record=False,
                      reconcile_existing_projection=True, projection_sink=prepared.append)
        healthy_payload = prepared[0]
        store.put(healthy_id, kind="note", source_ref=str(healthy_source), payload=healthy_payload)
        client = factory()
        text = canonicalize_indexable_text(healthy_payload)
        index.upsert(healthy_id, kind="note", source_ref=str(healthy_source),
            payload=build_indexed_unit_payload(object_id=healthy_id, kind="note", source_ref=str(healthy_source),
                payload=healthy_payload, text=text, embedding_identity=client.identity),
            embedding=[2., 1.], model=client.identity.model, identity=client.identity)

    def healthy_vector():
        with psycopg.connect(resolve_dsn()) as conn:
            return conn.execute("SELECT embedding::text, payload, model, provider, dim, normalize FROM store_vector_index "
                "WHERE vault_binding_id = %s AND object_id = %s", (store.vault_binding_id, healthy_id)).fetchone()

    protected_vector = healthy_vector() if healthy_id is not None else None
    with psycopg.connect(resolve_dsn()) as conn:
        ensure_schema(conn)
        conn.execute("INSERT INTO objects (id, uuid, vault_binding_id, kind) VALUES (%s, %s, %s, 'note')",
                     (original["object_id"], original["object_id"], store.vault_binding_id))
        if healthy_id is not None:
            conn.execute("INSERT INTO objects (id, uuid, vault_binding_id, kind) VALUES (%s, %s, %s, 'note')",
                         (healthy_id, healthy_id, store.vault_binding_id))
    binding = SimpleNamespace(backend="pg", store=store)
    monkeypatch.setattr(repair.domain_objects, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(repair, "get_vector_index", lambda: index)
    monkeypatch.setattr(repair, "get_product_embedding_client", factory)
    monkeypatch.setattr(doctor, "get_vector_index", lambda: index)
    monkeypatch.setattr(doctor, "get_embeddings_client", lambda *args, **kwargs: factory())
    monkeypatch.setattr(native, "preflight", lambda selector: root)
    events = []

    def run(arguments):
        events.append(arguments)
        if arguments[0] == "settings":
            return {}
        if arguments[0] == "vault-alpha-ingest":
            return dict(scanned=0, ingested=0, errors=0, malformed=0, skipped_locked=0, skipped_invalid=0)
        result = CliRunner().invoke(cli, arguments)
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    monkeypatch.setattr(native, "_run_json", run)
    native.rebuild_if_needed("test:" + "a" * 40)
    assert events.index(["index", "reconcile-legacy", "--json"]) < events.index(["index", "repair-missing", "--json"])
    assert events[-1] == ["index", "doctor", "--json", "--strict"]
    projected = store.get(original["object_id"])
    if selected or broader or registry_enabled:
        assert projected["payload"]["frontmatter"]["trust"] == "human"
        assert projected["object_id"] == original["object_id"]
        assert index.present_object_ids() == ({str(original["object_id"])} | ({str(healthy_id)} if healthy_id else set()))
        assert state.embedded == [projected["payload"].get("content", "canonical body")]
    else:
        assert projected is None and index.present_object_ids() == ({str(healthy_id)} if healthy_id else set())
        assert state.embedded == []
    assert source.read_bytes() == raw
    assert evaluate_product_store_readiness(root, store.list_objects(limit=None)).ready
    assert recovery.reconcile_legacy_sources(binding, index, factory) == 0
    if healthy_id is not None:
        assert store.get(healthy_id)["payload"] == healthy_payload
        assert healthy_vector() == protected_vector
        assert healthy_source.read_text() == healthy_raw
    pg.truncate_pg_tables()


@pytest.mark.pg
@pytest.mark.parametrize("producer_kind", ["disabled", "filesystem", "registry"])
def test_native_legacy_reconciliation_reports_producer_policy_and_converges(tmp_path, monkeypatch, producer_kind):
    test_native_legacy_eligible_source_reprojects_before_missing_vector_repair(
        tmp_path, monkeypatch, selected=False, broader=producer_kind == "filesystem", preserve_existing=True,
        registry_enabled=producer_kind == "registry",
    )


@pytest.mark.parametrize("reason", ["source_post_rebuild_failed", "embedding_generation_failed",
                                  "vector_index_write_failed"])
def test_native_missing_vector_repair_refuses_ineligible_or_failed_rows(tmp_path: Path, reason) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    missing = json.dumps(dict(backend="PgVectorIndex", issues=["private-object-canary"],
        rebuild_required=True, unembedded_object_count=1, non_vector_issue_count=0, pg_state={}))
    env["FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"] = missing
    env["FAKE_SOURCE_REPLAY_INDEX_SUMMARY"] = missing
    _wire_real_missing_repair(root, env)
    env["REAL_REPAIR_FAILURE"] = {"source_post_rebuild_failed": "ineligible",
        "embedding_generation_failed": "embed", "vector_index_write_failed": "write"}[reason]
    result = _run_deploy(root, env, sha, channel="dev")
    assert result.returncode != 0
    assert f"YGGDRASIL_DEPLOY_FAILURE_REASON={reason}" in result.stderr
    assert "hostile-child-canary" not in result.stdout + result.stderr
    assert "private-object-canary" not in result.stdout + result.stderr
    assert not any("up -d --force-recreate api worker watcher" in event
                   for event in _deploy_events(env))
    assert not list((root / "ops/deployments").glob("*.json"))


def test_native_deploy_repairs_vector_only_gap_before_health_gate(tmp_path: Path) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    env["FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"] = json.dumps({
        "backend": "PgVectorIndex",
        "issues": ["1 object has no vector"],
        "rebuild_required": True,
        "unembedded_object_count": 1,
        "non_vector_issue_count": 0,
        "pg_state": {"rows": 1},
    })

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    preflight_doctor = events.index("api-cli index doctor --json")
    rebuild = events.index("source-rebuild")
    strict_doctor = events.index("api-cli index doctor --json --strict")
    runtime_start = next(
        i for i, event in enumerate(events)
        if "up -d --force-recreate api worker watcher" in event
    )
    assert events.count("source-rebuild") == 1
    assert preflight_doctor < rebuild < strict_doctor < runtime_start
    assert f"NATIVE_SOURCE_BOOTSTRAP=dev:{sha}" in "\n".join(events)


@pytest.mark.parametrize("counter", [1, True, "1", 0, -1, 3, None])
def test_native_deploy_reports_redacted_vector_projection_failure(tmp_path: Path, counter) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev")
    env["FAKE_SOURCE_RC"] = "79"
    env["FAKE_SOURCE_SUMMARY"] = json.dumps(dict(
        scanned=2, ingested=1, errors=1, malformed=0, skipped_locked=0,
        skipped_invalid=0, vector_projection_errors=counter,
        private="hostile-summary-canary /private/vault password=do-not-leak",
    ))
    result = _run_deploy(root, env, sha, channel="dev")
    assert result.returncode != 0
    assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr
    assert ("YGGDRASIL_DEPLOY_FAILURE_REASON=vector_projection_failed" in result.stderr) is (type(counter) is int and counter == 1)
    assert "hostile" not in result.stdout + result.stderr
    assert "/private/vault" not in result.stdout + result.stderr
    assert not any("up -d --force-recreate api worker watcher" in event for event in _deploy_events(env))
    assert not list((root / "ops/deployments").glob("*.json"))


@pytest.mark.parametrize("reason,code", [("embedding_generation_failed", 80), ("vector_index_write_failed", 81)])
def test_native_vector_write_failure_reaches_supervised_redacted_diagnostic(
    tmp_path: Path, monkeypatch, reason: str, code: int,
) -> None:
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root, env, sha = _native_source_harness(tmp_path, channel="dev")
    # Run the real CLI, note producer, and search projection. Only the
    # infrastructure/provider seams are isolated, not a fabricated CLI summary.
    (root / "app/ops/__init__.py").write_text("from pkgutil import extend_path\n__path__ = extend_path(__path__, __name__)\n")
    note = root / "tmp" / "retained.md"
    note.write_text("---\nuuid: 1c2428f2-0a13-498d-ae3a-12e5ce1bfd27\ntitle: Retained\n---\n\nFixture source body.\n")
    cli_stub = root / "app/cli.py"
    cli_stub.write_text(cli_stub.read_text().replace(
        'if args[:1] == ["vault-alpha-ingest"]:',
        '''if args[:1] == ["vault-alpha-ingest"]:
    import importlib.util
    package = Path(os.environ["REAL_CLI_PACKAGE"])
    spec = importlib.util.spec_from_file_location("app.cli", package / "__init__.py", submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["app.cli"] = module
    spec.loader.exec_module(module)
    module.cli()
if args[:1] == ["vault-alpha-ingest"]:''',
    ))
    site = tmp_path / "api-python-fixture" / "sitecustomize.py"
    site.write_text(site.read_text() + '''
from app.ingest import vault_alpha
from app.search import service
from app import stores
from app.components.embeddings import EmbeddingIdentity
paths.resolve_optional_vault_root = lambda **kwargs: Path(os.environ["FAKE_API_VAULT"])
from app.settings import runtime as settings_runtime
from app.settings.models import SettingsBundle
settings_runtime.get_settings_bundle = lambda: SettingsBundle()
class RecoveryStore:
    def put_and_reconcile_source_backed(self, object_id, **kwargs):
        return str(object_id)
class RefusedIndex:
    def upsert(self, **kwargs):
        raise RuntimeError("hostile-child-canary /private/vault password=do-not-leak")
vault_alpha.get_object_store = lambda: RecoveryStore()
vault_alpha._select_candidates = lambda *args, **kwargs: ([Path(os.environ["REAL_SOURCE_NOTE"])], ["."])
vault_alpha.classify_run = lambda *args, **kwargs: {}
stores.get_vector_index = lambda: RefusedIndex()
def embed(texts):
    if os.environ["REAL_SOURCE_FAILURE"] == "embedding_generation_failed":
        raise RuntimeError("hostile-child-canary /private/vault password=do-not-leak")
    return [[1.0, 0.0, 0.0]], EmbeddingIdentity(provider="mock", model="fixture", dim=3, normalize=True)
service.embed_docs = embed
''')
    env.update(REAL_CLI_PACKAGE=str(REPO_ROOT / "app/cli"), REAL_SOURCE_NOTE=str(note),
               REAL_SOURCE_FAILURE=reason, STORE_BACKEND="memory")
    emitted: list[bytes] = []
    monkeypatch.setattr(linux, "_emit_native_diagnostic", emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(["bash", str(root / "scripts/deploy_channel.sh"), "deploy", "dev", sha],
                       cwd=root, env=env, deploy_diagnostics=True)
    assert emitted == [(
        "PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n"
        f"MESSAGE=native deployment failure: stage=source_projection class={reason}\n"
    ).encode("ascii")]
    assert not any("up -d --force-recreate api worker watcher" in event for event in _deploy_events(env))
    assert not list((root / "ops/deployments").glob("*.json"))


def test_native_deploy_vector_repair_retry_converges_before_activation(tmp_path: Path) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    missing = dict(backend="PgVectorIndex", issues=["missing vector"], rebuild_required=True,
                   unembedded_object_count=1, non_vector_issue_count=0, pg_state={"rows": 1})
    env["FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"] = json.dumps(missing)
    env["FAKE_SOURCE_RC"] = "79"
    env["FAKE_SOURCE_SUMMARY"] = json.dumps(dict(scanned=2, ingested=1, errors=1, malformed=0,
        skipped_locked=0, skipped_invalid=0, vector_projection_errors=1))
    failed = _run_deploy(root, env, sha, channel="dev")
    assert failed.returncode != 0
    env["FAKE_SOURCE_RC"] = "0"
    del env["FAKE_SOURCE_SUMMARY"]
    retried = _run_deploy(root, env, sha, channel="dev")
    assert retried.returncode == 0, retried.stderr
    events = _deploy_events(env)
    strict = events.index("api-cli index doctor --json --strict")
    activation = next(i for i, event in enumerate(events)
                      if "up -d --force-recreate api worker watcher" in event)
    assert strict < activation
    assert events.count("source-rebuild") == 2


def test_native_deploy_fails_closed_when_vector_repair_does_not_converge(
    tmp_path: Path,
) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    missing_vector = {
        "backend": "PgVectorIndex",
        "issues": ["1 object has no vector"],
        "rebuild_required": True,
        "unembedded_object_count": 1,
        "non_vector_issue_count": 0,
        "pg_state": {"rows": 1},
    }
    env["FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"] = json.dumps(missing_vector)
    env["FAKE_SOURCE_INDEX_SUMMARY"] = json.dumps(missing_vector)
    env["FAKE_SOURCE_INDEX_RC"] = "2"

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode != 0
    events = _deploy_events(env)
    assert events.count("source-rebuild") == 1
    assert events.index("source-rebuild") < events.index("api-cli index doctor --json --strict")
    assert not any("up -d --force-recreate api worker watcher" in event for event in events)
    assert not list((root / "ops/deployments").glob("*.json"))
    assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr
    assert "hostile-child-canary" not in result.stdout + result.stderr


def test_native_deploy_refuses_unrecognized_index_preflight(tmp_path: Path) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    env["FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"] = "{}"

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode != 0
    events = _deploy_events(env)
    assert "api-cli index doctor --json" in events
    assert "source-rebuild" not in events
    assert not any("up -d --force-recreate api worker watcher" in event for event in events)
    assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr
    assert "hostile-child-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "other_issue",
    [
        "Identity mismatch for model: expected primary, stored other.",
        "1 rows have embeddings not matching the recorded dimension.",
        "Mixed embedding identities in index: primary, fallback.",
    ],
)
def test_native_deploy_does_not_rebuild_vector_gap_with_other_index_issue(
    tmp_path: Path, other_issue: str,
) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    vector_issue = "1 store_objects rows have no embedded store_vector_index row: object-id"
    diagnosis = {
        "backend": "PgVectorIndex",
        "issues": [other_issue, vector_issue],
        "rebuild_required": True,
        "unembedded_object_count": 1,
        "non_vector_issue_count": 1,
        "pg_state": {"rows": 1},
    }
    env["FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY"] = json.dumps(diagnosis)
    env["FAKE_SOURCE_INDEX_SUMMARY"] = json.dumps(diagnosis)
    env["FAKE_SOURCE_INDEX_RC"] = "2"

    result = _run_deploy(root, env, sha, channel="dev")

    assert result.returncode != 0
    events = _deploy_events(env)
    assert "source-rebuild" not in events
    assert "api-cli index doctor --json --strict" in events
    assert not any(
        "up -d --force-recreate api worker watcher" in event for event in events
    )
    assert not list((root / "ops/deployments").glob("*.json"))
    assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr
    assert "hostile-child-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize("rows,refused", [
    ([], False),
    ([{"kind": "note", "payload": {}}], True),
    ([{"payload": {}}], True),
    ([{"kind": "builder_learning", "payload": {}}], False),
])
def test_native_empty_vault_requires_empty_product_projection(
    tmp_path: Path, rows: list[dict], refused: bool,
) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev", ready=True)
    layout = root / "tmp/⚙️ System/vault.layout.md"
    layout.parent.mkdir(parents=True)
    layout.write_text(
        "---\nsystem_folder: ⚙️ System\ninbox_folder: Inbox\ndesk_folder: Desk\n"
        "include_folders:\n  - Notes\n---\n\nEmpty-source fixture layout.\n",
        encoding="utf-8",
    )
    (root / "tmp/Notes").mkdir()
    site = tmp_path / "api-python-fixture/sitecustomize.py"
    text = site.read_text(encoding="utf-8")
    override = (
        'rebuildability.evaluate_product_store_readiness = lambda root, rows: SimpleNamespace(\n'
        '    ready=Path(os.environ["FAKE_API_READY_FILE"]).exists(),\n'
        '    state="ready" if Path(os.environ["FAKE_API_READY_FILE"]).exists() else "refused")\n'
    )
    assert text.count(override) == 1
    text = text.replace(override, "")
    store = 'store=SimpleNamespace(list_objects=lambda **kwargs: []),'
    assert text.count(store) == 1
    site.write_text(text.replace(
        store,
        'store=SimpleNamespace(list_objects=lambda **kwargs: iter('
        f'{rows!r})),',
    ), encoding="utf-8")
    env["FAKE_SOURCE_SUMMARY"] = json.dumps({
        "scanned": 0, "ingested": 0, "errors": 0, "malformed": 0,
        "skipped_locked": 0, "skipped_invalid": 0,
    })

    result = _run_deploy(root, env, sha)

    events = _deploy_events(env)
    if refused:
        assert result.returncode != 0
        assert events.count("source-rebuild") == 1
        assert not any("up -d --force-recreate api" in event for event in events)
        assert not any("/readyz" in event for event in events)
        assert "api-cli index doctor --json --strict" not in events
        assert not list((root / "ops/deployments").glob("*.json"))
        assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "source-rebuild" not in events
        assert "api-cli index doctor --json --strict" in events
    assert "hostile-child-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize("database_target", ["local", "external"])
def test_native_source_rebuild_retains_bws_api_context_and_writer_fence(
    tmp_path: Path, database_target: str
) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="test")
    env["BWS_DATABASE_TARGET"] = database_target
    if database_target == "external":
        env["DATABASE_URL"] = env["DB_DSN"] = "postgresql://writer@db.example.invalid:5432/app_test"
    result = _run_deploy(root, env, sha, channel="test")
    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    source_position = next(i for i, event in enumerate(events) if "NATIVE_SOURCE_BOOTSTRAP=" in event)
    assert any("stop api worker watcher heimdal-capture-watch companion-ui" in event
               for event in events[:source_position])
    assert not any("up -d --force-recreate api" in event for event in events[:source_position])
    assert f"source-probe channel=test image={sha} api-context={env['HOST_SECRET_RUNTIME_ENV_FILE_API']}" in events
    assert any(event == "bws-guard" for event in events[:source_position])
    assert ("docker-compose.bws-external.yml" in events[source_position]) is (database_target == "external")
    api = _compose("docker-compose.yaml")["services"]["api"]
    assert any(isinstance(item, dict) and "HOST_SECRET_RUNTIME_ENV_FILE_API" in item["path"] for item in api["env_file"])
    assert api["environment"]["NATIVE_SOURCE_BOOTSTRAP"] == ""
    assert "--entrypoint" not in events[source_position]
    assert events[source_position].endswith(" api")
    assert "POSTGRES_PASSWORD=" not in events[source_position]


@pytest.mark.parametrize("fault", [
    "missing", "malformed", "bad_json", "errors", "locked", "invalid", "count_mismatch",
    "wrong_type", "exit", "product_unready", "index_unready", "index_unknown",
])
def test_native_source_rebuild_fails_closed_on_incomplete_projection(tmp_path: Path, fault: str) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev")
    summary = {"scanned": 2, "ingested": 2, "errors": 0, "malformed": 0,
               "skipped_locked": 0, "skipped_invalid": 0}
    if fault == "missing":
        del summary["errors"]
    elif fault == "malformed":
        summary["malformed"] = 1
    elif fault in {"errors", "locked", "invalid"}:
        summary[{"locked": "skipped_locked", "invalid": "skipped_invalid"}.get(fault, fault)] = 1
    elif fault == "count_mismatch":
        summary["ingested"] = 1
    elif fault == "wrong_type":
        summary["scanned"] = True
    elif fault == "exit":
        env["FAKE_SOURCE_RC"] = "42"
    elif fault == "product_unready":
        env["FAKE_SOURCE_PREADINESS"] = "0"
    elif fault == "index_unready":
        env["FAKE_SOURCE_INDEX_RC"] = "2"
    elif fault == "index_unknown":
        env["FAKE_SOURCE_INDEX_SUMMARY"] = '{}'
    env["FAKE_SOURCE_SUMMARY"] = json.dumps(summary)
    if fault == "bad_json":
        env["FAKE_SOURCE_SUMMARY"] = "hostile-child-canary malformed summary"
    result = _run_deploy(root, env, sha)
    assert result.returncode != 0
    events = _deploy_events(env)
    assert events.count("source-rebuild") == 1
    assert not any("up -d --force-recreate api" in event for event in events)
    assert not list((root / "ops/deployments").glob("*.json"))
    assert "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection" in result.stderr
    assert "hostile-child-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize("fault", ["syntax", "foreign_channel", "foreign_image", "instance", "vault_context", "memory"])
def test_native_api_source_selector_refuses_before_source_write(tmp_path: Path, fault: str) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev")
    env.update(PYTHONPATH=env["FAKE_API_PYTHONPATH"], NATIVE_SOURCE_BOOTSTRAP=f"dev:{sha}")
    if fault == "syntax":
        env["NATIVE_SOURCE_BOOTSTRAP"] = f"dev:{sha};echo hostile"
    elif fault == "foreign_channel":
        env["NATIVE_SOURCE_BOOTSTRAP"] = f"test:{sha}"
    elif fault == "foreign_image":
        env["NATIVE_SOURCE_BOOTSTRAP"] = "dev:" + "a" * 40
    elif fault == "instance":
        env["FAKE_API_INSTANCE_RC"] = "75"
    elif fault == "vault_context":
        env["FAKE_API_CONTEXT_RC"] = "75"
    else:
        env["FAKE_API_BACKEND"] = "memory"
    result = subprocess.run(["bash", str(root / "api-command.sh")], cwd=root, env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    events = _deploy_events(env)
    assert "source-rebuild" not in events
    assert "api-migrations" not in events
    assert not any(event.startswith("api-cli ") for event in events)
    assert "hostile" not in result.stdout + result.stderr


def test_native_source_selector_absent_preserves_ordinary_api_start(tmp_path: Path) -> None:
    root, env, _sha = _native_source_harness(tmp_path, channel="dev")
    uvicorn = tmp_path / "bin/uvicorn"
    uvicorn.write_text('#!/bin/bash\nprintf "ordinary-api %s\\n" "$*" >> "${FAKE_DEPLOY_EVENT_LOG:?}"\n', encoding="utf-8")
    uvicorn.chmod(0o755)
    env.update(PYTHONPATH=env["FAKE_API_PYTHONPATH"], NATIVE_SOURCE_BOOTSTRAP="")
    result = subprocess.run(["bash", str(root / "api-command.sh")], cwd=root, env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    events = _deploy_events(env)
    assert events.count("api-migrations") == 1
    assert "ordinary-api app.main:app --host 0.0.0.0 --port 8000" in events
    assert not any(event.startswith("api-cli ") for event in events)


@pytest.mark.parametrize("unquiesced", [False, True])
def test_native_source_rebuild_failure_preserves_recovery_fences(tmp_path: Path, unquiesced: bool) -> None:
    root, env, prior_sha = _native_source_harness(tmp_path, channel="dev")
    (root / "config/deploy/dev.env").write_text(f"APP_IMAGE_TAG={prior_sha}\n", encoding="utf-8")
    (root / "target.txt").write_text("target", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "target"], cwd=root, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env.update(FAKE_SHA=sha, VCS_REF=sha, APP_IMAGE_TAG=sha, BWS_DEPLOY_TARGET_REVISION=sha, FAKE_SOURCE_RC="42")
    if unquiesced:
        docker = tmp_path / "bin/docker"
        docker.write_text(docker.read_text(encoding="utf-8").replace(
            'case "$*" in\n',
            '''if [ "${1:-}" = ps ]; then
  printf '%s\\n' 0123456789ab
  exit 0
fi
if [ "${1:-}" = inspect ] && [[ "$*" == *"State.Running"* ]]; then
  printf '/pkm-dev-source-bootstrap-%s pkm-dev api True %s %s true\\n' \
    "${BWS_DEPLOY_OPERATION_ID}" "${BWS_DEPLOY_OPERATION_ID}" "${BWS_DEPLOY_TARGET_REVISION}"
  exit 0
fi
if [ "${1:-}" = stop ]; then exit 77; fi
case "$*" in
''', 1,
        ), encoding="utf-8")
    result = _run_deploy(root, env, sha)
    assert result.returncode != 0
    events = _deploy_events(env)
    assert events.count("source-rebuild") == 1
    assert not list((root / "ops/deployments").glob("*.json"))
    assert f"APP_IMAGE_TAG={prior_sha}\n" in (root / "config/deploy/dev.previous.env").read_text()
    if unquiesced:
        assert f"APP_IMAGE_TAG={sha}\n" in (root / "config/deploy/dev.env").read_text()
        assert not any("up -d --force-recreate api" in event for event in events)
        assert "native source producer quiescence is unproven" in result.stderr
    else:
        assert f"APP_IMAGE_TAG={prior_sha}\n" in (root / "config/deploy/dev.env").read_text()
        assert any("up -d --force-recreate api" in event for event in events)
    assert "hostile-child-canary" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("worker_state", "expected_rc"),
    [("running", 0), ("exited", 1)],
)
def test_source_projection_refusal_restores_complete_previous_runtime(
    tmp_path: Path, worker_state: str, expected_rc: int
) -> None:
    """Compensation is healthy only when the complete runtime is running."""
    script = SCRIPT.read_text(encoding="utf-8")
    start = script.index("rollback_runtime_complete_gate()")
    end = script.index("\nrollback_failed_startup()", start)
    gate = script[start:end]
    rows = json.dumps([
        {"Service": "api", "State": "running", "Health": "healthy"},
        {"Service": "worker", "State": worker_state, "Health": ""},
        {"Service": "watcher", "State": "running", "Health": ""},
    ])
    compose = tmp_path / "compose"
    compose.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"${FAKE_COMPOSE_ROWS:?}\"\n",
        encoding="utf-8",
    )
    compose.chmod(0o755)
    env = os.environ.copy()
    env.update(COMPOSE_BIN=str(compose), FAKE_COMPOSE_ROWS=rows, PYTHON=sys.executable)
    pin = tmp_path / 'channel.env'
    pin.write_text('APP_IMAGE_TAG=' + 'a' * 40 + '\n')
    result = subprocess.run(
        ["bash", "-c", f'''source "$1"
pin_file="$2"
channel=dev
compose() {{ "${{COMPOSE_BIN}}"; }}
{gate}
rollback_runtime_complete_gate''', '--', str(REPO_ROOT / 'scripts/lib/deploy_channel_compose.sh'), str(pin)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected_rc, result.stdout + result.stderr


def test_native_source_timeout_terminates_descendants_even_when_parent_exits(tmp_path: Path) -> None:
    import time
    from app.ops.native_source_bootstrap import wait_for_owned_child
    child = tmp_path / "child.py"
    stopped = tmp_path / "stopped"
    child.write_text('''import signal, subprocess, sys, time
def stop(*args):
    open(sys.argv[2], "w").write("parent stopped")
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
subprocess.Popen([sys.executable, "-c", "import signal,sys,time,os; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)", sys.argv[1]])
time.sleep(30)
''', encoding="utf-8")
    pid_file = tmp_path / "descendant.pid"
    assert wait_for_owned_child([sys.executable, str(child), str(pid_file), str(stopped)], timeout=3) == 124
    assert stopped.is_file()
    pid = int(pid_file.read_text())
    # A killed orphan may remain a zombie until init reaps it. It cannot execute
    # a producer; absence or zombie is the finite process-state proof here.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if not state or state.startswith("Z"):
            break
        time.sleep(0.05)
    assert not state or state.startswith("Z"), state


@pytest.mark.parametrize("signum", [15, 2])
def test_native_source_signal_terminates_owned_child_group(tmp_path: Path, signum: int) -> None:
    import time
    child = tmp_path / "child.py"
    pid_file = tmp_path / "child.pid"
    child.write_text('''import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
open(sys.argv[1], "w").write(str(os.getpid()))
time.sleep(30)
''', encoding="utf-8")
    runner = subprocess.Popen([
        sys.executable, "-c",
        "import sys; from app.ops.native_source_bootstrap import wait_for_owned_child; "
        "raise SystemExit(wait_for_owned_child(sys.argv[1:], timeout=60))",
        sys.executable, str(child), str(pid_file),
    ], cwd=REPO_ROOT)
    try:
        deadline = time.monotonic() + 10
        while not pid_file.is_file() and time.monotonic() < deadline:
            assert runner.poll() is None
            time.sleep(0.05)
        assert pid_file.is_file()
        pid = int(pid_file.read_text())
        runner.send_signal(signum)
        assert runner.wait(timeout=10) == 128 + signum
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        assert not state or state.startswith("Z"), state
    finally:
        if runner.poll() is None:
            runner.terminate()
        runner.wait(timeout=10)


@pytest.mark.parametrize("fault", ["none", "operation", "revision", "name", "project", "service", "oneoff", "unavailable", "stop_lost_ack", "still_running"])
def test_native_source_container_termination_requires_exact_ownership(tmp_path: Path, monkeypatch, fault: str) -> None:
    from app.ops.native_source_bootstrap import quiesce_owned_container
    operation = "03b3bb2f-6d85-499a-8b45-e397f56812e1"
    revision = "a" * 40
    name = "pkm-test-source-bootstrap-" + operation
    producer = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    docker = tmp_path / "docker"
    event_log = tmp_path / "events"
    state = tmp_path / "stopped"
    docker.write_text('''#!/usr/bin/env python3
import os, signal, sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ["FAKE_CONTAINER_EVENTS"], "a") as stream:
    stream.write(args[0] + "\\n")
if os.environ["FAKE_CONTAINER_FAULT"] == "unavailable": raise SystemExit(42)
if args[0] == "ps":
    print("0123456789ab")
elif args[0] == "inspect":
    operation = os.environ["FAKE_CONTAINER_OPERATION"]
    revision = os.environ["FAKE_CONTAINER_REVISION"]
    name = os.environ["FAKE_CONTAINER_NAME"]
    project = "pkm-test"
    service = "api"
    oneoff = "True"
    fault = os.environ["FAKE_CONTAINER_FAULT"]
    if fault == "operation": operation = "00000000-0000-4000-8000-000000000002"
    if fault == "revision": revision = "b" * 40
    if fault == "name": name = "foreign"
    if fault == "project": project = "pkm-dev"
    if fault == "service": service = "worker"
    if fault == "oneoff": oneoff = "False"
    running = "false" if Path(os.environ["FAKE_CONTAINER_STOPPED"]).exists() else "true"
    print(f"/{name} {project} {service} {oneoff} {operation} {revision} {running}")
elif args[0] == "stop":
    if os.environ["FAKE_CONTAINER_FAULT"] == "still_running": raise SystemExit(42)
    os.kill(int(os.environ["FAKE_CONTAINER_PID"]), signal.SIGTERM)
    Path(os.environ["FAKE_CONTAINER_STOPPED"]).touch()
    if os.environ["FAKE_CONTAINER_FAULT"] == "stop_lost_ack": raise SystemExit(42)
elif args[0] != "rm": raise SystemExit(43)
''', encoding="utf-8")
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    for key, value in {
        "FAULT": fault, "PID": str(producer.pid), "OPERATION": operation,
        "REVISION": revision, "NAME": name, "STOPPED": str(state), "EVENTS": str(event_log),
    }.items():
        monkeypatch.setenv("FAKE_CONTAINER_" + key, value)
    try:
        assert quiesce_owned_container("test", name, operation, revision) is (fault in {"none", "stop_lost_ack"})
        events = event_log.read_text().splitlines()
        if fault in {"operation", "revision", "name", "project", "service", "oneoff", "unavailable"}:
            assert "stop" not in events and "rm" not in events
            assert producer.poll() is None
        if fault in {"none", "stop_lost_ack"}:
            producer.wait(timeout=2)
            assert events.index("inspect") < events.index("stop") < events.index("rm")
        if fault == "still_running":
            assert "rm" not in events
    finally:
        if producer.poll() is None:
            producer.terminate()
        producer.wait(timeout=2)


def test_native_source_cleanup_requires_current_parent_guard(tmp_path: Path) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev")
    guard = root / "app/ops/postgres_deploy_linux.py"
    guard.write_text(guard.read_text() +
        'from pathlib import Path\n'
        'if Path(os.environ["FAKE_API_READY_FILE"]).exists(): raise SystemExit(78)\n', encoding="utf-8")
    env["FAKE_SOURCE_RC"] = "42"
    result = _run_deploy(root, env, sha)
    assert result.returncode != 0
    events = _deploy_events(env)
    assert events.count("source-rebuild") == 1
    assert not any(event.startswith("docker ps --all") or event.startswith("docker stop") or
                   event.startswith("docker rm") or "up -d --force-recreate api" in event for event in events)
    assert "native source producer quiescence is unproven" in result.stderr


@pytest.mark.parametrize("fault", [
    "created", "running", "paused", "restarting", "removing", "unknown",
    "transition", "malformed", "unavailable", "timeout", "membership_changed",
    "identity_changed", "inconsistent_state", "duplicate_id",
])
def test_native_source_api_oneoff_blocks_same_id_reconciliation(tmp_path: Path, monkeypatch, capsys, fault: str) -> None:
    from dataclasses import asdict
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
    root = tmp_path / "checkout"
    lock = root / "config/deploy/test.env.lock"
    lock.mkdir(parents=True, mode=0o700)
    (lock / "bws-owner").touch(mode=0o600)
    journal = DeployJournal(tmp_path / "journal", "test")
    plan = DeployPlan("test", "a" * 40, ("db", "api"), ("postgres-db", "postgres-api"))
    operation = str(uuid4())
    journal.bind_request(operation, plan, False, create=True)
    for stage in ("prepared", "preflighted", "materialized", "activating"):
        journal.write(operation, stage)
    config = SimpleNamespace(channel="test", root=root, journal=journal)
    monkeypatch.setattr(linux.LinuxConfig, "load", lambda _channel: config)
    monkeypatch.setattr(linux.LinuxEffects, "activate", lambda *_args: pytest.fail("must not replay"))
    monkeypatch.setattr(linux.LinuxEffects, "compose", lambda *_args: '[{"Service":"api","State":"running","Health":""}]')
    active = {"value": True}
    container_id = "0123456789abcdef" * 4
    commands = []
    inspections = []
    inventories = []
    def command(argv, **kwargs):
        assert kwargs["timeout"] == 15
        commands.append(argv)
        if argv[:2] == ["docker", "ps"]:
            if any(value.startswith('name=') for value in argv):
                return ''
            inventories.append(argv)
            # A created/unknown one-off is absent from Docker's running-only
            # inventory. Exercise that omission through actual reconciliation.
            if not active["value"] or ("--all" not in argv and fault != "running"):
                return ""
            if fault == "membership_changed" and len(inventories) > 1:
                return container_id + "\n" + "f" * 64
            if fault == "duplicate_id":
                return container_id + "\n" + container_id
            return container_id
        assert argv[:2] == ["docker", "inspect"]
        inspections.append(argv)
        if fault == "unavailable":
            raise linux.PostgresDeployError()
        if fault == "timeout":
            raise subprocess.TimeoutExpired(argv, 15, output="hostile-child-canary", stderr="private-endpoint")
        if fault == "malformed":
            return "hostile-child-canary private-endpoint"
        identity = "f" * 64 if fault == "identity_changed" else container_id
        state = "exited" if fault in {"membership_changed", "identity_changed", "inconsistent_state"} else fault
        if fault == "transition":
            state = "exited" if len(inspections) == 1 else "created"
        running = "true" if state in {"running", "paused", "restarting"} or fault == "inconsistent_state" else "false"
        paused = "true" if state == "paused" else "false"
        restarting = "true" if state == "restarting" else "false"
        pid = "23" if running == "true" else "0"
        return f"{identity} {state} {running} {paused} {restarting} {pid}"
    monkeypatch.setattr(linux, "_command", command)
    supervisor = linux.DeploymentSupervisor(config)
    request = {"action":"reconcile-failed", "operation_id":operation, "plan":asdict(plan), "bootstrap":False}
    prior = (journal.directory / "test.json").read_bytes()
    with pytest.raises(PostgresDeployError):
        supervisor.request(request)
    assert (journal.directory / "test.json").read_bytes() == prior
    assert lock.is_dir()
    assert inventories
    assert all("--all" in argv and "--no-trunc" in argv for argv in inventories)
    assert all("label=com.docker.compose.oneoff=True" in argv for argv in inventories)
    assert not any(argv[1] in {"stop", "rm", "start", "restart", "kill"} for argv in commands)
    captured = capsys.readouterr()
    assert captured.out + captured.err == ""
    active["value"] = False
    receipt = supervisor.request(request)
    assert receipt["receipt"]["terminal_result"] == "failed"
    assert not lock.exists()
    assert supervisor.request({**request, "action":"join"}) == receipt


@pytest.mark.parametrize("state", ["exited", "dead"])
def test_native_source_completed_oneoff_allows_same_id_reconciliation(tmp_path: Path, monkeypatch, state: str) -> None:
    from dataclasses import asdict
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan
    root = tmp_path / "checkout"
    lock = root / "config/deploy/test.env.lock"
    lock.mkdir(parents=True, mode=0o700)
    (lock / "bws-owner").touch(mode=0o600)
    journal = DeployJournal(tmp_path / "journal", "test")
    plan = DeployPlan("test", "a" * 40, ("db", "api"), ("postgres-db", "postgres-api"))
    operation = str(uuid4())
    journal.bind_request(operation, plan, False, create=True)
    for stage in ("prepared", "preflighted", "materialized", "activating"):
        journal.write(operation, stage)
    config = SimpleNamespace(channel="test", root=root, journal=journal)
    monkeypatch.setattr(linux.LinuxConfig, "load", lambda _channel: config)
    monkeypatch.setattr(linux.LinuxEffects, "activate", lambda *_args: pytest.fail("must not replay"))
    monkeypatch.setattr(linux.LinuxEffects, "compose", lambda *_args: '[{"Service":"api","State":"running","Health":""}]')
    container_id = "0123456789abcdef" * 4
    commands = []
    def command(argv, **kwargs):
        assert kwargs["timeout"] == 15
        commands.append(argv)
        if argv[:2] == ["docker", "ps"]:
            if any(value.startswith('name=') for value in argv):
                return ''
            assert "--all" in argv and "--no-trunc" in argv
            return container_id
        assert argv[:2] == ["docker", "inspect"]
        assert argv[-1] == container_id
        return f"{container_id} {state} false false false 0"
    monkeypatch.setattr(linux, "_command", command)
    supervisor = linux.DeploymentSupervisor(config)
    request = {"action":"reconcile-failed", "operation_id":operation, "plan":asdict(plan), "bootstrap":False}
    receipt = supervisor.request(request)
    assert receipt["receipt"]["terminal_result"] == "failed"
    assert not lock.exists()
    assert sum(argv[:2] == ["docker", "inspect"] for argv in commands) == 2
    assert not any(argv[1] in {"stop", "rm", "start", "restart", "kill"} for argv in commands)
    assert supervisor.request({**request, "action":"join"}) == receipt


@pytest.mark.parametrize("fault", ["timeout", "unavailable", "malformed"])
def test_native_source_oneoff_census_unknown_stays_pending(tmp_path: Path, monkeypatch, capsys, fault: str) -> None:
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    effects = linux.LinuxEffects(SimpleNamespace(channel="test", root=tmp_path))
    def probe(argv, **kwargs):
        assert argv[:2] == ["docker", "ps"]
        assert kwargs["timeout"] == 15
        if fault == "timeout":
            raise subprocess.TimeoutExpired(argv, 15, output="hostile-child-canary", stderr="private-endpoint")
        return SimpleNamespace(returncode=42 if fault == "unavailable" else 0,
                               stdout="hostile-child-canary", stderr="private-endpoint")
    monkeypatch.setattr(linux.subprocess, "run", probe)
    monkeypatch.setattr(effects, "compose", lambda *args: pytest.fail("unknown census is not quiescence"))
    assert effects.quiescent() is False
    captured = capsys.readouterr()
    assert captured.out + captured.err == ""


def test_native_source_unbound_api_preserves_idle_without_source_write(tmp_path: Path) -> None:
    root, env, sha = _native_source_harness(tmp_path, channel="dev")
    env["FAKE_API_UNBOUND"] = "1"
    result = _run_deploy(root, env, sha)
    assert result.returncode == 0, result.stdout + result.stderr
    events = _deploy_events(env)
    assert any("NATIVE_SOURCE_BOOTSTRAP=" in event for event in events)
    assert not any(event.startswith("api-cli ") for event in events)
    assert any("up -d --force-recreate api" in event for event in events)


@pytest.mark.parametrize("fault", ["missing", "not_directory", "symlink_loop", "inaccessible"])
def test_native_source_configured_invalid_root_never_becomes_unbound(tmp_path: Path, monkeypatch, fault: str) -> None:
    from app.ops import native_source_bootstrap as source
    from app import objects, version
    revision = "a" * 40
    selector = "test:" + revision
    selected = tmp_path / "selected"
    if fault == "not_directory":
        selected.write_text("not a vault")
    elif fault == "symlink_loop":
        selected.symlink_to(selected)
    elif fault == "inaccessible":
        selected.mkdir()
        original_exists = Path.exists
        def exists(path):
            if path == selected:
                raise PermissionError("configured vault inaccessible")
            return original_exists(path)
        monkeypatch.setattr(Path, "exists", exists)
    monkeypatch.setenv("NATIVE_SOURCE_BOOTSTRAP", selector)
    monkeypatch.setenv("PKM_ENVIRONMENT", "test")
    monkeypatch.setenv("VAULT_ROOT", str(selected))
    # A usable foreign root cannot rescue the selected canonical API root.
    monkeypatch.setenv("VAULT_ROOT_DEV", str(tmp_path))
    monkeypatch.setenv("VAULT_ROOT_TEST", str(tmp_path))
    monkeypatch.setattr(version, "get_runtime_version", lambda: {"git_sha": revision})
    monkeypatch.setattr(objects, "resolve_store_backend", lambda: "pg")
    monkeypatch.setattr(
        objects,
        "resolve_object_store_port",
        lambda: pytest.fail("invalid root must be rejected before StorePort construction"),
    )
    monkeypatch.setattr(source, "_instance_preflight", lambda channel: None)
    monkeypatch.setattr(source, "_run_json", lambda *args: pytest.fail("must refuse before SourceWrite"))
    with pytest.raises((RuntimeError, OSError, ValueError)):
        source.rebuild_if_needed(selector)


@pytest.mark.parametrize("value", [None, {}, [], {"scanned": 0},
    {"scanned": "0", "ingested": 0, "errors": 0, "malformed": 0, "skipped_locked": 0, "skipped_invalid": 0},
    {"scanned": 0, "ingested": 0, "errors": -1, "malformed": 0, "skipped_locked": 0, "skipped_invalid": 0},
    {"scanned": 0, "ingested": 0, "errors": False, "malformed": 0, "skipped_locked": 0, "skipped_invalid": 0},
])
def test_native_source_summary_unknown_is_not_empty_success(value) -> None:
    from app.ops.native_source_bootstrap import source_rebuild_counts
    with pytest.raises(ValueError):
        source_rebuild_counts(value)


@pytest.mark.parametrize('fault,reason', [
    ('identity', 'embedding_identity_unavailable'),
    ('invalid_identity', 'embedding_identity_unavailable'),
    ('service', 'embedding_service_unavailable'),
    ('readiness', 'embedding_service_not_ready'),
    ('pull', 'embedding_model_unavailable'),
    ('model', 'embedding_model_not_ready'),
    ('probe', 'embedding_probe_failed'),
    ('context', 'embedding_context_invalid'),
    ('host_identity', 'embedding_identity_invalid'),
])
def test_native_source_embedding_preflight_failures_are_finitely_attributed(tmp_path, monkeypatch, fault, reason):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root, env, _prior, sha, _previous = _native_source_harness_with_prior_deployment(tmp_path)
    variables = {'identity': 'FAKE_EMBEDDING_IDENTITY_RC', 'service': 'FAKE_OLLAMA_UP_RC',
                 'readiness': 'FAKE_OLLAMA_LIST_RC', 'pull': 'FAKE_OLLAMA_PULL_RC',
                 'probe': 'FAKE_EMBEDDING_PROBE_RC'}
    if fault in variables:
        env[variables[fault]] = '42'
    if fault in {'pull', 'model'}:
        Path(env['FAKE_OLLAMA_MODEL_STATE_FILE']).unlink()
    if fault == 'model':
        docker = tmp_path / 'bin/docker'
        docker.write_text(docker.read_text().replace(': > "${FAKE_OLLAMA_MODEL_STATE_FILE:?}"', ':'))
    if fault == 'invalid_identity':
        env['FAKE_EMBEDDING_IDENTITY_EXTRA_OUTPUT'] = 'hostile-child-canary /private/vault password=do-not-leak'
    if fault in {'context', 'host_identity'}:
        # These defensive branches sit behind earlier whole-deployment guards
        # and Compose redaction. Execute the actual gate body with only that
        # predecessor seam isolated, then use the real supervisor boundary.
        script = SCRIPT.read_text()
        gate = script[script.index('native_source_failure() {'):script.index('native_source_projection_gate() {')]
        payload = '{"provider":"BAD", "model":"hostile-child-canary"}'
        operation = 'invalid' if fault == 'context' else env['BWS_DEPLOY_OPERATION_ID']
        command = (gate + '\naction=deploy\nactivation_scope=full\ntarget_sha=' + sha
                   + '\nBWS_DEPLOY_OPERATION_ID=' + operation
                   + '\ncompose() { printf \'%s\\n\' \' ' + payload + '\'; }\n'
                   + 'native_source_embedding_preflight_gate\nrc=$?\n'
                   + 'printf "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection\\n" >&2\nexit "$rc"\n')
        emitted = []
        monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
        with pytest.raises(PostgresDeployError):
            linux._command(['bash', '-c', command], env=env, deploy_diagnostics=True)
        assert emitted == [(
            'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
            f'MESSAGE=native deployment failure: stage=source_projection class={reason}\n'
        ).encode('ascii')]
        return
    if fault == 'readiness':
        sleeper = tmp_path / 'bin/sleep'
        sleeper.write_text('#!/bin/sh\nexit 0\n')
        sleeper.chmod(0o755)
    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(['bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', 'dev', sha],
                       cwd=root, env=env, deploy_diagnostics=True)
    assert emitted == [(
        'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        f'MESSAGE=native deployment failure: stage=source_projection class={reason}\n'
    ).encode('ascii')]
    assert 'source-rebuild' not in _deploy_events(env)
    assert not list((root / 'ops/deployments').glob('*.json'))


def test_supervised_compose_guard_refusal_has_reserved_status_before_docker(tmp_path):
    root, env, sha = _native_source_harness(tmp_path, channel='dev', ready=True)
    env['FAKE_BWS_COMPOSE_GUARD_RC'] = '42'
    script = root / 'scripts/lib/deploy_channel_compose.sh'
    result = subprocess.run(
        ['bash', '-c', 'source "$1"; deploy_channel_compose "$2" dev docker-compose.dev.yml pkm-dev "$3" run',
         'bash', str(script), str(root), str(root / 'config/deploy/dev.env')],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 120
    assert not Path(env['FAKE_DEPLOY_EVENT_LOG']).exists()


@pytest.mark.parametrize('guarded_call', [
    'up',
    'list',
    'show',
    'pull',
    'NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER',
])
def test_native_embedding_probe_guard_refusal_is_distinct_from_probe_failures(tmp_path, monkeypatch, guarded_call):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root, env, _prior, sha, _previous = _native_source_harness_with_prior_deployment(tmp_path)
    script = SCRIPT.read_text()
    gate = script[script.index('native_source_failure() {'):script.index('native_source_projection_gate() {')]
    show_failure = '    *ollama\\ show*) return 1 ;;\n' if guarded_call == 'pull' else ''
    command = ('set -euo pipefail\n' + gate + '\naction=deploy\nactivation_scope=full\ntarget_sha=' + sha
               + '\nBWS_DEPLOY_OPERATION_ID=' + env['BWS_DEPLOY_OPERATION_ID']
               + '\nHOST_SECRET_RUNTIME_ENV_FILE_API=' + env['HOST_SECRET_RUNTIME_ENV_FILE_API']
               + '''\ncompose() {
  case "$*" in
    *native-source-embedding-identity.v1*) printf '{"provider":"ollama","model":"nomic-embed-text:latest"}\\n' ;;
    *''' + guarded_call + '''*) DEPLOY_CHANNEL_COMPOSE_GUARD_REFUSED=1; return 120 ;;
''' + show_failure + '''
    *) return 0 ;;
  esac
}\n'''
               + 'if native_source_embedding_preflight_gate; then exit 0; else rc=$?; fi\n'
               + 'printf "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection\\n" >&2\nexit "$rc"\n')
    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(['bash', '-c', command], cwd=root, env=env, deploy_diagnostics=True)
    assert emitted == [(
        'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        'MESSAGE=native deployment failure: stage=source_projection class=embedding_guard_refused\n'
    ).encode('ascii')]
    assert not Path(env['FAKE_DEPLOY_EVENT_LOG']).exists()


def test_native_embedding_identity_guard_refusal_is_distinct_from_probe_failures(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root, env, _prior, sha, _previous = _native_source_harness_with_prior_deployment(tmp_path)
    env['FAKE_BWS_COMPOSE_GUARD_RC'] = '42'
    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(['bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', 'dev', sha],
                       cwd=root, env=env, deploy_diagnostics=True)
    assert emitted == [(
        'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        'MESSAGE=native deployment failure: stage=source_projection class=embedding_guard_refused\n'
    ).encode('ascii')]
    assert 'source-rebuild' not in _deploy_events(env)


def test_native_embedding_probe_unmarked_status_120_uses_generic_failure(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root, env, _prior, sha, _previous = _native_source_harness_with_prior_deployment(tmp_path)
    script = SCRIPT.read_text()
    gate = script[script.index('native_source_failure() {'):script.index('native_source_projection_gate() {')]
    command = (gate + '\naction=deploy\nactivation_scope=full\ntarget_sha=' + sha
               + '\nBWS_DEPLOY_OPERATION_ID=' + env['BWS_DEPLOY_OPERATION_ID']
               + '\nHOST_SECRET_RUNTIME_ENV_FILE_API=' + env['HOST_SECRET_RUNTIME_ENV_FILE_API']
               + '''\ncompose() {
  case "$*" in
    *native-source-embedding-identity.v1*) printf '{"provider":"ollama","model":"nomic-embed-text:latest"}\\n' ;;
    *NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER*) return 120 ;;
    *) return 0 ;;
  esac
}\n'''
               + 'native_source_embedding_preflight_gate\nrc=$?\n'
               + 'printf "YGGDRASIL_DEPLOY_FAILURE_STAGE=source_projection\\n" >&2\nexit "$rc"\n')
    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(['bash', '-c', command], cwd=root, env=env, deploy_diagnostics=True)
    assert emitted == [(
        'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        'MESSAGE=native deployment failure: stage=source_projection class=embedding_probe_failed\n'
    ).encode('ascii')]


@pytest.mark.parametrize('changes,ready,reason', [
    ({'FAKE_API_CONTEXT_RC': '42'}, False, 'source_preflight_failed'),
    ({'FAKE_SOURCE_SETTINGS_RC': '42'}, False, 'source_settings_failed'),
    ({'FAKE_SOURCE_RC': '42'}, False, 'source_command_failed'),
    ({'FAKE_SOURCE_SUMMARY': 'hostile-child-canary /private/vault password=do-not-leak'}, False, 'source_summary_invalid'),
    ({'FAKE_SOURCE_SUMMARY': '{}'}, False, 'source_summary_invalid'),
    ({'FAKE_SOURCE_PREADINESS': '0'}, False, 'source_post_rebuild_failed'),
    ({'FAKE_SOURCE_INDEX_RC': '42'}, False, 'source_doctor_failed'),
    ({'FAKE_SOURCE_INDEX_SUMMARY': '{}'}, False, 'source_doctor_failed'),
    ({'FAKE_SOURCE_INDEX_PREFLIGHT_RC': '42'}, True, 'source_doctor_failed'),
    ({'FAULT_READINESS': '1'}, False, 'source_readiness_failed'),
    ({'FAULT_QUIESCENCE': '1'}, False, 'source_quiescence_failed'),
    ({'FAULT_WORKER': '1'}, False, 'source_worker_failed'),
])
def test_native_source_bootstrap_generic_failures_are_finitely_attributed(tmp_path, monkeypatch, changes, ready, reason):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    root, env, sha = _native_source_harness(tmp_path, channel='dev', ready=ready)
    env.update(changes)
    if 'FAULT_READINESS' in changes:
        site = tmp_path / 'api-python-fixture/sitecustomize.py'
        site.write_text(site.read_text() + '\ndef fail_readiness(*args):\n    raise RuntimeError("hostile-child-canary /private/vault password=do-not-leak")\nrebuildability.evaluate_product_store_readiness = fail_readiness\n')
    if 'FAULT_QUIESCENCE' in changes:
        docker = tmp_path / 'bin/docker'
        docker.write_text(docker.read_text().replace('case "$*" in\n', 'if [ "${1:-}" = ps ] && [[ "$*" == *source-bootstrap* ]]; then exit 42; fi\ncase "$*" in\n', 1))
    if 'FAULT_WORKER' in changes:
        bootstrap = root / 'app/ops/native_source_bootstrap.py'
        bootstrap.write_text(bootstrap.read_text().replace('rebuild_if_needed(selector)', 'raise RuntimeError("hostile-child-canary /private/vault password=do-not-leak")'))
    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(['bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', 'dev', sha],
                       cwd=root, env=env, deploy_diagnostics=True)
    assert emitted == [(
        'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
        f'MESSAGE=native deployment failure: stage=source_projection class={reason}\n'
    ).encode('ascii')]
    assert not list((root / 'ops/deployments').glob('*.json'))


@pytest.mark.parametrize('shape', ['valid', 'duplicate', 'injected', 'unknown', 'malformed', 'other_stage'])
def test_supervised_source_projection_reasons_are_finite_and_fail_closed(monkeypatch, shape):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError

    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    for reason in linux._SOURCE_PROJECTION_FAILURE_REASONS:
        stage = 'health' if shape == 'other_stage' else 'source_projection'
        marker = f'YGGDRASIL_DEPLOY_FAILURE_REASON={reason}\n'
        if shape == 'duplicate':
            marker += marker
        elif shape == 'injected':
            marker = 'hostile-child-canary ' + marker
        elif shape == 'unknown':
            marker = 'YGGDRASIL_DEPLOY_FAILURE_REASON=hostile-child-canary\n'
        elif shape == 'malformed':
            marker = marker.rstrip() + ' /private/vault password=do-not-leak\n'
        stderr = f'YGGDRASIL_DEPLOY_FAILURE_STAGE={stage}\n' + marker
        monkeypatch.setattr(linux.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 78, 'hostile stdout', stderr))
        with pytest.raises(PostgresDeployError):
            linux._command(['deployment'], deploy_diagnostics=True)
        expected = reason if shape == 'valid' else 'command_failed'
        assert emitted.pop() == (
            'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
            f'MESSAGE=native deployment failure: stage={stage} class={expected}\n'
        ).encode('ascii')


@pytest.mark.parametrize('status,oom,reason', [
    (82, False, 'source_preflight_failed'), (88, False, 'source_settings_failed'),
    (83, False, 'source_readiness_failed'), (84, False, 'source_command_failed'),
    (86, False, 'source_post_rebuild_failed'), (87, False, 'source_doctor_failed'),
    (79, False, 'vector_projection_failed'), (124, False, 'source_worker_timeout'),
    (143, False, 'source_worker_terminated'), (130, False, 'source_worker_terminated'),
    (137, True, 'source_worker_oom'), (137, False, 'source_worker_failed'),
    (96, False, 'source_worker_failed'), (97, False, 'source_worker_failed'),
    (98, False, 'source_worker_failed'),
    *[(status, False, 'source_worker_failed') for status in (114, 115, 116, 117, 118, 119, 255)],
    (42, False, 'source_worker_failed'),
])
def test_native_source_worker_terminal_classes_survive_supervision(tmp_path, status, oom, reason, monkeypatch):
    from app.ops import native_source_bootstrap as source, postgres_deploy_linux as linux
    assert source.source_terminal_reason(status, oom_killed=oom) == reason
    assert linux._deploy_failure_reason('YGGDRASIL_DEPLOY_FAILURE_REASON=' + reason, 'source_projection') == reason
    journal, operation, plan = _source_terminal_journal(tmp_path, monkeypatch)
    removed = []
    _source_terminal_docker(monkeypatch, journal, operation, plan.revision, status, oom, removed)
    assert linux.record_source_terminal('test', 'pkm-test-source-bootstrap-' + operation, status) == source.SOURCE_PROJECTION_FAILURE_CODES[reason]
    assert removed == [reason]


@pytest.mark.parametrize('changes,reason', [
    ({'FAKE_API_CONTEXT_RC': '42'}, 'source_preflight_failed'),
    ({'FAKE_SOURCE_SETTINGS_RC': '42'}, 'source_settings_failed'),
    ({'FAKE_SOURCE_RC': '42'}, 'source_command_failed'),
    ({'FAKE_SOURCE_PREADINESS': '0'}, 'source_post_rebuild_failed'),
    ({'FAKE_SOURCE_INDEX_RC': '42'}, 'source_doctor_failed'),
])
def test_native_source_worker_checkpoint_failure_is_content_free_and_attributable(tmp_path, monkeypatch, changes, reason):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError
    root, env, sha = _native_source_harness(tmp_path, channel='dev')
    env.update(changes)
    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(['bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', 'dev', sha],
                       cwd=root, env=env, deploy_diagnostics=True)
    assert len(emitted) == 1 and ('class=' + reason).encode() in emitted[0]
    assert b'hostile' not in b''.join(emitted) and b'/private' not in b''.join(emitted)


def _source_terminal_journal(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal
    operation = '03b3bb2f-6d85-499a-8b45-e397f56812e1'
    _worker, _journal, plan, _operation = _bws_worker(tmp_path, _BwsVmEffects())
    journal = DeployJournal(tmp_path / 'retained', 'test')
    journal.bind_request(operation, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(operation, stage)
    monkeypatch.setenv('BWS_DEPLOY_OPERATION_ID', operation)
    monkeypatch.setenv('BWS_DEPLOY_TARGET_REVISION', plan.revision)
    monkeypatch.setattr(linux, 'inherited_worker_guard', lambda channel: None)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda channel: SimpleNamespace(
        journal=journal, channel='test', root=tmp_path / 'checkout'))
    return journal, operation, plan


def _source_terminal_docker(monkeypatch, journal, operation, revision, status, oom, removed, fault=None):
    from app.ops import native_source_bootstrap as source
    def docker(argv, **kwargs):
        command = argv[1]
        output = ''
        if command == 'ps':
            hidden_foreign = fault in {'project', 'service', 'oneoff'} and any(
                value.startswith('label=com.docker.compose.') for value in argv)
            output = '' if removed or hidden_foreign else '0123456789ab'
        elif command == 'inspect':
            if 'ExitCode' in argv[3]:
                state = fault if fault in {'created', 'removing', 'unknown'} else 'exited'
                output = f'{state} {status} {str(oom).lower()}' if fault != 'malformed' else 'private output'
            else:
                op = operation if fault != 'foreign' else '00000000-0000-4000-8000-000000000002'
                project = 'pkm-foreign' if fault == 'project' else 'pkm-test'
                service = 'worker' if fault == 'service' else 'api'
                oneoff = 'False' if fault == 'oneoff' else 'True'
                output = f'/pkm-test-source-bootstrap-{operation} {project} {service} {oneoff} {op} {revision} false'
        elif command == 'rm':
            removed.append(journal.read().source_failure)
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(argv, 0, output, '')
    monkeypatch.setattr(source.subprocess, 'run', docker)
    return docker


@pytest.mark.parametrize('interrupted_before_observation', [False, True])
@pytest.mark.parametrize('already_failed', [False, True])
@pytest.mark.parametrize('worker_status,oom,reason', [(137, True, 'source_worker_oom'),
    (96, False, 'source_worker_failed'), (97, False, 'source_worker_failed'),
    (98, False, 'source_worker_failed'),
    *[(status, False, 'source_worker_failed') for status in (114, 115, 116, 117, 118, 119, 255)]])
def test_native_source_terminal_reason_survives_cleanup_and_same_id_reconciliation(tmp_path, monkeypatch, interrupted_before_observation, already_failed, worker_status, oom, reason):
    from dataclasses import asdict
    from app.ops import postgres_deploy_linux as linux
    from app.ops.native_source_bootstrap import SOURCE_PROJECTION_FAILURE_CODES
    from app.ops.postgres_deploy import PostgresDeployError
    journal, operation, plan = _source_terminal_journal(tmp_path, monkeypatch)
    removed = []
    docker = _source_terminal_docker(monkeypatch, journal, operation, plan.revision, worker_status, oom, removed)
    if not interrupted_before_observation:
        assert linux.record_source_terminal('test', 'pkm-test-source-bootstrap-' + operation, worker_status) == SOURCE_PROJECTION_FAILURE_CODES[reason]
        assert removed == [reason]
    if already_failed:
        journal.write(operation, 'failed')
    config = linux.LinuxConfig.load('test')
    lock = config.root / 'config/deploy/test.env.lock'
    lock.mkdir(parents=True, mode=0o700)
    (lock / 'bws-owner').touch(mode=0o600)
    monkeypatch.setattr(linux.LinuxEffects, 'quiescent', lambda self: True)
    monkeypatch.setattr(linux.LinuxEffects, 'activate', lambda *args: pytest.fail('must not replay'))
    monkeypatch.setattr(linux, '_command', lambda argv, **kwargs: docker(argv, **kwargs).stdout)
    supervisor = linux.DeploymentSupervisor(config)
    request = {'action': 'reconcile-failed', 'operation_id': operation, 'plan': asdict(plan), 'bootstrap': False}
    result = supervisor.request(request)
    assert result['receipt']['source_failure'] == reason
    assert removed == [reason] and not lock.exists()
    assert supervisor.request({**request, 'action': 'join'}) == result
    with pytest.raises(PostgresDeployError):
        journal.record_source_failure(operation, 'f' * 40, 'source_worker_failed')
    assert journal.read().source_failure == reason


@pytest.mark.parametrize('reason', [
    'legacy_candidate_refused', 'legacy_authority_refused', 'legacy_trust_refused',
    'legacy_origin_refused', 'legacy_payload_shape_refused', 'legacy_system_path_refused',
    'legacy_profile_refused', 'legacy_dependency_shape_refused',
    'legacy_retained_history_refused', 'legacy_relation_retention_refused',
])
def test_native_legacy_admission_subreason_survives_terminal_reconciliation(tmp_path, monkeypatch, reason):
    from dataclasses import asdict
    from click.testing import CliRunner
    from app.cli import cli, index_rebuild
    from app.ops import native_source_bootstrap as native, postgres_deploy_linux as linux
    from tests.cli.test_index_rebuild_cli import _legacy_source_fixture

    # Exercise the actual private CLI serialization, then send that exact
    # summary through the native subprocess/bootstrap and shell wrapper path.
    fixture = tmp_path / 'source'
    fixture.mkdir()
    recovery, state, root, source, raw, original, binding, index, factory = _legacy_source_fixture(monkeypatch, fixture)
    monkeypatch.setattr(index_rebuild.domain_objects, 'resolve_object_store_port', lambda: binding)
    monkeypatch.setattr(index_rebuild, 'get_vector_index', lambda: index)
    monkeypatch.setattr(index_rebuild, 'get_product_embedding_client', factory)

    def refuse(*args, **kwargs):
        raise recovery.LegacySourceRefusal(reason)

    monkeypatch.setattr(recovery, 'reconcile_legacy_sources', refuse)
    cli_result = CliRunner().invoke(cli, ['index', 'reconcile-legacy', '--json'])
    assert cli_result.exit_code == 79 and json.loads(cli_result.output) == {'reason': reason}
    harness = tmp_path / 'deploy'
    harness.mkdir()
    root, env, sha = _native_source_harness(harness, channel='dev', ready=True)
    missing = json.dumps(dict(backend='PgVectorIndex', issues=['missing vector'], rebuild_required=True,
        unembedded_object_count=1, non_vector_issue_count=0, pg_state={}))
    env.update(FAKE_SOURCE_INDEX_PREFLIGHT_SUMMARY=missing, FAKE_SOURCE_REPLAY_INDEX_SUMMARY=missing,
               FAKE_LEGACY_RECONCILIATION_SUMMARY=cli_result.output, FAKE_LEGACY_RECONCILIATION_RC='79')
    diagnostics = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', diagnostics.append)
    with pytest.raises(linux.PostgresDeployError):
        linux._command(['bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', 'dev', sha],
                       cwd=root, env=env, deploy_diagnostics=True)
    assert len(diagnostics) == 1 and ('class=' + reason).encode() in diagnostics[0]
    assert b'hostile' not in b''.join(diagnostics) and b'/private' not in b''.join(diagnostics)
    events = _deploy_events(env)
    assert 'api-cli index repair-missing --json' not in events
    assert not any('up -d --force-recreate api worker watcher' in event for event in events)

    journal, operation, plan = _source_terminal_journal(tmp_path, monkeypatch)
    removed = []
    status = native.SOURCE_PROJECTION_FAILURE_CODES[reason]
    docker = _source_terminal_docker(monkeypatch, journal, operation, plan.revision, status, False, removed)
    assert linux.record_source_terminal('test', 'pkm-test-source-bootstrap-' + operation, status) == status
    assert removed == [reason]  # Durable attribution precedes container removal.
    journal.write(operation, 'failed')
    config = linux.LinuxConfig.load('test')
    lock = config.root / 'config/deploy/test.env.lock'
    lock.mkdir(parents=True, mode=0o700)
    (lock / 'bws-owner').touch(mode=0o600)
    monkeypatch.setattr(linux.LinuxEffects, 'quiescent', lambda self: True)
    monkeypatch.setattr(linux.LinuxEffects, 'activate', lambda *args: pytest.fail('must not replay'))
    monkeypatch.setattr(linux, '_command', lambda argv, **kwargs: docker(argv, **kwargs).stdout)
    supervisor = linux.DeploymentSupervisor(config)
    request = {'action': 'reconcile-failed', 'operation_id': operation, 'plan': asdict(plan), 'bootstrap': False}
    result = supervisor.request(request)
    assert result['receipt']['source_failure'] == reason
    assert supervisor.request({**request, 'action': 'join'}) == result
    assert removed == [reason] and not lock.exists()


@pytest.mark.parametrize('reason', [
    'legacy_identity_persistence_refused', 'legacy_identity_mismatch_refused',
    'legacy_identity_ambiguous_refused', 'legacy_identity_producer_refused',
    'legacy_identity_canonical_refused',
])
def test_native_legacy_identity_subreason_survives_terminal_reconciliation(tmp_path, monkeypatch, reason):
    test_native_legacy_admission_subreason_survives_terminal_reconciliation(tmp_path, monkeypatch, reason)


def test_native_source_same_id_reply_keeps_locked_snapshot_after_admission_retirement(tmp_path, monkeypatch):
    from dataclasses import asdict
    from app.ops import postgres_deploy_linux as linux
    journal, operation, plan = _source_terminal_journal(tmp_path, monkeypatch)
    journal.record_source_failure(operation, plan.revision, 'source_worker_failed')
    journal.write(operation, 'failed')
    config = linux.LinuxConfig.load('test')
    lock = config.root / 'config/deploy/test.env.lock'
    lock.mkdir(parents=True, mode=0o700)
    (lock / 'bws-owner').touch(mode=0o600)
    monkeypatch.setattr(linux.LinuxEffects, 'quiescent', lambda self: True)
    monkeypatch.setattr(linux, '_command', lambda *args, **kwargs: '')
    retire = linux.LinuxEffects.retire_reconciled_channel_lock
    replacement = '00000000-0000-4000-8000-000000000002'
    def replace_after_retirement(handle):
        retire(handle)
        journal.bind_request(replacement, plan, False, create=True)
        journal.write(replacement, 'prepared')
    monkeypatch.setattr(linux.LinuxEffects, 'retire_reconciled_channel_lock', staticmethod(replace_after_retirement))
    result = linux.DeploymentSupervisor(config).request({
        'action': 'reconcile-failed', 'operation_id': operation, 'plan': asdict(plan), 'bootstrap': False,
    })
    assert result['receipt']['operation_id'] == operation
    assert result['receipt']['source_failure'] == 'source_worker_failed'
    assert journal.read().operation_id == replacement


@pytest.mark.parametrize('fault', ['foreign', 'project', 'service', 'oneoff', 'malformed', 'created', 'removing', 'unknown', 'journal_unavailable'])
def test_native_source_terminal_evidence_failure_preserves_container(tmp_path, monkeypatch, fault):
    from app.ops import postgres_deploy_linux as linux
    journal, operation, plan = _source_terminal_journal(tmp_path, monkeypatch)
    removed = []
    _source_terminal_docker(monkeypatch, journal, operation, plan.revision, 137, True, removed, fault)
    if fault == 'journal_unavailable':
        def fail(*args):
            raise OSError('private evidence path')
        monkeypatch.setattr(journal, '_persist', fail)
    with pytest.raises(Exception):
        linux.record_source_terminal('test', 'pkm-test-source-bootstrap-' + operation, 137)
    assert removed == []
    assert journal.read().source_failure is None


def test_native_source_terminal_retry_reestablishes_durability_before_removal(tmp_path, monkeypatch):
    import stat
    from app.ops import postgres_deploy_linux as linux
    journal, operation, plan = _source_terminal_journal(tmp_path, monkeypatch)
    removed = []
    _source_terminal_docker(monkeypatch, journal, operation, plan.revision, 137, True, removed)
    original_fsync = os.fsync
    directory_identity = journal.directory.stat()
    failed = False
    directory_syncs = []
    def fsync(descriptor):
        nonlocal failed
        renamed = json.loads((journal.directory / 'test.json').read_text()).get('source_failure') == 'source_worker_oom'
        info = os.fstat(descriptor)
        if (stat.S_ISDIR(info.st_mode) and renamed
            and (info.st_dev, info.st_ino) == (directory_identity.st_dev, directory_identity.st_ino)):
            if not failed:
                failed = True
                raise OSError('private sync diagnostic')
            directory_syncs.append('synced')
        return original_fsync(descriptor)
    monkeypatch.setattr(os, 'fsync', fsync)
    with pytest.raises(Exception):
        linux.record_source_terminal('test', 'pkm-test-source-bootstrap-' + operation, 137)
    # Read bytes directly: journal.read itself re-fsyncs the directory, so using
    # it here would repair the injected failure before the production retry.
    assert json.loads((journal.directory / 'test.json').read_text())['source_failure'] == 'source_worker_oom'
    assert removed == []
    assert linux.record_source_terminal('test', 'pkm-test-source-bootstrap-' + operation, 137) == 98
    assert directory_syncs and removed == ['source_worker_oom']


@pytest.mark.parametrize('compose_status,worker_status,reason', [
    (1, 82, 'source_preflight_failed'), (1, 79, 'vector_projection_failed'),
    (1, 0, 'source_worker_failed'), (124, 0, 'source_worker_timeout'),
    (143, 0, 'source_worker_terminated'), (1, 98, 'source_worker_failed'),
    *[(1, status, 'source_worker_failed') for status in (114, 115, 116, 117, 118, 119, 255)],
])
def test_native_source_docker_worker_state_survives_compose_transport_failure(tmp_path, monkeypatch, compose_status, worker_status, reason):
    from app.ops import native_source_bootstrap as source, postgres_deploy_linux as linux
    journal, operation, plan = _source_terminal_journal(tmp_path, monkeypatch)
    removed = []
    _source_terminal_docker(monkeypatch, journal, operation, plan.revision, worker_status, False, removed)
    assert linux.record_source_terminal('test', 'pkm-test-source-bootstrap-' + operation, compose_status) == source.SOURCE_PROJECTION_FAILURE_CODES[reason]
    assert removed == [reason]


@pytest.mark.parametrize('helper_status', [1, 42, 78, 114, 115, 116, 117, 118, 119, 124, 130, 137, 143, 255])
def test_native_source_unexpected_cleanup_helper_exit_never_admits_writer_restart(tmp_path, helper_status):
    root, env, sha = _native_source_harness(tmp_path, channel='dev')
    env['FAKE_SOURCE_RC'] = '42'
    adapter = root / 'app/ops/postgres_deploy_linux.py'
    adapter.write_text(adapter.read_text() + f'\ndef record_source_terminal(*args):\n    raise SystemExit({helper_status})\n')
    result = _run_deploy(root, env, sha)
    assert result.returncode == 78
    assert 'YGGDRASIL_DEPLOY_FAILURE_REASON=source_quiescence_failed' in result.stderr
    assert 'native source producer quiescence is unproven' in result.stderr
    assert not any('up -d --force-recreate api' in event for event in _deploy_events(env))


def test_native_source_foreign_exact_name_cannot_hide_behind_ownership_filters(tmp_path):
    root, env, sha = _native_source_harness(tmp_path, channel='dev')
    env['FAKE_SOURCE_RC'] = '42'
    docker = tmp_path / 'bin/docker'
    docker.write_text(docker.read_text().replace('case "$*" in\n', '''if [ "${1:-}" = ps ] && [[ "$*" == *source-bootstrap* ]]; then
  if [[ "$*" != *label=com.docker.compose.* ]]; then printf '0123456789ab\\n'; fi
  exit 0
fi
if [ "${1:-}" = inspect ] && [[ "$*" == *State.Running* ]]; then
  printf '/pkm-dev-source-bootstrap-%s pkm-foreign api True %s %s false\\n' \\
    "${BWS_DEPLOY_OPERATION_ID}" "${BWS_DEPLOY_OPERATION_ID}" "${BWS_DEPLOY_TARGET_REVISION}"
  exit 0
fi
case "$*" in
''', 1))
    result = _run_deploy(root, env, sha)
    assert result.returncode == 78
    assert 'YGGDRASIL_DEPLOY_FAILURE_REASON=source_quiescence_failed' in result.stderr
    assert 'native source producer quiescence is unproven' in result.stderr
    assert not any('up -d --force-recreate api' in event for event in _deploy_events(env))


def test_native_source_failure_after_embedding_progress_keeps_only_fixed_reason(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import PostgresDeployError
    root, env, sha = _native_source_harness(tmp_path, channel='dev')
    cli = root / 'app/cli.py'
    cli.write_text(cli.read_text().replace(
        'if args[:1] == ["vault-alpha-ingest"]:',
        '''if args[:1] == ["vault-alpha-ingest"]:
    def embedding_call():
        with open(os.environ['FAKE_DEPLOY_EVENT_LOG'], 'a') as progress:
            progress.write('embedding-success\\n')
        return [0.1, 0.2]
    for _ in range(400):
        assert len(embedding_call()) == 2
        print("private successful embedding payload /private/vault")
    raise SystemExit(42)
'''))
    emitted = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', emitted.append)
    with pytest.raises(PostgresDeployError):
        linux._command(['bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', 'dev', sha],
                       cwd=root, env=env, deploy_diagnostics=True)
    assert len(emitted) == 1 and b'class=source_command_failed' in emitted[0]
    assert _deploy_events(env).count('embedding-success') == 400
    assert b'private' not in b''.join(emitted) and b'payload' not in b''.join(emitted)


_EMBEDDING_PROBE_REASONS = [
    'embedding_probe_client_failed', 'embedding_probe_identity_mismatch',
    'embedding_probe_generation_failed', 'embedding_probe_vector_invalid',
    'embedding_probe_cleanup_failed',
]
_EMBEDDING_PROBE_STATUSES = list(enumerate(_EMBEDDING_PROBE_REASONS, 114)) + [
    (121, 'embedding_probe_executor_busy')]


@pytest.mark.parametrize('fault,status', [
    ('client', 114), ('identity', 114), ('mismatch', 115), ('generation', 116),
    ('dimension', 117), ('shape', 117), ('nan', 0), ('cleanup', 118),
    ('generation_cleanup', 116), ('unexpected', 78), ('success', 0),
    # A candidate image without the busy type keeps the generic generation status.
    ('busy', 121), ('busy_cleanup', 121), ('busy_old_image', 116),
])
def test_native_embedding_probe_subreasons_cover_production_call_site(tmp_path, fault, status):
    assignment = next(line.strip() for line in SCRIPT.read_text().splitlines()
                      if line.strip().startswith("probe_command=$'"))
    extracted = subprocess.run(['bash', '-c', assignment + '\nprintf "%s" "$probe_command"'],
                               capture_output=True, text=True, check=True)
    # Replace only the provider factory at the actual production import seam.
    setup = '''import sys, types
from types import SimpleNamespace
fault = sys.argv[1]
events = []
def fail():
    raise RuntimeError('private-provider-canary /private/vault credential=secret')
class Client:
    @property
    def identity(self):
        events.append('identity')
        if fault == 'identity': fail()
        return SimpleNamespace(provider='mock' if fault == 'mismatch' else 'ollama', model='selected', dim=2)
    def embed_text(self, text):
        events.append('embed')
        assert text == 'Yggdrasil deployment preflight'
        if fault in {'generation', 'generation_cleanup'}: fail()
        if fault.startswith('busy'): raise Busy('embedding_executor_busy')
        if fault == 'unexpected': raise SystemExit(78)
        return {'dimension': [0.0], 'shape': 'xx', 'nan': [float('nan'), 0.0]}.get(fault, [0.0, 1.0])
    def close(self):
        events.append('close')
        if fault in {'cleanup', 'generation_cleanup', 'busy_cleanup'}: fail()
def factory():
    events.append('client')
    if fault == 'client': fail()
    return Client()
module = types.ModuleType('app.components.llm.fabric')
module.get_product_embedding_client = factory
module.RemoteEmbeddingIdentityError = type('RemoteEmbeddingIdentityError', (Exception,), {})
module.RemoteEmbeddingVectorError = type('RemoteEmbeddingVectorError', (Exception,), {})
Busy = type('RemoteEmbeddingExecutorBusyError', (Exception,), {})
if fault != 'busy_old_image':
    module.RemoteEmbeddingExecutorBusyError = Busy
sys.modules['app.components.llm.fabric'] = module
'''
    # Even refusal must close an acquired client; no exception payload escapes.
    wrapper = (setup + '\ntry:\n    exec(' + repr(extracted.stdout)
               + ')\nfinally:\n    assert events.count("embed") <= 1\n'
               + '    assert events.count("close") == (0 if fault == "client" else 1)\n')
    result = subprocess.run([sys.executable, '-c', wrapper, fault], cwd=tmp_path,
                            env={**os.environ, 'NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER': 'ollama',
                                 'NATIVE_SOURCE_EXPECTED_EMBEDDING_MODEL': 'selected'},
                            capture_output=True, text=True)
    assert result.returncode == status
    assert result.stdout == result.stderr == ''


@pytest.mark.parametrize('status,reason', _EMBEDDING_PROBE_STATUSES + [(42, 'embedding_probe_failed')])
def test_native_embedding_probe_subreason_survives_terminal_reconciliation(tmp_path, monkeypatch, status, reason):
    from dataclasses import asdict
    from app.ops import postgres_deploy_linux as linux
    root, env, _prior, sha, _previous = _native_source_harness_with_prior_deployment(tmp_path)
    journal, operation, plan = _source_terminal_journal(tmp_path / 'journal-test', monkeypatch)
    env['FAKE_EMBEDDING_PROBE_RC'] = str(status)
    diagnostics = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', diagnostics.append)
    with pytest.raises(linux.PostgresDeployError):
        linux._command(['bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', 'dev', sha],
                       cwd=root, env=env, deploy_diagnostics=True,
                       retain_source_failure=lambda value: journal.record_source_failure(
                           operation, plan.revision, value))
    assert len(diagnostics) == 1 and ('class=' + reason + '\n').encode() in diagnostics[0]
    assert 'source-rebuild' not in _deploy_events(env)
    assert not any('stop' in event for event in _deploy_events(env))
    # Journal exactly the supervised, allowlisted result; reconciliation cannot replay it.
    assert journal.read().source_failure == reason
    journal.write(operation, 'failed')
    config = linux.LinuxConfig.load('test')
    monkeypatch.setattr(linux.LinuxEffects, 'activate', lambda *args: pytest.fail('must not replay'))
    supervisor = linux.DeploymentSupervisor(config)
    result = supervisor.request({'action': 'join', 'operation_id': operation,
                                 'plan': asdict(plan), 'bootstrap': False})
    assert result['receipt']['source_failure'] == reason


@pytest.mark.parametrize('boundary,fault,status', [
    (boundary, fault, status) for boundary in ['fabric', 'transport']
    for fault, status in [('model', 115), ('dimension', 117), ('shape', 117),
        ('nonfinite', 117), ('cleanup', 118), ('model_cleanup', 115),
        ('generation_cleanup', 116), ('success', 0)]
] + [('transport', fault, status) for fault, status in [
    ('bool_vector', 117), ('string_vector', 117), ('container', 117), ('nested', 117),
    ('empty', 117), ('bool_dimension', 117), ('string_dimension', 117), ('zero_dimension', 117),
    ('provider', 115), ('transport', 116), ('metadata', 116), ('extra', 116),
    ('missing_vector', 116), ('malformed_json', 116), ('nan_json', 116), ('inf_json', 116),
    ('integer_overflow', 116),
]])
def test_embedding_probe_classifies_real_product_client_validation(monkeypatch, capsys, boundary, fault, status):
    if boundary == 'fabric' and fault == 'nonfinite':
        status = 0  # Preserve the existing custom-client policy; real wire transport refuses.
    import httpx
    from types import SimpleNamespace
    from app.components.llm import fabric
    from app.components.embeddings import EmbeddingIdentity
    from app.model_access import executor_network_policy as network
    from app.model_access.codex_remote_transport import (
        CodexRemoteTransport, RemoteEmbeddingError, RemoteEmbeddingIdentityError, RemoteEmbeddingVectorError,
    )
    from app.model_access.remote_contract import ProductEmbeddingResponse

    body = {'route': {'provider': 'ollama', 'model': 'other' if fault in {'model', 'model_cleanup'} else 'selected:latest',
                     'transport_id': 'ollama_http', 'catalog_snapshot_ref': 'catalog.synthetic',
                     'catalog_snapshot_hash': 'sha256:' + 'a' * 64},
            'dimensions': 3 if fault == 'dimension' else 2,
            'vector': [0.25] * (3 if fault == 'dimension' else 2)}
    if fault == 'shape':
        body['vector'] = [0.25]
    if fault == 'nonfinite':
        body['vector'] = [float('inf'), 0.25]
    vector_faults = {'bool_vector': [True, 0.25], 'string_vector': ['0.25', 0.25],
        'container': {'a': 0.25, 'b': 0.25}, 'nested': [[0.25], [0.25]], 'empty': [],
        'integer_overflow': [10 ** 400, 0.25]}
    if fault in vector_faults:
        body['vector'] = vector_faults[fault]
    if fault.endswith('_dimension'):
        body['dimensions'] = {'bool_dimension': True, 'string_dimension': '2', 'zero_dimension': 0}[fault]
    if fault == 'provider':
        body['route'].update(provider='gemini', transport_id='gemini_api')
    if fault == 'transport':
        body['route']['transport_id'] = 'unknown'
    if fault == 'metadata':
        body['route']['catalog_snapshot_hash'] = 'private-provider-canary'
    if fault == 'extra':
        body['private-provider-canary'] = 'private payload'
    if fault == 'missing_vector':
        del body['vector']
    requests, closed = [], []
    def send(request):
        requests.append(request)
        if fault == 'generation_cleanup':
            return httpx.Response(503, content='private-provider-canary /private/vault credential=secret')
        if fault == 'malformed_json':
            return httpx.Response(200, content='private-provider-canary not-json')
        if fault in {'nan_json', 'inf_json'}:
            return httpx.Response(200, content=json.dumps({**body, 'vector': [
                float('nan') if fault == 'nan_json' else float('inf'), 0.25]}))
        # JSON overflow is schema-valid in the existing response contract,
        # unlike the explicit NaN/Infinity constants rejected by the decoder.
        return httpx.Response(200, content=json.dumps(body).replace('Infinity', '1e400'))
    if boundary == 'transport':
        remote = CodexRemoteTransport(endpoint='https://synthetic-executor.test.ts.net',
                                     transport=httpx.MockTransport(send))
        embed = remote.embed_product
    else:
        def embed(request):
            requests.append(request)
            if fault == 'generation_cleanup':
                raise RemoteEmbeddingError('embedding_http_503', indeterminate=True)
            if fault == 'shape':
                return SimpleNamespace(route=SimpleNamespace(**body['route']),
                                       dimensions=body['dimensions'], vector=body['vector'])
            return ProductEmbeddingResponse.model_validate({**body, 'vector': tuple(body['vector'])})
    def close():
        closed.append(True)
        if boundary == 'transport':
            remote.close()
        if fault == 'cleanup' or fault.endswith('_cleanup'):
            raise RuntimeError('private-cleanup-canary /private/vault credential=secret')
    transport = SimpleNamespace(embed_product=embed, close=close)
    monkeypatch.setattr(network, 'resolve_executor_paths', lambda *a, **kw: [
        SimpleNamespace(path_profile='synthetic')])
    router = network.ExecutorNetworkPathRouter(transport_factory=lambda path: transport)
    identity = EmbeddingIdentity(provider='ollama', model='selected:latest', dim=2)
    errors = []
    original_embed = fabric._RemoteProductEmbeddingClient.embed_text
    def observed_embed(self, text):
        try:
            return original_embed(self, text)
        except RemoteEmbeddingError as exc:
            errors.append(exc)
            raise
    monkeypatch.setattr(fabric._RemoteProductEmbeddingClient, 'embed_text', observed_embed)
    def routed(intent):
        assert intent.task_kind == 'embed' and intent.strict_identity_required
        return SimpleNamespace(embedding_identity=identity)
    monkeypatch.setattr(fabric, 'LLMRouter', lambda: SimpleNamespace(route=routed))
    monkeypatch.setattr(fabric, 'load_models', lambda: {'selected': SimpleNamespace(
        kind='embedding', provider='ollama', model='selected:latest', dims=2,
        allowed_transports=('ollama_http',))})
    monkeypatch.setattr(fabric, '_adapter_factory', lambda: SimpleNamespace(
        adapter_id_for=lambda *a, **kw: 'ollama_http', describe=lambda *a, **kw: None))
    monkeypatch.setattr(fabric, '_new_executor_path_router', lambda **kw: router)
    monkeypatch.setenv('NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER', 'ollama')
    monkeypatch.setenv('NATIVE_SOURCE_EXPECTED_EMBEDDING_MODEL', 'selected:latest')
    assignment = next(line.strip() for line in SCRIPT.read_text().splitlines()
                      if line.strip().startswith("probe_command=$'"))
    probe = subprocess.run(['bash', '-c', assignment + '\nprintf "%s" "$probe_command"'],
                           capture_output=True, text=True, check=True).stdout
    with pytest.raises(SystemExit) as exit_info:
        exec(probe, {})
    assert exit_info.value.code == status
    assert len(requests) == len(closed) == 1
    assert fabric.RemoteEmbeddingError is RemoteEmbeddingError
    if status in {115, 116, 117}:
        assert len(errors) == 1 and errors[0].indeterminate
        if status != 116:
            assert isinstance(errors[0], RemoteEmbeddingIdentityError if status == 115 else RemoteEmbeddingVectorError)
        assert str(errors[0]) == errors[0].code == (
            'embedding_http_503' if fault == 'generation_cleanup'
            else 'embedding_response_invalid' if boundary == 'transport' and (
                fault == 'shape' or fault in vector_faults or fault.endswith('_dimension') or status == 116)
            else 'embedding_route_or_dimension_mismatch')
    captured = capsys.readouterr()
    assert captured.out == captured.err == ''


def test_native_embedding_probe_success_keeps_exact_identity_and_precedes_projection(tmp_path):
    root, env, _prior, sha, _previous = _native_source_harness_with_prior_deployment(tmp_path, ready=False)
    result = _run_deploy(root, env, sha)
    assert result.returncode == 0, result.stderr
    events = _deploy_events(env)
    probe = next(i for i, event in enumerate(events) if event.startswith('embedding-probe '))
    assert probe < events.index('source-rebuild')


@pytest.mark.parametrize('normalize', [False, True])
@pytest.mark.parametrize('values,normal_status,raw_status', [
    ([True, False], 0, 0), (['1.0', '2.0'], 0, 0), (['bad', '2.0'], 116, 0),
    ([float('nan'), 1.0], 0, 0), ([float('inf'), 1.0], 0, 0),
    ([0.25], 116, 116), ([], 116, 116), ('12', 0, 0), ([[], []], 116, 0),
])
def test_embedding_probe_preserves_profiled_factory_vector_policy(monkeypatch, normalize, values, normal_status, raw_status):
    from types import SimpleNamespace
    from app.components.llm import fabric
    from app.components.embeddings.legacy import EmbeddingIdentity, _ProfiledEmbeddingClient
    from app.llm import embeddings
    identity = EmbeddingIdentity(provider='mock', model='mock-embedding', dim=2, normalize=normalize)
    def route(intent):
        assert intent.task_kind == 'embed' and intent.strict_identity_required
        return SimpleNamespace(embedding_identity=identity)
    monkeypatch.setattr(fabric, 'LLMRouter', lambda: SimpleNamespace(route=route))
    monkeypatch.setattr(fabric, '_new_executor_path_router', lambda **kw: pytest.fail('legacy mock must stay local'))
    calls = []
    def adapter(text, **kwargs):
        calls.append(text)
        return values
    monkeypatch.setitem(embeddings.PROVIDER_REGISTRY, 'mock', adapter)
    monkeypatch.setenv('EMBED_MAX_INPUT_CHARS', '6000')
    monkeypatch.setenv('NATIVE_SOURCE_EXPECTED_EMBEDDING_PROVIDER', 'mock')
    monkeypatch.setenv('NATIVE_SOURCE_EXPECTED_EMBEDDING_MODEL', 'mock-embedding')
    assert isinstance(fabric.get_product_embedding_client(), _ProfiledEmbeddingClient)
    assignment = next(line.strip() for line in SCRIPT.read_text().splitlines()
                      if line.strip().startswith("probe_command=$'"))
    probe = subprocess.run(['bash', '-c', assignment + '\nprintf "%s" "$probe_command"'],
                           capture_output=True, text=True, check=True).stdout
    embeddings._embed_single.cache_clear()
    try:
        with pytest.raises(SystemExit) as exit_info:
            exec(probe, {})
        assert exit_info.value.code == (normal_status if normalize else raw_status)
        assert calls == ['Yggdrasil deployment preflight']
    finally:
        embeddings._embed_single.cache_clear()


@pytest.mark.parametrize('fault', ['identity', 'registry_dimension'])
def test_embedding_probe_actual_factory_acquisition_refuses_before_transport(monkeypatch, fault):
    from types import SimpleNamespace
    from app.components.llm import fabric
    from app.components.embeddings import EmbeddingIdentity
    identity = EmbeddingIdentity(provider='ollama', model='selected:latest', dim=2)
    def route(intent):
        assert intent.task_kind == 'embed' and intent.strict_identity_required
        return SimpleNamespace(embedding_identity=None if fault == 'identity' else identity)
    monkeypatch.setattr(fabric, 'LLMRouter', lambda: SimpleNamespace(route=route))
    monkeypatch.setattr(fabric, 'load_models', lambda: {'selected': SimpleNamespace(
        kind='embedding', provider='ollama', model='selected:latest', dims=3)})
    monkeypatch.setattr(fabric, '_new_executor_path_router', lambda **kw: pytest.fail('no transport before acquisition'))
    assignment = next(line.strip() for line in SCRIPT.read_text().splitlines()
                      if line.strip().startswith("probe_command=$'"))
    probe = subprocess.run(['bash', '-c', assignment + '\nprintf "%s" "$probe_command"'],
                           capture_output=True, text=True, check=True).stdout
    with pytest.raises(SystemExit) as exit_info:
        exec(probe, {})
    assert exit_info.value.code == 114


@pytest.mark.parametrize('checked', [False, True])
def test_embedding_router_cleanup_keeps_normal_policy_and_checks_all_unique_transports(monkeypatch, checked):
    from types import SimpleNamespace
    from app.model_access import executor_network_policy as network
    from app.components.llm.fabric import _RemoteProductEmbeddingClient
    from app.components.embeddings import EmbeddingIdentity
    closed = []
    def fail():
        closed.append('failed')
        raise RuntimeError('private-cleanup-canary /private/vault credential=secret')
    bad = SimpleNamespace(close=fail)
    healthy = SimpleNamespace(close=lambda: closed.append('healthy'))
    monkeypatch.setattr(network, 'resolve_executor_paths', lambda *a, **kw: [
        SimpleNamespace(path_profile=path) for path in ('bad', 'duplicate', 'healthy')])
    router = network.ExecutorNetworkPathRouter(transport_factory=lambda path:
        healthy if path.path_profile == 'healthy' else bad)
    client = _RemoteProductEmbeddingClient(
        identity=EmbeddingIdentity(provider='ollama', model='selected:latest', dim=2),
        request_model='selected:latest', expected_transport='ollama_http', remote_transport=router)
    if checked:
        with pytest.raises(RuntimeError, match='^executor_path_cleanup_failed$'):
            client.close_for_preflight()
    else:
        assert client.close() is None
    client.close()  # Finalizer already consumed: no replay of cleanup.
    assert closed == ['failed', 'healthy']


@pytest.mark.parametrize('marker', ['unknown', 'duplicate', 'other-stage', 'private'])
def test_embedding_probe_untrusted_markers_cannot_reach_operation_journal(monkeypatch, marker):
    from app.ops import native_source_bootstrap as source, postgres_deploy_linux as linux
    codes = source.SOURCE_PROJECTION_FAILURE_CODES
    assert len(codes) == len(set(codes.values()))
    probes = source.EMBEDDING_PROBE_FAILURE_CODES
    assert len(probes) == len(set(probes.values()))
    assert not (codes.keys() & probes.keys()) and not (set(codes.values()) & set(probes.values()))
    assert source.SOURCE_PROJECTION_FAILURE_REASONS == codes.keys() | probes.keys()
    reason = 'embedding_probe_client_failed'
    stage = 'health' if marker == 'other-stage' else 'source_projection'
    line = 'YGGDRASIL_DEPLOY_FAILURE_REASON=' + (reason if marker != 'unknown' else 'unknown') + '\n'
    if marker == 'duplicate':
        line += line
    if marker == 'private':
        line = 'private-provider-canary /private/vault credential=secret ' + line
    monkeypatch.setattr(linux.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(
        a, 78, 'private-provider-canary', 'YGGDRASIL_DEPLOY_FAILURE_STAGE=' + stage + '\n' + line))
    diagnostics, retained = [], []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', diagnostics.append)
    with pytest.raises(linux.PostgresDeployError):
        linux._command(['deployment'], deploy_diagnostics=True, retain_source_failure=retained.append)
    assert not retained
    assert len(diagnostics) == 1 and b'class=command_failed' in diagnostics[0]
    assert b'private-provider-canary' not in diagnostics[0]


def test_embedding_probe_status_namespace_never_decodes_as_worker_reason():
    from app.ops import native_source_bootstrap as source
    codes = source.SOURCE_PROJECTION_FAILURE_CODES
    # Every worker byte status uses only worker checkpoint/observer semantics.
    for status in range(256):
        expected = (None if status == 0 else 'source_worker_timeout' if status == 124
                    else 'source_worker_terminated' if status in {130, 143}
                    else next((reason for reason, code in codes.items()
                               if code == status and code not in {96, 97, 98}),
                              'source_worker_failed'))
        assert source.source_terminal_reason(status) == expected
        assert source.source_terminal_reason(status, oom_killed=True) == 'source_worker_oom'
    assert not (set(source.EMBEDDING_PROBE_FAILURE_CODES)
                & {source.source_terminal_reason(status) for status in range(256)})


def test_full_startup_uses_same_strict_source_summary_parser() -> None:
    script = (REPO_ROOT / "scripts/start_full_system.sh").read_text()
    assert "from app.ops.native_source_bootstrap import source_rebuild_counts" in script
    assert "values = [*source_rebuild_counts(payload), 0]" in script


def _cache_activation_harness(tmp_path, monkeypatch, *, channel='test', automatic=True):
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError

    directory = tmp_path / 'config/deploy'
    directory.mkdir(parents=True)
    directory.joinpath(channel + '.env').write_text(
        f'APP_IMAGE_REPOSITORY={IMAGE_REPOSITORY}\nAPP_IMAGE_TAG={"a" * 40}\n'
        f'APP_IMAGE_DIGEST_SUFFIX=@sha256:{"4" * 64}\n')
    directory.joinpath(channel + '.previous.env').write_text(
        f'APP_IMAGE_TAG={"a" * 40}\nAPP_IMAGE_DIGEST_SUFFIX=@sha256:{"5" * 64}\n')
    directory.joinpath('prod.previous.env').write_text(f'APP_IMAGE_TAG={6:040x}\n')
    directory.joinpath(channel + '.migration-pending.env').write_text(
        f'FROM_SHA={7:040x}\nTARGET_SHA={8:040x}\nACK_FORWARD_ONLY=0\n')
    journal = DeployJournal(tmp_path / 'journal', channel)
    operation_id = str(uuid4())
    for stage in ('prepared', 'preflighted', 'materialized', 'activating'):
        journal.write(operation_id, stage)
    source = tmp_path / 'secret-handles'
    source.mkdir()
    effects = linux.LinuxEffects(SimpleNamespace(
        channel=channel, root=tmp_path, journal=journal, source_directory=source))
    effects.source = SimpleNamespace(verify=lambda: None)
    effects.environment = lambda: {'HOST_SECRET_PROVIDER': 'bws'}
    effects.active_consumers = tuple(DATABASE_CONSUMERS)
    effects.consumer_values = {name: {} for name in
                              ('heimdal-api-ingress', 'heimdal-capture-watch', 'heimdal-raw-migrate')}
    plan = DeployPlan(channel, 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      tuple(DATABASE_CONSUMERS), image_digest='sha256:' + '9' * 64,
                      automatic=automatic)
    images = {f'sha256:{number:064x}': {
        'id': f'sha256:{number:064x}', 'tags': [f'{IMAGE_REPOSITORY}:{number:040x}'],
        'digests': [f'{IMAGE_REPOSITORY}@sha256:{number:064x}'],
        'created': '2020-01-01T00:00:00Z',
    } for number in range(1, 16)}
    # Current, previous and admitted target share one source SHA but have three
    # different digests. Digest-only previous and target images stay protected.
    for number in (4, 5, 9):
        images[f'sha256:{number:064x}']['tags'] = [IMAGE_REPOSITORY + ':' + 'a' * 40] if number == 4 else []
        images[f'sha256:{number:064x}']['digests'] = [IMAGE_REPOSITORY + '@sha256:' + str(number) * 64]
    images[f'sha256:{10:064x}']['tags'].append('other.example.invalid/app:retained')
    images[f'sha256:{11:064x}']['tags'] = ['other.example.invalid/db:retained']
    images[f'sha256:{12:064x}']['tags'] = []
    images[f'sha256:{12:064x}']['digests'] = []
    images[f'sha256:{14:064x}']['tags'] = []
    images[f'sha256:{15:064x}']['tags'] = [IMAGE_REPOSITORY + ':local-only']
    images[f'sha256:{15:064x}']['digests'] = []
    containers = {f'{number + 100:064x}': {
        'id': f'{number + 100:064x}', 'image_id': f'sha256:{number:064x}',
        'ref': f'{IMAGE_REPOSITORY}:{number:040x}',
    } for number in (1, 2, 3)}
    state = {'images': images, 'containers': containers, 'fault': '', 'ps_reads': 0,
             'deploy_fails': False, 'deploy_calls': 0}
    calls, warnings = [], []

    def command(argv, **options):
        calls.append(tuple(argv))
        if argv[0] == 'bash':
            state['deploy_calls'] += 1
            assert options['pass_fds'] == (effects.lock_fd,)
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in source.iterdir())
            if state['deploy_fails']:
                raise PostgresDeployError()
            return ''
        assert argv[0] == 'docker' and 'env' not in options
        assert not any('.Config.Env' in argument for argument in argv)
        if argv[1] == 'ps':
            assert argv == ['docker', 'ps', '--all', '--quiet', '--no-trunc']
            state['ps_reads'] += 1
            if state['fault'] == 'census':
                raise RuntimeError('private-canary-must-not-enter-warning')
            if state['ps_reads'] == 2:
                if state['fault'] == 'stale_pin':
                    directory.joinpath('prod.env').write_text(f'APP_IMAGE_TAG={13:040x}\n')
                if state['fault'] == 'stale_container':
                    state['containers'][f'{199:064x}'] = {
                        'id': f'{199:064x}', 'image_id': f'sha256:{13:064x}',
                        'ref': f'{IMAGE_REPOSITORY}:{13:040x}',
                    }
            return '\n'.join(state['containers'])
        if argv[1:3] == ['image', 'ls']:
            return '\n'.join(state['images'])
        if argv[2] == 'inspect':
            assert argv[3] == '--format'
            ids = argv[5:]
            if state['fault'] == 'malformed' and argv[1] == 'image':
                return 'private-canary-must-not-enter-warning'
            if state['fault'] == 'stale_alias' and argv[1] == 'image' and len(ids) == 1:
                state['images'][ids[0]]['tags'].append('other.example.invalid/app:new-alias')
            rows = state['containers'] if argv[1] == 'container' else state['images']
            return '\n'.join(json.dumps(rows[item]) for item in ids)
        if argv[1:3] == ['image', 'rm']:
            assert len(argv) in {4, 5} and '--force' not in argv
            if len(argv) == 5:
                assert argv[3] == '--no-prune'
            if state['fault'] == 'deletion':
                raise PostgresDeployError()
            image_id = argv[-1]
            del state['images'][image_id]
            # Docker's default removal also deletes untagged parent images;
            # --no-prune is required to confine this effect to the selected ID.
            if '--no-prune' not in argv:
                for parent_id in state.get('parents', {}).get(image_id, ()):
                    assert not state['images'][parent_id]['tags']
                    del state['images'][parent_id]
            return ''
        raise AssertionError('unexpected Docker cache command')

    monkeypatch.setattr(linux, '_command', command)
    monkeypatch.setattr(linux, '_emit_native_diagnostic', warnings.append)
    return effects, plan, state, calls, warnings


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_automatic_cache_cleanup_protects_live_and_recovery_images(tmp_path, monkeypatch, channel):
    effects, plan, state, calls, warnings = _cache_activation_harness(tmp_path, monkeypatch, channel=channel)
    pins = {path.name: path.read_bytes() for path in (tmp_path / 'config/deploy').glob('*.env')}
    before = set(state['images'])
    with effects.channel_lock():
        effects.activate(plan)
    removed = {f'sha256:{number:064x}' for number in (13, 14)}
    assert before - set(state['images']) == removed
    assert {path.name: path.read_bytes() for path in (tmp_path / 'config/deploy').glob('*.env')} == pins
    assert {f'sha256:{number:064x}' for number in range(1, 13)} <= set(state['images'])
    assert [call for call in calls if call[:3] == ('docker', 'image', 'rm')] == [
        ('docker', 'image', 'rm', '--no-prune', f'sha256:{number:064x}') for number in (13, 14)]
    assert calls[-1][0] == 'bash' and state['deploy_calls'] == 1
    assert not warnings and not list((tmp_path / 'secret-handles').iterdir())


@pytest.mark.parametrize('fault', ['census', 'malformed', 'deletion', 'stale_pin', 'stale_container', 'stale_alias'])
@pytest.mark.parametrize('deploy_fails', [False, True])
def test_optional_cache_cleanup_failure_does_not_gate_deploy(tmp_path, monkeypatch, capsys, fault, deploy_fails):
    from app.ops.postgres_deploy import PostgresDeployError
    effects, plan, state, calls, warnings = _cache_activation_harness(tmp_path, monkeypatch)
    state.update(fault=fault, deploy_fails=deploy_fails)
    before = set(state['images'])
    with effects.channel_lock():
        if deploy_fails:
            with pytest.raises(PostgresDeployError):
                effects.activate(plan)
        else:
            effects.activate(plan)
    assert set(state['images']) == before
    assert state['deploy_calls'] == 1 and calls[-1][0] == 'bash'
    assert len(warnings) == 1 and warnings[0].startswith(
        b'PRIORITY=4\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\nMESSAGE=optional image cache recovery skipped: reason=')
    assert 'private-canary' not in repr(warnings) + repr(capsys.readouterr())
    assert not list((tmp_path / 'secret-handles').iterdir())


@pytest.mark.parametrize('channel,automatic', [('dev', False), ('test', False), ('prod', False), ('prod', True)])
def test_cache_cleanup_excludes_manual_and_prod_paths(tmp_path, monkeypatch, channel, automatic):
    effects, plan, state, calls, warnings = _cache_activation_harness(
        tmp_path, monkeypatch, channel=channel, automatic=automatic)
    before = set(state['images'])
    with effects.channel_lock():
        effects._reclaim_image_cache(plan)
    assert set(state['images']) == before and calls == [] and warnings == []


def test_cache_cleanup_requires_existing_native_lock(tmp_path, monkeypatch):
    from app.ops.postgres_deploy import PostgresDeployError
    effects, plan, state, calls, warnings = _cache_activation_harness(tmp_path, monkeypatch)
    before = set(state['images'])
    effects._reclaim_image_cache(plan)
    with pytest.raises(PostgresDeployError):
        effects.activate(plan)
    assert set(state['images']) == before and calls == []
    assert len(warnings) == 1 and b'reason=native_lock_unproven' in warnings[0]


def test_cache_cleanup_preserves_unproved_local_application_images(tmp_path, monkeypatch):
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    effects, plan, state, calls, warnings = _cache_activation_harness(tmp_path, monkeypatch)
    # A tag in the digest field also cannot establish a registry-backed image.
    image_id = f'sha256:{16:064x}'
    state['images'][image_id] = {
        'id': image_id, 'tags': [IMAGE_REPOSITORY + ':manual-second'],
        'digests': [IMAGE_REPOSITORY + ':looks-like-tag'],
        'created': '2020-01-01T00:00:00Z',
    }
    before = set(state['images'])
    with effects.channel_lock():
        effects.activate(plan)
    assert before - set(state['images']) == {f'sha256:{number:064x}' for number in (13, 14)}
    assert {f'sha256:{number:064x}' for number in (15, 16)} <= set(state['images'])
    assert state['deploy_calls'] == 1 and calls[-1][0] == 'bash' and not warnings


def test_cache_cleanup_caps_exact_nonforce_removal_batch(tmp_path, monkeypatch):
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    effects, plan, state, calls, warnings = _cache_activation_harness(tmp_path, monkeypatch)
    for number in range(20, 31):
        image_id = f'sha256:{number:064x}'
        state['images'][image_id] = {
            'id': image_id, 'tags': [f'{IMAGE_REPOSITORY}:{number:040x}'],
            'digests': [f'{IMAGE_REPOSITORY}@sha256:{number:064x}'],
            'created': '2020-01-01T00:00:00Z',
        }
    before = set(state['images'])
    with effects.channel_lock():
        effects.activate(plan)
    expected = {f'sha256:{number:064x}' for number in (13, 14, *range(20, 26))}
    assert before - set(state['images']) == expected
    assert len([call for call in calls if call[:3] == ('docker', 'image', 'rm')]) == 8
    assert calls[-1][0] == 'bash' and not warnings


def test_cache_cleanup_preserves_unproved_untagged_parents(tmp_path, monkeypatch):
    effects, plan, state, calls, warnings = _cache_activation_harness(tmp_path, monkeypatch)
    selected = f'sha256:{13:064x}'
    parent = f'sha256:{12:064x}'
    # This parent has no tag or registry digest and cannot be reclaimed.
    state['parents'] = {selected: (parent,)}
    before = set(state['images'])
    with effects.channel_lock():
        effects.activate(plan)
    assert parent in state['images']
    assert before - set(state['images']) == {f'sha256:{number:064x}' for number in (13, 14)}
    assert ('docker', 'image', 'rm', '--no-prune', selected) in calls
    assert state['deploy_calls'] == 1 and calls[-1][0] == 'bash' and not warnings
