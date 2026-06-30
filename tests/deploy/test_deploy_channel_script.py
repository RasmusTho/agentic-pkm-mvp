from __future__ import annotations

import os
import re
import subprocess
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

import yaml


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


@contextmanager
def _temporary_previous_pin(channel: str, sha: str) -> Iterator[Path]:
    path = REPO_ROOT / "config" / "deploy" / f"{channel}.previous.env"
    original = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(
        f"APP_IMAGE_REPOSITORY=ghcr.io/rasmustho/pkm-app\nAPP_IMAGE_TAG={sha}\n",
        encoding="utf-8",
    )
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
    assert run_block.index("compose pull") < run_block.index("compose up -d --force-recreate")

    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_health_gate_blocks_and_triggers_rollback() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "health_gate" in text
    assert "http://127.0.0.1:${api_port}/healthz" in text
    assert "http://127.0.0.1:${ui_port}/healthz" in text
    assert "health gate failed; attempting rollback to previous pin" in text
    run_block = text.split('echo "deploy plan:', 1)[1]
    assert run_block.index("compose up -d --force-recreate") < run_block.index("health_gate")
    assert run_block.index("health_gate") < run_block.index("version_gate")


def test_rollback_uses_previous_pin_and_skips_forward_only_reversal() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "rollback" in text
    assert "previous_pin_file" in text
    assert "Do not auto-reverse forward-only migrations" not in text
    assert "forward_only" in text
    assert "ack_forward_only" in text
    assert "reverse" not in re.sub(r"reversibility|reversible", "", text)


def test_rollback_dry_run_without_sha_parses_flag_and_skips_writes(tmp_path: Path) -> None:
    explicit_previous_sha = _git_sha("HEAD")
    pin_path = REPO_ROOT / "config" / "deploy" / "dev.env"
    original_pin = pin_path.read_text(encoding="utf-8")
    env, docker_marker, curl_marker = _stub_env(tmp_path)

    with _temporary_previous_pin("dev", explicit_previous_sha):
        result = _run_script("rollback", "dev", "--dry-run", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"target={explicit_previous_sha}" in result.stdout
    assert "dry-run: stopping before pin write, docker recreate, health gate, and receipt write" in result.stdout
    assert pin_path.read_text(encoding="utf-8") == original_pin
    assert not docker_marker.exists()
    assert not curl_marker.exists()


def test_rollback_with_explicit_sha_still_allows_flags(tmp_path: Path) -> None:
    previous_sha = _git_sha("HEAD~1")
    explicit_sha = _git_sha("HEAD")
    env, docker_marker, curl_marker = _stub_env(tmp_path)

    with _temporary_previous_pin("dev", previous_sha):
        result = _run_script("rollback", "dev", explicit_sha, "--dry-run", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"target={explicit_sha}" in result.stdout
    assert f"target={previous_sha}" not in result.stdout
    assert "dry-run: stopping before pin write, docker recreate, health gate, and receipt write" in result.stdout
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
