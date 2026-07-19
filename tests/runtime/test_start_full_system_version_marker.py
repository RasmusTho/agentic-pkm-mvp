"""Regression guard for prod build identity in `scripts/start_full_system.sh`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
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

if [ "${{1:-}}" = "volume" ]; then
  case "${{2:-}}" in
    inspect) exit 1 ;;
    create) exit 0 ;;
  esac
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
    run|stop)
      # The instance-state deployment producer now fences/finalizes before
      # the first compose up. This test is scoped to the later build marker.
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
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        f"""#!/usr/bin/env bash
set -eu
case "${{1:-}}" in
  */scripts/instance_state_writer_inventory.py)
    command="${{2:-}}"
    if [ "$command" = controller-token ]; then
      printf 'darwin:%064d\n' 0
      exit 0
    fi
    case "$command" in
      produce-legacy-owners|prove-quiescent|validate-legacy-owners)
        while [ "$#" -gt 0 ]; do
          if [ "$1" = --output ]; then
            printf '{{}}\n' >"$2"
            exit 0
          fi
          shift
        done
        exit 2
        ;;
    esac
    ;;
esac
exec {sys.executable!s} "$@"
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    fake_inline_python = fake_bin / "python"
    fake_inline_python.write_text(
        f"""#!/usr/bin/env bash
set -eu
# This marker test exits at compose-up and does not exercise the independent
# Obsidian-required policy or startup-status receipt serialization. Bypass only
# those exact repeated inline programs and delegate every other helper.
if [ "${{1:-}}" = - ]; then
  program="$(cat)"
  case "$program" in
    *"from app.cli.health import _obsidian_required"*"_obsidian_required()"*)
      printf '0\n'
      exit 0
      ;;
    *"STARTUP_STATUS_PATH"*"tmp_path.write_text(json.dumps(payload, ensure_ascii=False))"*)
      printf '{{}}\n' > "${{STARTUP_STATUS_PATH:?}}"
      exit 0
      ;;
  esac
  printf '%s\n' "$program" | {sys.executable!s} "$@"
  exit $?
fi
exec {sys.executable!s} "$@"
""",
        encoding="utf-8",
    )
    fake_inline_python.chmod(0o755)

    env = os.environ.copy()
    for name in (
        "DESIGN_HANDOFF_APP_LOCAL_SETTINGS",
        "INSTANCE_LEGACY_OWNER_CONFIG_PATHS",
        "VAULT_HOST_ROOT",
        "VAULT_ROOT",
        "VAULT_ROOT_DEV",
        "VAULT_ROOT_PROD",
        "VAULT_ROOT_TEST",
        "WATCHER_RUNTIME_ENV_FILE",
        "WATCHER_VAULT_PATH",
    ):
        env.pop(name, None)
    env.update(
        {
            "PATH": f"{fake_bin}:{env.get('PATH', '')}",
            "HOME": str(Path.home()),
            "XDG_DATA_HOME": str(tmp_path / "xdg"),
            "PKM_ENVIRONMENT": "prod",
            "START_MODE": "diagnostic",
            "START_FLIGHT_RECORDER": "0",
            "VCS_REF": "unknown",
            "BUILT_AT": "unknown",
        }
    )

    proc = subprocess.run(
        ["bash", "scripts/start_full_system.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
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
