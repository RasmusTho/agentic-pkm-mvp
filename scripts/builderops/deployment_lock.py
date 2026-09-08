#!/usr/bin/env python3
"""Run one BuilderOps deployment while holding its host-local interlock."""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
import subprocess
import sys
from pathlib import Path


def _open_lock(lock_path: Path, *, create: bool) -> int:
    parent = lock_path.parent
    if create:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_stat = parent.stat()
    if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise PermissionError("deployment interlock directory must be private to its owner")

    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT
    lock_fd = os.open(lock_path, flags, 0o600)
    lock_stat = os.fstat(lock_fd)
    if lock_stat.st_uid != os.getuid() or stat.S_IMODE(lock_stat.st_mode) & 0o077:
        os.close(lock_fd)
        raise PermissionError("deployment interlock file must be private to its owner")
    return lock_fd


def _assert_held(lock_path: Path, lock_fd: int) -> int:
    """Prove that ``lock_fd`` refers to a currently held lock file."""

    try:
        fd_stat = os.fstat(lock_fd)
        probe_fd = _open_lock(lock_path, create=False)
    except (OSError, ValueError) as exc:
        print(f"BuilderOps deployment interlock proof is invalid: {exc}", file=sys.stderr)
        return 75
    try:
        probe_stat = os.fstat(probe_fd)
        if (fd_stat.st_dev, fd_stat.st_ino) != (probe_stat.st_dev, probe_stat.st_ino):
            print(
                "BuilderOps deployment interlock proof references the wrong file",
                file=sys.stderr,
            )
            return 75

        # First prove that the path is already locked.  An unlocked descriptor
        # must not be allowed to acquire the lock as part of its own proof.
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            fcntl.flock(probe_fd, fcntl.LOCK_UN)
            print("BuilderOps deployment interlock is not held", file=sys.stderr)
            return 75

        # Re-acquiring on the inherited open-file description succeeds only
        # for the descriptor that owns the lock.  A separately opened fd for
        # the same inode remains blocked by the other deployment.
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                "BuilderOps deployment interlock descriptor does not own the lock",
                file=sys.stderr,
            )
            return 75
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        fcntl.flock(probe_fd, fcntl.LOCK_UN)
    finally:
        os.close(probe_fd)
    print("BuilderOps deployment interlock is not held", file=sys.stderr)
    return 75


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-path", required=True, type=Path)
    parser.add_argument("--assert-held", action="store_true")
    parser.add_argument("--fd", type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.assert_held:
        if args.command or args.fd is None:
            parser.error("--assert-held requires --fd and no command")
        return _assert_held(args.lock_path, args.fd)
    if not args.command or args.command[0] != "--":
        parser.error("a command is required after --")

    lock_path = args.lock_path
    try:
        lock_fd = _open_lock(lock_path, create=True)
    except OSError as exc:
        print(f"BuilderOps deployment interlock is unavailable: {exc}", file=sys.stderr)
        return 75
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("BuilderOps deployment interlock is busy", file=sys.stderr)
            return 75
        try:
            child_env = os.environ.copy()
            child_env["BUILDEROPS_DEPLOYMENT_LOCK_FD"] = str(lock_fd)
            child_env["BUILDEROPS_DEPLOYMENT_LOCK_PATH"] = str(lock_path)
            return subprocess.run(
                args.command[1:],
                check=False,
                env=child_env,
                pass_fds=(lock_fd,),
            ).returncode
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
