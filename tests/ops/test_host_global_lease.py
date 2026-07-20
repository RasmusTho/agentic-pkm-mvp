from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.run_with_host_lease import repo_common_lock_path


REPO_ROOT = Path(__file__).resolve().parents[2]
LEASE_SCRIPT = REPO_ROOT / "scripts/run_with_host_lease.py"


def _lease_command(
    resource: str, execution_id: str, child: str, *, wait_seconds: float = 0
) -> list[str]:
    return [
        sys.executable,
        str(LEASE_SCRIPT),
        "--resource",
        resource,
        "--execution-id",
        execution_id,
        "--wait-seconds",
        str(wait_seconds),
        "--",
        sys.executable,
        "-c",
        child,
    ]


def test_repo_common_lock_path_rejects_unsafe_resource() -> None:
    with pytest.raises(ValueError, match="resource must start"):
        repo_common_lock_path("../escape")


def test_host_lease_is_atomic_across_processes_and_releases_after_exit() -> None:
    resource = f"test-host-lease-{time.time_ns()}"
    holder = subprocess.Popen(
        _lease_command(resource, "holder", "import time; time.sleep(0.8)"),
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lock_path = repo_common_lock_path(resource)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if lock_path.exists():
            try:
                if json.loads(lock_path.read_text())["event"] == "host_lease_acquired":
                    break
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.02)
    else:
        holder.kill()
        holder.wait()
        pytest.fail("holder did not acquire the host lease")

    contender = subprocess.run(
        _lease_command(resource, "contender", "pass"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert contender.returncode == 75
    assert '"event": "host_lease_busy"' in contender.stderr
    assert '"execution_id": "holder"' in contender.stderr

    holder_stdout, holder_stderr = holder.communicate(timeout=3)
    assert holder.returncode == 0, (holder_stdout, holder_stderr)

    successor = subprocess.run(
        _lease_command(resource, "successor", "pass"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0
    assert '"event": "host_lease_released"' in successor.stderr


def test_child_keeps_lease_if_wrapper_is_killed() -> None:
    resource = f"test-host-lease-crash-{time.time_ns()}"
    holder = subprocess.Popen(
        _lease_command(resource, "crash-holder", "import time; time.sleep(0.8)"),
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock_path = repo_common_lock_path(resource)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if lock_path.exists():
            try:
                if json.loads(lock_path.read_text())["event"] == "host_lease_acquired":
                    break
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.02)
    else:
        holder.kill()
        holder.wait()
        pytest.fail("holder did not acquire the host lease")

    holder.kill()
    holder.wait(timeout=2)
    contender = subprocess.run(
        _lease_command(resource, "early-successor", "pass"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert contender.returncode == 75

    time.sleep(0.9)
    successor = subprocess.run(
        _lease_command(resource, "late-successor", "pass"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0


@pytest.mark.parametrize("termination_signal", [signal.SIGTERM, signal.SIGINT])
def test_termination_signal_is_forwarded_and_lease_releases_after_command_exits(
    termination_signal: signal.Signals,
) -> None:
    resource = f"test-host-lease-signal-{termination_signal.value}-{time.time_ns()}"
    holder = subprocess.Popen(
        _lease_command(resource, "signal-holder", "import time; time.sleep(30)"),
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lock_path = repo_common_lock_path(resource)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if lock_path.exists():
            try:
                if json.loads(lock_path.read_text())["event"] == "host_lease_acquired":
                    break
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.02)
    else:
        holder.kill()
        holder.wait()
        pytest.fail("holder did not acquire the host lease")

    holder.send_signal(termination_signal)
    holder_stdout, holder_stderr = holder.communicate(timeout=3)
    assert holder.returncode == 128 + termination_signal.value, (
        holder_stdout,
        holder_stderr,
    )
    assert '"event": "host_lease_released"' in holder_stderr

    successor = subprocess.run(
        _lease_command(resource, "signal-successor", "pass"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0


def test_descendant_does_not_inherit_lease_or_delay_release_receipt() -> None:
    resource = f"test-host-lease-descendant-{time.time_ns()}"
    child = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "sys.exit(0)"
    )
    holder = subprocess.run(
        _lease_command(resource, "descendant-holder", child),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    assert holder.returncode == 0
    assert '"event": "host_lease_released"' in holder.stderr

    successor = subprocess.run(
        _lease_command(resource, "descendant-successor", "pass"),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0
