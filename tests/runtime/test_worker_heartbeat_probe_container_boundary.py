"""Regression coverage for the worker heartbeat probe in named-volume mode
(#4361).

`/app/tmp` (and `/app/tmp-test` for the test channel) is always the
`runtime-tmp` Docker-managed named volume declared in docker-compose.yaml --
never a host bind mount, in any channel. Reading a host-side
`tmp/worker_heartbeat.json` path (the pre-#4361 behavior) can never observe a
heartbeat written inside the worker container, which made a fully healthy
pinned-image prod stack fail `make prod-start-full` with "worker heartbeat
file missing after 30 seconds".

These tests exercise `scripts/lib/worker_heartbeat_probe.sh` directly: the
channel-correct container path resolution, and the container-boundary
readiness check (which must go through `docker compose exec`, never a host
filesystem read).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts/lib/worker_heartbeat_probe.sh"


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
    "compose_project,expected",
    [
        ("pkm-prod", "/app/tmp/worker_heartbeat.json"),
        ("pkm-dev", "/app/tmp/worker_heartbeat.json"),
        ("pkm-test", "/app/tmp-test/worker_heartbeat.json"),
        ("", "/app/tmp/worker_heartbeat.json"),
    ],
)
def test_resolve_container_worker_heartbeat_path(compose_project: str, expected: str) -> None:
    out = _bash_ok(
        f"source '{LIB}'; "
        f"export COMPOSE_PROJECT_NAME='{compose_project}'; "
        "resolve_container_worker_heartbeat_path"
    )
    assert out == expected


def test_worker_heartbeat_ready_probes_through_container_boundary_not_host_fs(
    tmp_path: Path,
) -> None:
    """A host-side file at the equivalent path must NOT satisfy the probe.

    This is the exact #4361 regression: the probe must call
    `run_docker_compose exec ... worker ...`, never stat/read a host path.
    """
    # A file exists on the host at a path that looks like the old (broken)
    # lookup location -- the probe must still report "not ready" because it
    # never consults the host filesystem at all.
    host_lookalike = tmp_path / "worker_heartbeat.json"
    host_lookalike.write_text('{"ts": 1}', encoding="utf-8")

    script = f"""
set -euo pipefail
source '{LIB}'
run_docker_compose() {{
  # Simulate: worker container has NO heartbeat file yet.
  if [ "$1" = "exec" ]; then
    return 1
  fi
  return 0
}}
if worker_heartbeat_ready "/app/tmp/worker_heartbeat.json"; then
  echo READY
else
  echo NOT_READY
fi
"""
    proc = _bash(script, env={"HOST_LOOKALIKE": str(host_lookalike)})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "NOT_READY"


def test_worker_heartbeat_ready_true_when_container_exec_succeeds() -> None:
    script = f"""
set -euo pipefail
source '{LIB}'
run_docker_compose() {{
  if [ "$1" = "exec" ]; then
    return 0
  fi
  return 1
}}
if worker_heartbeat_ready "/app/tmp/worker_heartbeat.json"; then
  echo READY
else
  echo NOT_READY
fi
"""
    out = _bash_ok(script)
    assert out == "READY"


def test_worker_heartbeat_ready_uses_test_channel_path(tmp_path: Path) -> None:
    """The container path passed to `docker compose exec` must be the
    channel-resolved one (/app/tmp-test/...) for the test channel, not the
    prod/dev default.

    `worker_heartbeat_ready` redirects the wrapped command's own stdout/stderr
    to /dev/null, so the stub writes what it observed to a side file instead
    of stdout/stderr.
    """
    captured = tmp_path / "captured.txt"
    script = f"""
set -euo pipefail
source '{LIB}'
export COMPOSE_PROJECT_NAME=pkm-test
run_docker_compose() {{
  printf '%s' "$*" > '{captured}'
  return 0
}}
path="$(resolve_container_worker_heartbeat_path)"
worker_heartbeat_ready "$path"
"""
    _bash_ok(script)
    assert captured.exists(), "run_docker_compose stub was never invoked"
    assert "tmp-test/worker_heartbeat.json" in captured.read_text(encoding="utf-8")
