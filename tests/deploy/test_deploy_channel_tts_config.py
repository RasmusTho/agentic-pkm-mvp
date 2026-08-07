from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

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
        "}), encoding='utf-8')\n",
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
            f"pkm-dev-tts-test {shlex.quote(str(channel_env))} config",
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


def test_deploy_channel_invokes_tts_preflight_before_mutation() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    run_block = script.split('echo "deploy plan:', 1)[1]
    preflight = "deploy_channel_tts_config_preflight"

    assert preflight in run_block
    assert run_block.index(preflight) < run_block.index("migration_gate")
    assert run_block.index(preflight) < run_block.index("write_pin")
    assert run_block.index(preflight) < run_block.index("compose pull")
    assert "[ \"${action}\" = \"deploy\" ]" in run_block
