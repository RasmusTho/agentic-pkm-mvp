from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import pytest

from scripts.run_with_host_lease import (
    HOST_GLOBAL_RESOURCE_NAMES,
    repo_common_lock_path,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
LEASE_SCRIPT = REPO_ROOT / "scripts/run_with_host_lease.py"


@pytest.fixture
def lease_repo(tmp_path: Path) -> Iterator[Path]:
    repo = tmp_path / "lease-repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    lock_path = _lease_lock_path(repo)
    try:
        yield repo
    finally:
        lock_path.unlink(missing_ok=True)
        assert not lock_path.exists()


def _canonical_resource() -> str:
    assert len(HOST_GLOBAL_RESOURCE_NAMES) == 1
    return next(iter(HOST_GLOBAL_RESOURCE_NAMES))


def _lease_lock_path(repo: Path) -> Path:
    return repo / ".git" / "host-global-leases" / f"{_canonical_resource()}.lock"


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


def test_unrecognised_resource_name_is_rejected(lease_repo: Path) -> None:
    rejected_resource = "not-a-real-resource"
    result = subprocess.run(
        _lease_command(rejected_resource, "rejected", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert rejected_resource in result.stderr
    assert not (
        lease_repo / ".git" / "host-global-leases" / f"{rejected_resource}.lock"
    ).exists()


def test_documented_full_suite_resource_is_on_allowlist() -> None:
    workflow = (REPO_ROOT / "docs/development/DEV_WORKFLOW.md").read_text()
    documented_resources = {
        token.split()[0]
        for token in workflow.split("--resource ")[1:]
    }

    assert documented_resources == HOST_GLOBAL_RESOURCE_NAMES


def test_host_lease_is_atomic_across_processes_and_releases_after_exit(
    lease_repo: Path,
) -> None:
    resource = _canonical_resource()
    holder = subprocess.Popen(
        _lease_command(resource, "holder", "import time; time.sleep(0.8)"),
        cwd=lease_repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lock_path = _lease_lock_path(lease_repo)
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
        cwd=lease_repo,
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
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0
    assert '"event": "host_lease_released"' in successor.stderr
    lock_path.unlink()
    assert not lock_path.exists()


def test_child_keeps_lease_if_wrapper_is_killed(lease_repo: Path) -> None:
    resource = _canonical_resource()
    holder = subprocess.Popen(
        _lease_command(resource, "crash-holder", "import time; time.sleep(0.8)"),
        cwd=lease_repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock_path = _lease_lock_path(lease_repo)
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
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert contender.returncode == 75

    time.sleep(0.9)
    successor = subprocess.run(
        _lease_command(resource, "late-successor", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0


def test_supervisor_keeps_lease_if_wrapper_process_group_is_killed(
    lease_repo: Path,
) -> None:
    resource = _canonical_resource()
    holder = subprocess.Popen(
        _lease_command(resource, "group-crash-holder", "import time; time.sleep(0.8)"),
        cwd=lease_repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    lock_path = _lease_lock_path(lease_repo)
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

    os.killpg(holder.pid, signal.SIGKILL)
    holder.wait(timeout=2)
    contender = subprocess.run(
        _lease_command(resource, "group-crash-contender", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert contender.returncode == 75

    time.sleep(0.9)
    successor = subprocess.run(
        _lease_command(resource, "group-crash-successor", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0


@pytest.mark.parametrize("termination_signal", [signal.SIGTERM, signal.SIGINT])
def test_termination_signal_is_forwarded_and_lease_releases_after_command_exits(
    termination_signal: signal.Signals, lease_repo: Path
) -> None:
    resource = _canonical_resource()
    holder = subprocess.Popen(
        _lease_command(resource, "signal-holder", "import time; time.sleep(30)"),
        cwd=lease_repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stderr is not None
    acquired_line = holder.stderr.readline()
    assert json.loads(acquired_line)["event"] == "host_lease_acquired"

    holder.send_signal(termination_signal)
    holder_stdout, remaining_stderr = holder.communicate(timeout=3)
    holder_stderr = acquired_line + remaining_stderr
    assert holder.returncode != 0, (holder_stdout, holder_stderr)
    assert '"event": "host_lease_released"' in holder_stderr
    release_receipt = json.loads(holder_stderr.splitlines()[-1])
    assert release_receipt["return_code"] == holder.returncode

    successor = subprocess.run(
        _lease_command(resource, "signal-successor", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0


def test_descendant_does_not_inherit_lease_or_delay_release_receipt(
    lease_repo: Path,
) -> None:
    resource = _canonical_resource()
    child = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "sys.exit(0)"
    )
    holder = subprocess.run(
        _lease_command(resource, "descendant-holder", child),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    assert holder.returncode == 0
    assert '"event": "host_lease_released"' in holder.stderr

    successor = subprocess.run(
        _lease_command(resource, "descendant-successor", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0


@pytest.mark.parametrize("termination_signal", [signal.SIGTERM, signal.SIGINT])
def test_signalled_waiting_contender_never_runs_command(
    termination_signal: signal.Signals, tmp_path: Path, lease_repo: Path
) -> None:
    resource = _canonical_resource()
    marker = tmp_path / "contender-ran"
    holder = subprocess.Popen(
        _lease_command(resource, "wait-holder", "import time; time.sleep(2)"),
        cwd=lease_repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock_path = _lease_lock_path(lease_repo)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if lock_path.exists():
            try:
                if json.loads(lock_path.read_text())["execution_id"] == "wait-holder":
                    break
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.02)
    else:
        holder.kill()
        holder.wait()
        pytest.fail("holder did not acquire the host lease")

    contender_child = f"from pathlib import Path; Path({str(marker)!r}).touch()"
    contender = subprocess.Popen(
        _lease_command(
            resource,
            "signalled-waiter",
            contender_child,
            wait_seconds=3,
        ),
        cwd=lease_repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert contender.stderr is not None
    readable, _, _ = select.select([contender.stderr], [], [], 3)
    assert readable, "waiting contender did not publish its readiness receipt"
    waiting_line = contender.stderr.readline()
    assert json.loads(waiting_line)["event"] == "host_lease_waiting"
    cancellation_started = time.monotonic()
    contender.send_signal(termination_signal)
    try:
        contender_stdout, remaining_stderr = contender.communicate(timeout=0.75)
        contender_stderr = waiting_line + remaining_stderr
    finally:
        if contender.poll() is None:
            contender.kill()
            contender.wait()
        holder.terminate()
        holder.wait(timeout=3)

    assert contender.returncode == 128 + termination_signal.value, (
        contender_stdout,
        contender_stderr,
    )
    assert time.monotonic() - cancellation_started < 0.75
    assert '"event": "host_lease_signal_forwarded"' in contender_stderr
    assert '"event": "host_lease_cancelled"' in contender_stderr
    assert not marker.exists()


def test_exec_child_restores_default_sigpipe_disposition(lease_repo: Path) -> None:
    resource = _canonical_resource()
    command = [
        sys.executable,
        str(LEASE_SCRIPT),
        "--resource",
        resource,
        "--execution-id",
        "sigpipe-default",
        "--",
        "/bin/bash",
        "-o",
        "pipefail",
        "-c",
        "yes | head -n 1 >/dev/null",
    ]
    result = subprocess.run(
        command,
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 128 + signal.SIGPIPE, result.stderr


@pytest.mark.parametrize("kill_process_group", [False, True])
def test_orphaned_waiting_supervisor_never_runs_command(
    kill_process_group: bool, tmp_path: Path, lease_repo: Path
) -> None:
    resource = _canonical_resource()
    marker = tmp_path / "orphan-waiter-ran"
    release_holder = tmp_path / "release-holder"
    holder_child = (
        "import sys, time; from pathlib import Path; "
        f"release = Path({str(release_holder)!r}); deadline = time.monotonic() + 5; "
        "\nwhile not release.exists() and time.monotonic() < deadline: time.sleep(0.02)"
        "\nsys.exit(0 if release.exists() else 2)"
    )
    holder = subprocess.Popen(
        _lease_command(resource, "orphan-wait-holder", holder_child),
        cwd=lease_repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lock_path = _lease_lock_path(lease_repo)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if lock_path.exists():
            try:
                if json.loads(lock_path.read_text())["execution_id"] == "orphan-wait-holder":
                    break
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(0.02)
    else:
        holder.kill()
        holder.wait()
        pytest.fail("holder did not acquire the host lease")

    waiter_child = f"from pathlib import Path; Path({str(marker)!r}).touch()"
    waiter = subprocess.Popen(
        _lease_command(
            resource,
            "orphaned-waiter",
            waiter_child,
            wait_seconds=3,
        ),
        cwd=lease_repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=kill_process_group,
    )
    assert waiter.stderr is not None
    readable, _, _ = select.select([waiter.stderr], [], [], 3)
    assert readable, "waiting supervisor did not publish its readiness receipt"
    waiting_receipt = json.loads(waiter.stderr.readline())
    assert waiting_receipt["event"] == "host_lease_waiting"
    assert waiting_receipt["supervisor_pid"] == waiting_receipt["supervisor_pgid"]
    if kill_process_group:
        assert waiting_receipt["supervisor_pgid"] != os.getpgid(waiter.pid)
    if kill_process_group:
        os.killpg(waiter.pid, signal.SIGKILL)
    else:
        waiter.kill()
    waiter.wait(timeout=2)
    assert json.loads(lock_path.read_text())["execution_id"] == "orphan-wait-holder"
    release_holder.touch()
    holder.wait(timeout=3)
    assert holder.returncode == 0

    supervisor_pid = waiting_receipt["supervisor_pid"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(supervisor_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("orphaned waiting supervisor did not exit after parent handoff failed")
    assert not marker.exists()

    successor = subprocess.run(
        _lease_command(resource, "orphan-wait-successor", "pass", wait_seconds=1),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    assert successor.returncode == 0, successor.stderr
    assert not marker.exists()


def test_outer_owner_keeps_lease_until_command_dies_if_supervisor_is_killed(
    tmp_path: Path, lease_repo: Path
) -> None:
    resource = _canonical_resource()
    command_pid_path = tmp_path / "command.pid"
    child = (
        "import os, signal, time; from pathlib import Path; "
        f"Path({str(command_pid_path)!r}).write_text(str(os.getpid())); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    )
    holder = subprocess.Popen(
        _lease_command(resource, "supervisor-crash-holder", child),
        cwd=lease_repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lock_path = _lease_lock_path(lease_repo)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if command_pid_path.exists():
            break
        time.sleep(0.02)
    else:
        holder.kill()
        holder.wait()
        pytest.fail("wrapped command did not start")

    supervisor_pid = int(json.loads(lock_path.read_text())["pid"])
    command_pid = int(command_pid_path.read_text())
    os.kill(supervisor_pid, signal.SIGKILL)

    contender = subprocess.run(
        _lease_command(resource, "recovery-contender", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert contender.returncode == 75

    holder_stdout, holder_stderr = holder.communicate(timeout=5)
    assert holder.returncode == 137, (holder_stdout, holder_stderr)
    assert '"event": "host_lease_recovered_after_supervisor_exit"' in holder_stderr
    with pytest.raises(ProcessLookupError):
        os.kill(command_pid, 0)

    successor = subprocess.run(
        _lease_command(resource, "recovery-successor", "pass"),
        cwd=lease_repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert successor.returncode == 0
