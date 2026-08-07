from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import time

import pytest
import yaml

from tests.deploy.test_deploy_channel import _deploy_harness, _run_deploy


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_HELPER = REPO_ROOT / "scripts/lib/deploy_channel_compose.sh"
DEPLOY_SCRIPT = REPO_ROOT / "scripts/deploy_channel.sh"


def _write_runtime_env(root: Path, *lines: str, channel: str = "dev") -> Path:
    runtime_dir = root / ("tmp-test" if channel == "test" else "tmp")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_env = runtime_dir / "runtime.env"
    runtime_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return runtime_env


def test_governed_runtime_env_supplies_tts_selectors_to_compose(tmp_path: Path) -> None:
    synthetic_root = tmp_path / "repo"
    (synthetic_root / "config/deploy").mkdir(parents=True)
    (synthetic_root / "scripts/lib").mkdir(parents=True)
    for relative in (
        "scripts/lib/deploy_channel_compose.sh",
        "scripts/lib/instance_ownership_host_state.sh",
        "scripts/lib/signboard_root.sh",
    ):
        source = REPO_ROOT / relative
        destination = synthetic_root / relative
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    tts_root = tmp_path / "machine-local-tts"
    tts_root.mkdir()
    _write_runtime_env(
        synthetic_root,
        "TTS_ENABLED=true",
        f"TTS_HOST_ROOT={tts_root}",
    )
    channel_env = synthetic_root / "config/deploy/dev.env"
    channel_env.write_text("WATCHER_RUNTIME_ENV_FILE=./tmp/runtime.env\n", encoding="utf-8")

    capture = tmp_path / "compose-env.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['TTS_CAPTURE']).write_text(json.dumps({\n"
        "  'enabled': os.environ.get('TTS_ENABLED'),\n"
        "  'host_root': os.environ.get('TTS_HOST_ROOT'),\n"
        "  'argv': sys.argv[1:],\n"
        "}), encoding='utf-8')\n"
        "print(os.environ.get('TTS_FAKE_STDOUT', 'f' * 64))\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    command = "\n".join(
        (
            "set -euo pipefail",
            f"source {shlex.quote(str(synthetic_root / 'scripts/lib/deploy_channel_compose.sh'))}",
            "deploy_channel_tts_config_preflight "
            f"{shlex.quote(str(synthetic_root))} dev {shlex.quote(str(channel_env))}",
            "deploy_channel_compose "
            f"{shlex.quote(str(synthetic_root))} dev docker-compose.dev.yml "
            f"pkm-dev-tts-test {shlex.quote(str(channel_env))} ps -q api",
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TTS_CAPTURE": str(capture),
            "TTS_ENABLED": "false",
            "TTS_HOST_ROOT": "hostile-caller-value",
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(tmp_path / "instance-ownership"),
        }
    )
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=synthetic_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(capture.read_text(encoding="utf-8"))
    assert evidence["enabled"] == "true"
    assert evidence["host_root"] == str(tts_root)
    assert str(tts_root) not in " ".join(evidence["argv"])
    assert str(tts_root) not in result.stdout + result.stderr
    exporter = (REPO_ROOT / "scripts/export_runtime_env.sh").read_text(encoding="utf-8")
    assert exporter.count('"TTS_ENABLED=${TTS_ENABLED}"') == 1
    assert exporter.count('"TTS_HOST_ROOT=${TTS_HOST_ROOT}"') == 1
    assert 'printf "TTS_ENABLED=%s\\n"' in exporter
    assert 'printf "TTS_HOST_ROOT=%s\\n"' in exporter

    def run_wrapper(*compose_arguments: str, command_env: dict[str, str] = env) -> subprocess.CompletedProcess[str]:
        wrapper_command = "\n".join(
            (
                "set -euo pipefail",
                f"source {shlex.quote(str(synthetic_root / 'scripts/lib/deploy_channel_compose.sh'))}",
                "deploy_channel_tts_config_preflight "
                f"{shlex.quote(str(synthetic_root))} dev {shlex.quote(str(channel_env))}",
                "deploy_channel_compose "
                f"{shlex.quote(str(synthetic_root))} dev docker-compose.dev.yml "
                f"pkm-dev-tts-test {shlex.quote(str(channel_env))} "
                + " ".join(shlex.quote(argument) for argument in compose_arguments),
            )
        )
        return subprocess.run(
            ["bash", "-c", wrapper_command],
            cwd=synthetic_root,
            env=command_env,
            check=False,
            capture_output=True,
            text=True,
        )

    quiet_success = run_wrapper("up", "-d", "api")
    assert quiet_success.returncode == 0
    assert "f" * 64 not in quiet_success.stdout + quiet_success.stderr
    assert str(tts_root) not in quiet_success.stdout + quiet_success.stderr

    blocked_config = run_wrapper("config")
    assert blocked_config.returncode == 92
    assert "command=config" in blocked_config.stderr
    assert str(tts_root) not in blocked_config.stdout + blocked_config.stderr

    malformed_env = env.copy()
    malformed_env["TTS_FAKE_STDOUT"] = str(tts_root)
    malformed_ps = run_wrapper("ps", "-q", "api", command_env=malformed_env)
    assert malformed_ps.returncode == 92
    assert "output=invalid" in malformed_ps.stderr
    assert str(tts_root) not in malformed_ps.stdout + malformed_ps.stderr


def test_normalized_external_tts_root_is_accepted(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    resolved_root = tmp_path / "tts-root"
    resolved_root.mkdir()
    selector = root / ".." / "tts-root"
    _write_runtime_env(root, "TTS_ENABLED=true", f"TTS_HOST_ROOT={selector}")

    result = _run_deploy(root, env, sha, "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "enabled=true" in result.stdout
    assert str(selector) not in result.stdout + result.stderr


def test_tts_bind_disables_host_path_creation() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    volumes = compose["services"]["api"]["volumes"]
    tts_mounts = [
        volume
        for volume in volumes
        if isinstance(volume, dict) and volume.get("target") == "/data/tts"
    ]

    assert tts_mounts == [
        {
            "type": "bind",
            "source": "${TTS_HOST_ROOT:-./config/tts-disabled}",
            "target": "/data/tts",
            "bind": {"create_host_path": False},
        }
    ]
    assert (REPO_ROOT / "config/tts-disabled/.gitkeep").is_file()


def test_disappearing_tts_root_fails_with_compose_output_redacted(
    tmp_path: Path,
) -> None:
    synthetic_root = tmp_path / "repo"
    (synthetic_root / "config/deploy").mkdir(parents=True)
    (synthetic_root / "scripts/lib").mkdir(parents=True)
    for relative in (
        "scripts/lib/deploy_channel_compose.sh",
        "scripts/lib/instance_ownership_host_state.sh",
        "scripts/lib/signboard_root.sh",
    ):
        destination = synthetic_root / relative
        destination.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")

    tts_root = tmp_path / "machine-local-tts"
    tts_root.mkdir()
    _write_runtime_env(
        synthetic_root,
        "TTS_ENABLED=true",
        f"TTS_HOST_ROOT={tts_root}",
    )
    channel_env = synthetic_root / "config/deploy/dev.env"
    channel_env.write_text("WATCHER_RUNTIME_ENV_FILE=./tmp/runtime.env\n", encoding="utf-8")

    private_dsn = "postgresql://private-user:private-pass@private-host/private-db"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"compose failed for ${TTS_HOST_ROOT:?}\" >&2\n"
        "echo \"unrelated=${PRIVATE_DSN:?}\"\n"
        "exit 23\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    command = "\n".join(
        (
            "set -u",
            f"source {shlex.quote(str(synthetic_root / 'scripts/lib/deploy_channel_compose.sh'))}",
            "deploy_channel_tts_config_preflight "
            f"{shlex.quote(str(synthetic_root))} dev {shlex.quote(str(channel_env))}",
            f"rmdir {shlex.quote(str(tts_root))}",
            "deploy_channel_compose "
            f"{shlex.quote(str(synthetic_root))} dev docker-compose.dev.yml "
            f"pkm-dev-tts-test {shlex.quote(str(channel_env))} up -d api",
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PRIVATE_DSN": private_dsn,
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(tmp_path / "instance-ownership"),
        }
    )
    result = subprocess.run(
        ["bash", "-c", command],
        cwd=synthetic_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 23
    assert "output=redacted" in result.stderr
    assert str(tts_root) not in output
    assert private_dsn not in output
    assert not tts_root.exists()


@pytest.mark.parametrize(
    ("enabled", "root_kind"),
    [
        ("TRUE", "valid"),
        ("true", "relative"),
        ("true", "missing"),
        ("true", "file"),
        ("true", "inaccessible"),
        ("true", "repo-contained"),
    ],
)
def test_invalid_enabled_tts_config_stops_before_channel_mutation(
    tmp_path: Path,
    enabled: str | None,
    root_kind: str,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    candidate = tmp_path / "tts-root"
    if root_kind == "valid":
        candidate.mkdir()
    elif root_kind == "relative":
        candidate = Path("relative/tts")
    elif root_kind == "file":
        candidate.write_text("not a directory", encoding="utf-8")
    elif root_kind == "inaccessible":
        candidate.mkdir()
        candidate.chmod(0o000)
    elif root_kind == "repo-contained":
        candidate = root / "private-tts"
        candidate.mkdir()

    lines = []
    if enabled is not None:
        lines.append(f"TTS_ENABLED={enabled}")
    if root_kind != "missing":
        lines.append(f"TTS_HOST_ROOT={candidate}")
    _write_runtime_env(root, *lines)

    result = _run_deploy(root, env, sha, "--dry-run")
    if root_kind == "inaccessible":
        candidate.chmod(0o700)

    assert result.returncode != 0
    assert "TTS_" in result.stderr
    assert not (root / "config/deploy/dev.env").exists()
    assert not (tmp_path / "docker-called").exists()


def test_tts_config_preflight_is_non_executing_and_redacted(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    execution_marker = tmp_path / "must-not-exist"
    private_path = tmp_path / "private-operator-tts-root"
    unrelated_dsn = "postgresql://private-user:private-pass@private-host/private-db"
    _write_runtime_env(
        root,
        f"TTS_ENABLED=$(touch {execution_marker})",
        f"TTS_HOST_ROOT={private_path}",
        f"DATABASE_URL={unrelated_dsn}",
        "UNRELATED_PRIVATE_VALUE=do-not-emit-this-value",
    )

    result = _run_deploy(root, env, sha, "--dry-run")
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert not execution_marker.exists()
    assert str(private_path) not in output
    assert unrelated_dsn not in output
    assert "do-not-emit-this-value" not in output
    assert "TTS_ENABLED" in output
    assert "path_class=" in output


@pytest.mark.parametrize("duplicate_key", ["TTS_ENABLED", "TTS_HOST_ROOT"])
def test_duplicate_tts_selector_is_rejected_before_mutation(
    tmp_path: Path, duplicate_key: str
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    tts_root = tmp_path / "tts-root"
    tts_root.mkdir()
    lines = ["TTS_ENABLED=true", f"TTS_HOST_ROOT={tts_root}"]
    lines.append(lines[0] if duplicate_key == "TTS_ENABLED" else lines[1])
    _write_runtime_env(root, *lines)

    result = _run_deploy(root, env, sha, "--dry-run")

    assert result.returncode == 91
    assert "reason=duplicate_key" in result.stderr
    assert str(tts_root) not in result.stdout + result.stderr
    assert not (root / "config/deploy/dev.env").exists()
    assert not (tmp_path / "docker-called").exists()


def test_runtime_env_open_error_is_redacted_and_stops_before_mutation(
    tmp_path: Path,
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    runtime_env = root / "tmp/runtime.env"
    runtime_env.unlink()
    runtime_env.mkdir()
    unrelated_dsn = "postgresql://private-user:private-pass@private-host/private-db"
    env["DATABASE_URL"] = unrelated_dsn

    result = _run_deploy(root, env, sha, "--dry-run")
    output = result.stdout + result.stderr

    assert result.returncode == 91
    assert "reason=validation_failed" in result.stderr
    assert str(runtime_env) not in output
    assert unrelated_dsn not in output
    assert not (root / "config/deploy/dev.env").exists()
    assert not (tmp_path / "docker-called").exists()


def test_atomic_export_never_exposes_partial_tts_snapshot(tmp_path: Path) -> None:
    synthetic_root = tmp_path / "repo"
    (synthetic_root / "config/deploy").mkdir(parents=True)
    (synthetic_root / "scripts/lib").mkdir(parents=True)
    for relative in (
        "scripts/lib/deploy_channel_compose.sh",
        "scripts/lib/instance_ownership_host_state.sh",
        "scripts/lib/signboard_root.sh",
    ):
        destination = synthetic_root / relative
        destination.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")

    runtime_env = tmp_path / "generated-runtime.env"
    runtime_env.write_text("TTS_ENABLED=false\n", encoding="utf-8")
    channel_env = synthetic_root / "config/deploy/dev.env"
    channel_env.write_text(
        f"WATCHER_RUNTIME_ENV_FILE={runtime_env}\n", encoding="utf-8"
    )
    tts_root = tmp_path / "machine-local-tts"
    tts_root.mkdir()

    marker = tmp_path / "publish-blocked"
    release = tmp_path / "publish-release"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_mv = bin_dir / "mv"
    fake_mv.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "touch \"${TTS_PUBLISH_MARKER:?}\"\n"
        "while [ ! -f \"${TTS_PUBLISH_RELEASE:?}\" ]; do sleep 0.01; done\n"
        "exec /bin/mv \"$@\"\n",
        encoding="utf-8",
    )
    fake_mv.chmod(0o755)

    export_env = os.environ.copy()
    export_env.pop("PYTEST_CURRENT_TEST", None)
    export_env.pop("PYTEST_VERSION", None)
    export_env.update(
        {
            "PATH": f"{bin_dir}:{export_env['PATH']}",
            "RUNTIME_ENV_PATH": str(runtime_env),
            "NO_VAULT_MODE": "1",
            "LLM_PROVIDER": "mock",
            "TTS_ENABLED": "true",
            "TTS_HOST_ROOT": str(tts_root),
            "TTS_PUBLISH_MARKER": str(marker),
            "TTS_PUBLISH_RELEASE": str(release),
        }
    )
    exporter = subprocess.Popen(
        ["bash", "scripts/export_runtime_env.sh"],
        cwd=REPO_ROOT,
        env=export_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()

    preflight_command = (
        f"source {shlex.quote(str(synthetic_root / 'scripts/lib/deploy_channel_compose.sh'))}; "
        "deploy_channel_tts_config_preflight "
        f"{shlex.quote(str(synthetic_root))} dev {shlex.quote(str(channel_env))}"
    )
    before_publish = subprocess.run(
        ["bash", "-c", preflight_command],
        cwd=synthetic_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert before_publish.returncode == 0
    assert "enabled=false" in before_publish.stdout

    release.touch()
    assert exporter.wait(timeout=5) == 0
    after_publish = subprocess.run(
        ["bash", "-c", preflight_command],
        cwd=synthetic_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert after_publish.returncode == 0
    assert "enabled=true" in after_publish.stdout
    assert str(tts_root) not in after_publish.stdout + after_publish.stderr


@pytest.mark.parametrize("no_vault_mode", [False, True])
def test_exporter_branches_publish_tts_selectors_together(
    tmp_path: Path, no_vault_mode: bool
) -> None:
    runtime_env = tmp_path / "runtime.env"
    tts_root = tmp_path / "machine-local-tts"
    tts_root.mkdir()
    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_VERSION", None)
    env.update(
        {
            "RUNTIME_ENV_PATH": str(runtime_env),
            "TTS_ENABLED": "true",
            "TTS_HOST_ROOT": str(tts_root),
            "LLM_PROVIDER": "mock",
        }
    )
    if no_vault_mode:
        env["NO_VAULT_MODE"] = "1"
        env.pop("VAULT_ROOT", None)
    else:
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        env["VAULT_ROOT"] = str(vault_root)
        env["DATABASE_URL"] = "postgresql+psycopg://fixture:fixture@db/fixture"
        env.pop("NO_VAULT_MODE", None)

    result = subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    assert result.returncode == 0
    lines = runtime_env.read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line.startswith("TTS_ENABLED=")] == [
        "TTS_ENABLED=true"
    ]
    assert [line for line in lines if line.startswith("TTS_HOST_ROOT=")] == [
        f"TTS_HOST_ROOT={tts_root}"
    ]


@pytest.mark.parametrize("tts_lines", [(), ("TTS_ENABLED=false",)])
def test_disabled_tts_and_rollback_bypass_enabled_root_requirement(
    tmp_path: Path,
    tts_lines: tuple[str, ...],
) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    _write_runtime_env(root, *tts_lines)
    deploy = _run_deploy(root, env, sha, "--dry-run")
    assert deploy.returncode == 0, deploy.stdout + deploy.stderr
    assert "enabled=false" in deploy.stdout

    _write_runtime_env(root, "TTS_ENABLED=true", "TTS_HOST_ROOT=relative/private")
    rollback = subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", "dev", sha, "--dry-run"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rollback.returncode == 0, rollback.stdout + rollback.stderr
    assert "tts config preflight" not in (rollback.stdout + rollback.stderr).lower()


def test_non_dry_rollback_clears_stale_caller_tts_root(tmp_path: Path) -> None:
    root, env, sha = _deploy_harness(tmp_path)
    pin_path = root / "config/deploy/dev.env"
    pin_path.write_text(
        "APP_IMAGE_REPOSITORY=example.invalid/pkm-app\n" f"APP_IMAGE_TAG={sha}\n",
        encoding="utf-8",
    )
    stale_root = tmp_path / "stale-machine-local-tts"
    env["TTS_ENABLED"] = "true"
    env["TTS_HOST_ROOT"] = str(stale_root)

    result = subprocess.run(
        ["bash", "scripts/deploy_channel.sh", "rollback", "dev", sha],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert str(stale_root) not in output
    assert not stale_root.exists()
    assert (root / "config/tts-disabled/.gitkeep").is_file()


def test_deploy_channel_invokes_tts_preflight_before_mutation() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    run_block = script.split('echo "deploy plan:', 1)[1]
    preflight = "deploy_channel_tts_config_preflight"

    assert preflight in run_block
    assert run_block.index(preflight) < run_block.index("migration_gate")
    assert run_block.index(preflight) < run_block.index("write_pin")
    assert run_block.index(preflight) < run_block.index("compose pull")
    assert "[ \"${action}\" = \"deploy\" ]" in run_block
