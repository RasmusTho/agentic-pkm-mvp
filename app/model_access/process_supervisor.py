"""Small stdlib-only guardian for one bounded Codex CLI process tree.

This module is launched as an isolated Python script by ``codex_cli``. It stays
alive if the request-owning process dies, and uses parent/caller-liveness pipes
plus its own deadline to terminate the CLI process group.
"""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import resource
import select
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Any


_MAX_STAGED_EXECUTABLE_BYTES = 256 * 1024 * 1024
_MAX_COPY_FALLBACK_BYTES = 16 * 1024 * 1024
_CHILD_REAP_GRACE_SECONDS = 1.0
_FICLONE = 0x40049409


def _write_status(fd: int, status: dict[str, Any]) -> bool:
    try:
        payload = json.dumps(status, separators=(",", ":")).encode("utf-8") + b"\n"
        bounded_payload = payload[:4096]
        return os.write(fd, bounded_payload) == len(bounded_payload)
    except OSError:
        return False


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


def _kill_child_and_group(pid: int) -> None:
    """Kill the owned group and its leader, including before setsid succeeds."""
    _kill_group(pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _reap(pid: int) -> int | None:
    try:
        waited, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return 0
    if waited == 0:
        return None
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return -os.WTERMSIG(status)
    return 1


def _reap_bounded(pid: int, timeout_seconds: float = _CHILD_REAP_GRACE_SECONDS) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _reap(pid) is not None:
            return
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))


def _liveness_fds(args: argparse.Namespace) -> list[int]:
    fds = [args.parent_fd]
    if args.caller_liveness_fd >= 0:
        fds.append(args.caller_liveness_fd)
    return fds


def _liveness_lost(fds: list[int]) -> bool:
    readable, _, _ = select.select(fds, [], [], 0)
    return bool(readable)


def _identity_from_stat(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _clone_or_copy_descriptor(
    fd: int,
    expected_identity: tuple[int, int, int, int, int],
    destination: Path,
) -> None:
    """Create a private executable snapshot without modifying the source inode."""
    before = os.fstat(fd)
    if (
        _identity_from_stat(before) != expected_identity
        or not stat.S_ISREG(before.st_mode)
        or not before.st_mode & 0o111
        or before.st_size <= 0
        or before.st_size > _MAX_STAGED_EXECUTABLE_BYTES
    ):
        raise ValueError("executable identity or size is unsupported")

    output_fd: int | None = None
    try:
        if sys.platform == "darwin":
            clone_function = ctypes.CDLL(None, use_errno=True).fclonefileat
            clone_function.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint32,
            ]
            clone_function.restype = ctypes.c_int
            destination_directory_fd = os.open(
                destination.parent,
                os.O_RDONLY,
            )
            try:
                result = clone_function(
                    fd,
                    destination_directory_fd,
                    os.fsencode(destination.name),
                    0,
                )
            finally:
                os.close(destination_directory_fd)
            if result != 0:
                error_number = ctypes.get_errno()
                raise OSError(
                    error_number,
                    os.strerror(error_number),
                    str(destination),
                )
        else:
            output_fd = os.open(
                destination,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o700,
            )
            try:
                fcntl.ioctl(output_fd, _FICLONE, fd)
            except OSError:
                if before.st_size > _MAX_COPY_FALLBACK_BYTES:
                    raise
                os.ftruncate(output_fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                copied = 0
                while copied < before.st_size:
                    chunk = os.read(fd, min(1024 * 1024, before.st_size - copied))
                    if not chunk:
                        raise ValueError("executable changed while being staged")
                    view = memoryview(chunk)
                    while view:
                        written = os.write(output_fd, view)
                        if written <= 0:
                            raise OSError("executable staging write made no progress")
                        view = view[written:]
                    copied += len(chunk)
            os.fsync(output_fd)

        if _identity_from_stat(os.fstat(fd)) != expected_identity:
            raise ValueError("executable changed while being staged")
        os.utime(
            destination,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )
        snapshot_stat = destination.stat()
        if (
            not stat.S_ISREG(snapshot_stat.st_mode)
            or snapshot_stat.st_size != before.st_size
            or snapshot_stat.st_mtime_ns != before.st_mtime_ns
            or not snapshot_stat.st_mode & 0o111
        ):
            raise ValueError("executable snapshot metadata is inconsistent")
        mode = (stat.S_IMODE(before.st_mode) & 0o555) | 0o500
        os.chmod(destination, mode)
    except BaseException:
        try:
            os.unlink(destination)
        except OSError:
            pass
        raise
    finally:
        if output_fd is not None:
            os.close(output_fd)


def _remove_staged_executable(executable: Path) -> None:
    try:
        executable.unlink()
    except OSError:
        pass


def _run(args: argparse.Namespace) -> int:
    command = list(args.command)
    if not command or os.name != "posix" or not hasattr(os, "fork"):
        _write_status(args.status_fd, {"kind": "unsupported"})
        return 0
    if args.caller_liveness_fd < -1 or args.caller_liveness_fd in {
        args.parent_fd,
        args.status_fd,
    }:
        _write_status(args.status_fd, {"kind": "unsupported"})
        return 0
    if args.caller_liveness_fd >= 0:
        try:
            caller_pipe = os.fstat(args.caller_liveness_fd)
        except OSError:
            _write_status(args.status_fd, {"kind": "unsupported"})
            return 0
        if not stat.S_ISFIFO(caller_pipe.st_mode):
            _write_status(args.status_fd, {"kind": "unsupported"})
            return 0

    try:
        expected = tuple(json.loads(args.expected_identity))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        executable_fd = os.open(command[0], flags)
        opened = os.fstat(executable_fd)
        if _identity_from_stat(opened) != expected:
            os.close(executable_fd)
            _write_status(args.status_fd, {"kind": "identity_mismatch"})
            return 0
        if not stat.S_ISREG(opened.st_mode) or not opened.st_mode & 0o111:
            os.close(executable_fd)
            _write_status(args.status_fd, {"kind": "unsupported"})
            return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        _write_status(args.status_fd, {"kind": "unsupported"})
        return 0

    source_path = Path(command[0])
    staged_executable = Path(args.staging_path)
    try:
        stage_metadata = os.stat(source_path.parent)
        if (
            not stat.S_ISDIR(stage_metadata.st_mode)
            or stat.S_IMODE(stage_metadata.st_mode) & 0o022
            or staged_executable.parent != source_path.parent
            or not staged_executable.name.startswith(
                f".{source_path.name}.model-access-"
            )
        ):
            raise OSError("executable snapshot path is outside the CLI install bin")
        _clone_or_copy_descriptor(executable_fd, expected, staged_executable)
    except ValueError:
        os.close(executable_fd)
        _remove_staged_executable(staged_executable)
        _write_status(args.status_fd, {"kind": "identity_mismatch"})
        return 0
    except OSError:
        os.close(executable_fd)
        _remove_staged_executable(staged_executable)
        _write_status(args.status_fd, {"kind": "unsupported"})
        return 0
    os.close(executable_fd)

    if args.file_limit:
        if not hasattr(resource, "RLIMIT_FSIZE"):
            _remove_staged_executable(staged_executable)
            _write_status(args.status_fd, {"kind": "limit_unavailable"})
            return 0
        try:
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (args.file_limit, args.file_limit),
            )
        except (OSError, ValueError):
            _remove_staged_executable(staged_executable)
            _write_status(args.status_fd, {"kind": "limit_unavailable"})
            return 0

    deadline = time.monotonic() + max(1, args.timeout_ms) / 1000
    start_read_fd, start_write_fd = os.pipe()
    try:
        ready_read_fd, ready_write_fd = os.pipe()
    except OSError:
        os.close(start_read_fd)
        os.close(start_write_fd)
        _remove_staged_executable(staged_executable)
        _write_status(args.status_fd, {"kind": "unsupported"})
        return 0
    try:
        child_pid = os.fork()
    except OSError:
        os.close(start_read_fd)
        os.close(start_write_fd)
        os.close(ready_read_fd)
        os.close(ready_write_fd)
        _remove_staged_executable(staged_executable)
        _write_status(args.status_fd, {"kind": "unsupported"})
        return 0

    if child_pid == 0:
        try:
            os.close(start_write_fd)
            os.close(ready_read_fd)
            os.setsid()
            if os.write(ready_write_fd, b"\x01") != 1:
                os._exit(127)
            os.close(ready_write_fd)
            if os.read(start_read_fd, 1) != b"\x01":
                os._exit(127)
            os.close(start_read_fd)
            for fd in (
                args.parent_fd,
                args.caller_liveness_fd,
                args.status_fd,
            ):
                if fd < 0:
                    continue
                try:
                    os.close(fd)
                except OSError:
                    pass
            os.execve(str(staged_executable), command, os.environ)
        except BaseException:
            os._exit(127)

    os.close(start_read_fd)
    start_read_fd = -1
    os.close(ready_write_fd)
    ready_write_fd = -1
    liveness_fds = _liveness_fds(args)
    try:
        # Do not announce or release the CLI until the child has successfully
        # created its session/process group. Watch both cancellation channels
        # during this handshake so cancellation cannot be lost in the fork to
        # setsid window.
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_child_and_group(child_pid)
                _reap_bounded(child_pid)
                _write_status(args.status_fd, {"kind": "timeout"})
                return 0
            if _liveness_lost(liveness_fds):
                _kill_child_and_group(child_pid)
                _reap_bounded(child_pid)
                _write_status(args.status_fd, {"kind": "parent_lost"})
                return 0
            readable, _, _ = select.select(
                [ready_read_fd, *liveness_fds], [], [], min(remaining, 0.05)
            )
            if any(fd in liveness_fds for fd in readable):
                _kill_child_and_group(child_pid)
                _reap_bounded(child_pid)
                _write_status(args.status_fd, {"kind": "parent_lost"})
                return 0
            if ready_read_fd in readable:
                ready = os.read(ready_read_fd, 1)
                if ready != b"\x01":
                    _kill_child_and_group(child_pid)
                    _reap_bounded(child_pid)
                    _write_status(args.status_fd, {"kind": "unsupported"})
                    return 0
                break
        os.close(ready_read_fd)
        ready_read_fd = -1

        # Check cancellation again at the release boundary. Once released, the
        # group is known to exist; later cancellation kills both its group and
        # leader, so a missed group signal cannot strand the pre-exec child.
        if _liveness_lost(liveness_fds):
            _kill_child_and_group(child_pid)
            _reap_bounded(child_pid)
            _write_status(args.status_fd, {"kind": "parent_lost"})
            return 0
        if not _write_status(
            args.status_fd,
            {"kind": "started", "process_group": child_pid},
        ):
            _kill_child_and_group(child_pid)
            _reap_bounded(child_pid)
            return 0
        if _liveness_lost(liveness_fds):
            _kill_child_and_group(child_pid)
            _reap_bounded(child_pid)
            _write_status(args.status_fd, {"kind": "parent_lost"})
            return 0
        try:
            os.write(start_write_fd, b"\x01")
        except OSError:
            _kill_child_and_group(child_pid)
            _reap_bounded(child_pid)
            return 0
        os.close(start_write_fd)
        start_write_fd = -1

        while True:
            returncode = _reap(child_pid)
            if returncode is not None:
                # A CLI child may exit while descendants still hold the output
                # pipes. Reap the leader, then close its owned process group.
                _kill_group(child_pid)
                _write_status(
                    args.status_fd,
                    {"kind": "completed", "returncode": returncode},
                )
                return 0

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_child_and_group(child_pid)
                _reap_bounded(child_pid)
                _write_status(args.status_fd, {"kind": "timeout"})
                return 0

            readable, _, _ = select.select(
                liveness_fds, [], [], min(remaining, 0.05)
            )
            if readable:
                _kill_child_and_group(child_pid)
                _reap_bounded(child_pid)
                _write_status(args.status_fd, {"kind": "parent_lost"})
                return 0
    finally:
        for fd in (
            start_read_fd,
            start_write_fd,
            ready_read_fd,
            ready_write_fd,
        ):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        for fd in (
            executable_fd,
            args.parent_fd,
            args.caller_liveness_fd,
            args.status_fd,
        ):
            if fd < 0:
                continue
            try:
                os.close(fd)
            except OSError:
                pass
        _remove_staged_executable(staged_executable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-fd", type=int, required=True)
    parser.add_argument("--caller-liveness-fd", type=int, default=-1)
    parser.add_argument("--status-fd", type=int, required=True)
    parser.add_argument("--timeout-ms", type=int, required=True)
    parser.add_argument("--file-limit", type=int, default=0)
    parser.add_argument("--expected-identity", required=True)
    parser.add_argument("--staging-path", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
