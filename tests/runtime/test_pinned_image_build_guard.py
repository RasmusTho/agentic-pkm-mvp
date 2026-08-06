"""Regression coverage for the pinned-image build guard (#4361).

The compose service definitions carry both `build:` and
`image: ${APP_IMAGE_REPOSITORY}:${APP_IMAGE_TAG}`. Before this fix,
`scripts/start_full_system.sh` passed `docker compose up --build`
unconditionally, so a pinned-image channel (prod: COMPOSE_FILE excludes
docker-compose.app-bind.yml) would silently BUILD the image from the local
checkout and tag the result with the pinned tag whenever that tag was not
already present locally -- running content then diverged from the
authorized pin.

These tests exercise `scripts/lib/pinned_image_guard.sh::app_image_pinned_mode`
directly (the pure mode-detection function) plus a bash harness that
reproduces the decision block wired into `scripts/start_full_system.sh`, so
the pull-or-fail-loud / override contract is covered without a real docker
daemon.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_LIB = REPO_ROOT / "scripts/lib/pinned_image_guard.sh"
START_SCRIPT = REPO_ROOT / "scripts/start_full_system.sh"


def _bash(cmd: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", "-lc", cmd],
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=REPO_ROOT,
    )


def _bash_ok(cmd: str, *, env: dict[str, str] | None = None) -> str:
    proc = _bash(cmd, env=env)
    assert proc.returncode == 0, f"bash failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return proc.stdout.strip()


@pytest.mark.parametrize(
    "compose_file,expected",
    [
        ("docker-compose.yaml:docker-compose.prod.yml", "PINNED"),
        ("docker-compose.yaml:docker-compose.app-bind.yml:docker-compose.dev.yml", "NOT_PINNED"),
        ("docker-compose.yaml:docker-compose.app-bind.yml:docker-compose.prod.yml", "NOT_PINNED"),
        ("docker-compose.yaml:docker-compose.dev.yml", "PINNED"),
        ("", "PINNED"),
    ],
)
def test_app_image_pinned_mode(compose_file: str, expected: str) -> None:
    out = _bash_ok(
        f"source '{GUARD_LIB}'; "
        f"if app_image_pinned_mode '{compose_file}'; then echo PINNED; else echo NOT_PINNED; fi"
    )
    assert out == expected


def test_prod_compose_file_as_makefile_resolves_it_is_pinned() -> None:
    """`make prod-start-full` (via COMPOSE_PROD_FILES in the Makefile) never
    includes the app-bind overlay, so it must be pinned-image mode."""
    prod_compose_file = "docker-compose.yaml:docker-compose.prod.yml"
    out = _bash_ok(
        f"source '{GUARD_LIB}'; "
        f"if app_image_pinned_mode '{prod_compose_file}'; then echo PINNED; else echo NOT_PINNED; fi"
    )
    assert out == "PINNED"


# ---------------------------------------------------------------------------
# Harness reproducing the decision block wired into start_full_system.sh:
# pinned mode => never pass --build; pull the pin; fail loud on pull failure
# unless APP_BUILD_OVERRIDE=1 is set.
# ---------------------------------------------------------------------------

_DECISION_HARNESS = r"""
set -euo pipefail
source '__GUARD_LIB__'

COMPOSE_FILE="__COMPOSE_FILE__"
preflight_services=(db api worker watcher)
compose_up_build_args=("--build")

run_docker_compose() {
  if [ "$1" = "pull" ]; then
    return "${PULL_RC:-0}"
  fi
  return 0
}

if app_image_pinned_mode "${COMPOSE_FILE:-}"; then
  compose_up_build_args=()
  pinned_pull_targets=()
  for pinned_svc in api worker watcher; do
    for candidate_svc in "${preflight_services[@]}"; do
      if [ "$candidate_svc" = "$pinned_svc" ]; then
        pinned_pull_targets+=("$pinned_svc")
      fi
    done
  done
  if [ "${#pinned_pull_targets[@]}" -gt 0 ]; then
    if ! run_docker_compose pull "${pinned_pull_targets[@]}"; then
      if [ "${APP_BUILD_OVERRIDE:-0}" = "1" ]; then
        compose_up_build_args=("--build")
      else
        echo "EXIT_REASON=pinned_image_pull_failed"
        exit 1
      fi
    fi
  fi
fi

if [ "${#compose_up_build_args[@]}" -gt 0 ]; then
  echo "BUILD_ARGS=${compose_up_build_args[*]}"
else
  echo "BUILD_ARGS=<none>"
fi
"""


def _run_decision_harness(
    *, compose_file: str, pull_rc: int = 0, build_override: str | None = None
) -> subprocess.CompletedProcess[str]:
    script = _DECISION_HARNESS.replace("__GUARD_LIB__", str(GUARD_LIB)).replace(
        "__COMPOSE_FILE__", compose_file
    )
    env = {"PULL_RC": str(pull_rc)}
    if build_override is not None:
        env["APP_BUILD_OVERRIDE"] = build_override
    return _bash(script, env=env)


def test_pinned_mode_never_builds_when_pull_succeeds() -> None:
    proc = _run_decision_harness(
        compose_file="docker-compose.yaml:docker-compose.prod.yml", pull_rc=0
    )
    assert proc.returncode == 0, proc.stderr
    assert "BUILD_ARGS=<none>" in proc.stdout


def test_pinned_mode_fails_loud_on_pull_failure_without_override() -> None:
    proc = _run_decision_harness(
        compose_file="docker-compose.yaml:docker-compose.prod.yml", pull_rc=1
    )
    assert proc.returncode == 1
    assert "EXIT_REASON=pinned_image_pull_failed" in proc.stdout
    assert "BUILD_ARGS" not in proc.stdout


def test_pinned_mode_falls_back_to_build_with_explicit_override() -> None:
    proc = _run_decision_harness(
        compose_file="docker-compose.yaml:docker-compose.prod.yml",
        pull_rc=1,
        build_override="1",
    )
    assert proc.returncode == 0, proc.stderr
    assert "BUILD_ARGS=--build" in proc.stdout


def test_code_bind_mode_keeps_default_build_behavior_unchanged() -> None:
    proc = _run_decision_harness(
        compose_file="docker-compose.yaml:docker-compose.app-bind.yml:docker-compose.dev.yml",
        pull_rc=0,
    )
    assert proc.returncode == 0, proc.stderr
    assert "BUILD_ARGS=--build" in proc.stdout


def test_prod_services_carry_both_build_and_image_pin(tmp_path: Path) -> None:
    """Structural guard: the scenario this issue describes (build+image both
    present) must still hold, otherwise this fix's guard is moot."""
    import yaml

    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    for svc_name in ("api", "worker", "watcher"):
        svc = compose["services"][svc_name]
        assert "build" in svc, f"{svc_name} must declare build: (dev/code-bind path)"
        assert svc.get("image", "").startswith("${APP_IMAGE_REPOSITORY"), (
            f"{svc_name} must declare an APP_IMAGE_REPOSITORY/APP_IMAGE_TAG image pin"
        )
