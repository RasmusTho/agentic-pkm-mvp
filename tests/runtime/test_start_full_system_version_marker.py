"""Regression guard for prod build identity in `scripts/start_full_system.sh`."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def test_start_full_system_exports_vcs_ref_for_compose_build(tmp_path: Path) -> None:
    expected_sha = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    capture_file = tmp_path / "compose-up.env"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail

capture_file={capture_file!s}

if [ "${{1:-}}" = "info" ]; then
  exit 0
fi

if [ "${{1:-}}" = "ps" ]; then
  exit 0
fi

if [ "${{1:-}}" = "compose" ]; then
  shift
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --env-file|-f|-p|--project-name)
        shift 2
        ;;
      *)
        break
        ;;
    esac
  done

  case "${{1:-}}" in
    config)
      printf '{{"services":{{}}}}\n'
      exit 0
      ;;
    up)
      {{
        printf 'COMMAND=%s\n' "compose $*"
        printf 'VCS_REF=%s\n' "${{VCS_REF:-}}"
        printf 'BUILT_AT=%s\n' "${{BUILT_AT:-}}"
        printf 'COMPOSE_FILE=%s\n' "${{COMPOSE_FILE:-}}"
        printf 'COMPOSE_PROJECT_NAME=%s\n' "${{COMPOSE_PROJECT_NAME:-}}"
      }} >"$capture_file"
      exit 99
      ;;
  esac
fi

echo "unexpected docker invocation: $*" >&2
exit 97
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "HOME": str(Path.home()),
        "PKM_ENVIRONMENT": "prod",
        "START_MODE": "diagnostic",
        "START_FLIGHT_RECORDER": "0",
        "VCS_REF": "unknown",
        "BUILT_AT": "unknown",
    }

    proc = subprocess.run(
        ["bash", "scripts/start_full_system.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 99, proc.stderr + proc.stdout
    assert capture_file.exists(), proc.stderr + proc.stdout

    captured = _read_env_file(capture_file)
    assert captured["COMMAND"] == "compose up --build db api"
    assert captured["COMPOSE_PROJECT_NAME"] == "pkm-prod"
    assert "docker-compose.prod.yml" in captured["COMPOSE_FILE"]
    assert captured["VCS_REF"] == expected_sha
    assert captured["BUILT_AT"] != "unknown"
    assert TIMESTAMP_RE.fullmatch(captured["BUILT_AT"])
