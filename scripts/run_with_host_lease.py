#!/usr/bin/env python3
"""Run one host-global command while holding an atomic repo-common lease."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


_RESOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
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

    started = time.monotonic()
    lock_path = repo_common_lock_path(resource)
    read_fd, write_fd = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:
        os.close(read_fd)
        _acquire_and_exec(
            lock_path=lock_path,
            resource=resource,
            execution_id=execution_id,
            command=command,
            wait_seconds=wait_seconds,
            poll_seconds=poll_seconds,
            started=started,
            status_fd=write_fd,
        )
        os._exit(127)

    os.close(write_fd)
    previous_handlers: dict[signal.Signals, object] = {}

    def forward_signal(signum: int, _frame: object) -> None:
        try:
            os.kill(child_pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, forward_signal)
    terminal_status: dict[str, object] | None = None
    try:
        with os.fdopen(read_fd, encoding="utf-8") as status_stream:
            raw_status = status_stream.readline()
            status = json.loads(raw_status) if raw_status else {
                "event": "host_lease_command_error",
                "execution_id": execution_id,
                "resource": resource,
                "error": "lease child exited before reporting status",
            }
            _emit(status)
            raw_terminal_status = status_stream.readline()
            if raw_terminal_status:
                terminal_status = json.loads(raw_terminal_status)
        _, wait_status = os.waitpid(child_pid, 0)
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)
    return_code = os.waitstatus_to_exitcode(wait_status)
    if return_code < 0:
        return_code = 128 + abs(return_code)
    if status.get("event") != "host_lease_acquired":
        return return_code
    if terminal_status is None:
        terminal_status = {
            "acquired_at": status["acquired_at"],
            "duration_seconds": round(time.monotonic() - started, 3),
            "event": "host_lease_release_unconfirmed",
            "execution_id": execution_id,
            "resource": resource,
            "return_code": return_code,
        }
    _emit(terminal_status)
    return return_code


def _report_to_parent(
    status_fd: int, receipt: dict[str, object], *, close: bool = False
) -> None:
    payload = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    try:
        os.write(status_fd, payload)
    except BrokenPipeError:
        pass
    finally:
        if close:
            os.close(status_fd)


def _acquire_and_exec(
    *,
    lock_path: Path,
    resource: str,
    execution_id: str,
    command: Sequence[str],
    wait_seconds: float,
    poll_seconds: float,
    started: float,
    status_fd: int,
) -> None:
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
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
                os.close(fd)
                os._exit(_TEMPFAIL)
            time.sleep(min(poll_seconds, wait_seconds - elapsed))

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
    _write_receipt(fd, held_receipt)
    _report_to_parent(status_fd, held_receipt)

    command_process: subprocess.Popen[bytes] | None = None

    def forward_signal(signum: int, _frame: object) -> None:
        if command_process is None:
            return
        try:
            os.killpg(command_process.pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, forward_signal)
    try:
        command_process = subprocess.Popen(
            list(command),
            close_fds=True,
            start_new_session=True,
        )
        command_return_code = command_process.wait()
    except FileNotFoundError:
        command_return_code = 127

    if command_return_code < 0:
        command_return_code = 128 + abs(command_return_code)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    _report_to_parent(
        status_fd,
        {
            "acquired_at": acquired_at,
            "duration_seconds": round(time.monotonic() - started, 3),
            "event": "host_lease_released",
            "execution_id": execution_id,
            "released_at": _utc_now(),
            "resource": resource,
            "return_code": command_return_code,
        },
        close=True,
    )
    os._exit(command_return_code)


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
