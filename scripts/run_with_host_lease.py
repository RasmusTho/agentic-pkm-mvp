#!/usr/bin/env python3
"""Run one host-global command while holding an atomic repo-common lease."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


_RESOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
HOST_GLOBAL_RESOURCE_NAMES = frozenset({"pytest-not-pg"})
_TEMPFAIL = 75


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_path(*args: str) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


def repo_common_lock_path(resource: str) -> Path:
    """Return one lock path shared by every worktree of the current repository."""

    if not _RESOURCE_RE.fullmatch(resource):
        raise ValueError(
            "resource must start with an alphanumeric character and contain only "
            "letters, numbers, dot, underscore, or hyphen (max 80 chars)"
        )
    if resource not in HOST_GLOBAL_RESOURCE_NAMES:
        allowed = ", ".join(sorted(HOST_GLOBAL_RESOURCE_NAMES))
        raise ValueError(
            f"unrecognised host-global resource {resource!r}; expected one of: {allowed}"
        )
    try:
        common_dir = _git_path("--path-format=absolute", "--git-common-dir")
    except subprocess.CalledProcessError:
        common_dir = _git_path("--git-common-dir")
        if not common_dir.is_absolute():
            common_dir = (_git_path("--show-toplevel") / common_dir).resolve()
    lease_dir = common_dir / "host-global-leases"
    lease_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return lease_dir / f"{resource}.lock"


def _write_receipt(fd: int, receipt: dict[str, object]) -> None:
    payload = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, payload)
    os.fsync(fd)


def _read_holder(lock_path: Path) -> dict[str, object] | str:
    try:
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "holder metadata unavailable"


def _emit(receipt: dict[str, object]) -> None:
    print(json.dumps(receipt, sort_keys=True), file=sys.stderr, flush=True)


def run_with_lease(
    *,
    resource: str,
    execution_id: str,
    command: Sequence[str],
    wait_seconds: float = 0,
    poll_seconds: float = 1,
) -> int:
    if not execution_id.strip():
        raise ValueError("execution_id is required")
    if not command:
        raise ValueError("a command is required after --")
    if wait_seconds < 0:
        raise ValueError("wait_seconds must be >= 0")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be > 0")

    forwarded_signals = {signal.SIGINT, signal.SIGTERM}
    previous_signal_mask = signal.pthread_sigmask(signal.SIG_BLOCK, forwarded_signals)
    started = time.monotonic()
    lock_path = repo_common_lock_path(resource)
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    parent_ready_read_fd, parent_ready_write_fd = os.pipe()
    read_fd, write_fd = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:
        os.close(parent_ready_write_fd)
        os.setsid()
        os.close(read_fd)
        _acquire_and_exec(
            lock_path=lock_path,
            lock_fd=lock_fd,
            resource=resource,
            execution_id=execution_id,
            command=command,
            wait_seconds=wait_seconds,
            poll_seconds=poll_seconds,
            started=started,
            status_fd=write_fd,
            inherited_signal_mask=previous_signal_mask,
            parent_ready_fd=parent_ready_read_fd,
        )
        os._exit(127)

    os.close(parent_ready_read_fd)
    os.close(write_fd)
    os.write(parent_ready_write_fd, b"1")
    os.close(parent_ready_write_fd)
    command_status: dict[str, object] | None = None
    command_complete: dict[str, object] | None = None
    status: dict[str, object] = {
        "event": "host_lease_command_error",
        "execution_id": execution_id,
        "resource": resource,
        "error": "lease child exited before reporting status",
    }
    first_status_seen = False
    try:
        with os.fdopen(read_fd, encoding="utf-8") as status_stream:
            while True:
                pending_signals = signal.sigpending() & forwarded_signals
                for pending_signal in pending_signals:
                    delivered_signal = signal.sigwait({pending_signal})
                    try:
                        os.kill(child_pid, delivered_signal)
                    except ProcessLookupError:
                        pass
                    _emit(
                        {
                            "event": "host_lease_signal_forwarded",
                            "execution_id": execution_id,
                            "resource": resource,
                            "signal": delivered_signal,
                        }
                    )
                readable, _, _ = select.select([status_stream], [], [], 0.1)
                if not readable:
                    continue
                raw_child_status = status_stream.readline()
                if not raw_child_status:
                    break
                child_status = json.loads(raw_child_status)
                if child_status.get("event") == "host_lease_waiting":
                    _emit(child_status)
                elif not first_status_seen:
                    status = child_status
                    first_status_seen = True
                    _emit(status)
                elif child_status.get("event") == "host_lease_command_started":
                    command_status = child_status
                    _emit(child_status)
                elif child_status.get("event") == "host_lease_command_complete":
                    command_complete = child_status
            if not first_status_seen:
                _emit(status)
        _, wait_status = os.waitpid(child_pid, 0)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_signal_mask)
    return_code = os.waitstatus_to_exitcode(wait_status)
    if return_code < 0:
        return_code = 128 + abs(return_code)
    if status.get("event") != "host_lease_acquired":
        os.close(lock_fd)
        return return_code

    if command_complete is None:
        command_group_terminated = True
        if command_status is not None:
            command_group_terminated = _terminate_process_group(int(command_status["command_pgid"]))
        os.close(lock_fd)
        _emit(
            {
                "acquired_at": status["acquired_at"],
                "duration_seconds": round(time.monotonic() - started, 3),
                "event": "host_lease_recovered_after_supervisor_exit",
                "execution_id": execution_id,
                "command_group_terminated": command_group_terminated,
                "released_at": _utc_now(),
                "resource": resource,
                "return_code": return_code,
            }
        )
        return return_code

    os.close(lock_fd)
    _emit(
        {
            **command_complete,
            "event": "host_lease_released",
            "released_at": _utc_now(),
        }
    )
    return return_code


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process_group(pgid: int) -> bool:
    """Fail closed until a crashed supervisor's command group is gone."""

    for signum, grace_seconds in ((signal.SIGTERM, 1.0), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(pgid, signum)
        except ProcessLookupError:
            return True
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            if not _process_group_exists(pgid):
                return True
            time.sleep(0.02)
    while _process_group_exists(pgid):
        time.sleep(0.1)
    return True


def _report_to_parent(
    status_fd: int, receipt: dict[str, object], *, close: bool = False
) -> bool:
    payload = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    try:
        os.write(status_fd, payload)
    except BrokenPipeError:
        return False
    finally:
        if close:
            os.close(status_fd)
    return True


def _acquire_and_exec(
    *,
    lock_path: Path,
    lock_fd: int,
    resource: str,
    execution_id: str,
    command: Sequence[str],
    wait_seconds: float,
    poll_seconds: float,
    started: float,
    status_fd: int,
    inherited_signal_mask: set[signal.Signals],
    parent_ready_fd: int,
) -> None:
    command_pid: int | None = None
    pending_signals: list[int] = []

    def forward_signal(signum: int, _frame: object) -> None:
        if command_pid is None:
            pending_signals.append(signum)
            return
        try:
            os.killpg(command_pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, forward_signal)
    signal.pthread_sigmask(signal.SIG_SETMASK, inherited_signal_mask)
    parent_ready = os.read(parent_ready_fd, 1)
    os.close(parent_ready_fd)
    if parent_ready != b"1":
        os.close(lock_fd)
        os.close(status_fd)
        os._exit(125)

    def cancel_if_pending() -> None:
        if not pending_signals:
            return
        cancellation_signal = pending_signals[0]
        os.close(lock_fd)
        _report_to_parent(
            status_fd,
            {
                "event": "host_lease_cancelled",
                "execution_id": execution_id,
                "resource": resource,
                "signal": cancellation_signal,
                "waited_seconds": round(time.monotonic() - started, 3),
            },
            close=True,
        )
        os._exit(128 + cancellation_signal)

    waiting_reported = False
    while True:
        cancel_if_pending()
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            cancel_if_pending()
            if not waiting_reported:
                waiting_receipt: dict[str, object] = {
                    "event": "host_lease_waiting",
                    "execution_id": execution_id,
                    "resource": resource,
                    "supervisor_pgid": os.getpgrp(),
                    "supervisor_pid": os.getpid(),
                }
                if not _report_to_parent(status_fd, waiting_receipt):
                    os.close(lock_fd)
                    os.close(status_fd)
                    os._exit(125)
                waiting_reported = True
            elapsed = time.monotonic() - started
            if elapsed >= wait_seconds:
                _report_to_parent(
                    status_fd,
                    {
                        "event": "host_lease_busy",
                        "execution_id": execution_id,
                        "holder": _read_holder(lock_path),
                        "resource": resource,
                        "waited_seconds": round(elapsed, 3),
                    },
                )
                os.close(lock_fd)
                os._exit(_TEMPFAIL)
            time.sleep(min(poll_seconds, wait_seconds - elapsed, 0.1))

    cancel_if_pending()

    acquired_at = _utc_now()
    held_receipt: dict[str, object] = {
        "acquired_at": acquired_at,
        "command": list(command),
        "event": "host_lease_acquired",
        "execution_id": execution_id,
        "pid": os.getpid(),
        "resource": resource,
        "worktree": str(_git_path("--show-toplevel")),
    }
    _write_receipt(lock_fd, held_receipt)
    if not _report_to_parent(status_fd, held_receipt):
        os.close(lock_fd)
        os.close(status_fd)
        os._exit(125)

    command_pid, start_fd = _spawn_gated_command(
        command=command,
        lock_fd=lock_fd,
        status_fd=status_fd,
    )
    _report_to_parent(
        status_fd,
        {
            "event": "host_lease_command_started",
            "execution_id": execution_id,
            "command_pgid": command_pid,
            "resource": resource,
        },
    )
    for pending_signal in pending_signals:
        try:
            os.killpg(command_pid, pending_signal)
        except ProcessLookupError:
            break
    try:
        os.write(start_fd, b"1")
    except BrokenPipeError:
        pass
    finally:
        os.close(start_fd)
    while True:
        waited_pid, command_wait_status = os.waitpid(command_pid, os.WNOHANG)
        if waited_pid == command_pid:
            break
        time.sleep(0.05)
    command_return_code = os.waitstatus_to_exitcode(command_wait_status)

    if command_return_code < 0:
        command_return_code = 128 + abs(command_return_code)
    os.close(lock_fd)
    _report_to_parent(
        status_fd,
        {
            "acquired_at": acquired_at,
            "duration_seconds": round(time.monotonic() - started, 3),
            "event": "host_lease_command_complete",
            "execution_id": execution_id,
            "resource": resource,
            "return_code": command_return_code,
        },
        close=True,
    )
    os._exit(command_return_code)


def _spawn_gated_command(
    *, command: Sequence[str], lock_fd: int, status_fd: int
) -> tuple[int, int]:
    """Create a stopped command group and return only after its PGID is stable."""

    ready_read_fd, ready_write_fd = os.pipe()
    start_read_fd, start_write_fd = os.pipe()
    command_pid = os.fork()
    if command_pid == 0:
        os.close(ready_read_fd)
        os.close(start_write_fd)
        os.close(lock_fd)
        os.close(status_fd)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        os.setsid()
        os.write(ready_write_fd, b"1")
        os.close(ready_write_fd)
        start_token = os.read(start_read_fd, 1)
        os.close(start_read_fd)
        if start_token != b"1":
            os._exit(125)
        try:
            os.execvp(command[0], list(command))
        except FileNotFoundError:
            os._exit(127)
        except OSError:
            os._exit(126)

    os.close(ready_write_fd)
    os.close(start_read_fd)
    ready = os.read(ready_read_fd, 1)
    os.close(ready_read_fd)
    if ready != b"1":
        os.close(start_write_fd)
        os.waitpid(command_pid, 0)
        raise RuntimeError("command child exited before establishing its process group")
    return command_pid, start_write_fd


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--wait-seconds", type=float, default=0)
    parser.add_argument("--poll-seconds", type=float, default=1)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        return run_with_lease(
            resource=args.resource,
            execution_id=args.execution_id,
            command=command,
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (ValueError, subprocess.CalledProcessError) as exc:
        _emit({"event": "host_lease_input_error", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
