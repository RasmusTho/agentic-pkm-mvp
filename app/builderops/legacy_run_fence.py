"""Scoped host fence for a coordinated, stopped legacy factory run.

The operator must separately establish the post-run reboot, restart-route state,
predecessor identity and absence of new manual starts for the whole transition.
This checks only the named factory/service/watcher CLI processes, not arbitrary Python.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path
import shlex
import stat
import subprocess
from typing import Iterator

from app.builderops import openhands_service as service


QUALIFIED_STATE_ROOT = Path("/Volumes/ColimaT7/builder-openhands-6600/runs")


class RunFenceError(ValueError):
    """The scoped run cannot be excluded from concurrent execution."""


def _option(args: list[str], name: str) -> str | None:
    values = [a.split('=', 1)[1] for a in args if a.startswith(name + '=')]
    values += [args[i + 1] for i, a in enumerate(args[:-1]) if a == name]
    return values[0] if len(values) == 1 else None


def _check_processes(issue: int, state_root: Path, server: Path) -> None:
    # pgrep limits readback to these named entrypoints; ps reads only matching PIDs.
    for module in ('openhands_factory', 'openhands_service', 'openhands_watcher'):
        try:
            found = subprocess.run(['pgrep', '-f', module], capture_output=True, text=True, timeout=5, check=False)
            if found.returncode not in (0, 1):
                raise RunFenceError('scoped process search unavailable')
            pids = [int(pid) for pid in found.stdout.split()]
            for pid in pids:
                if pid == os.getpid():
                    continue
                observed = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'command='],
                                          capture_output=True, text=True, timeout=5, check=False)
                if observed.returncode or not observed.stdout.strip():
                    raise RunFenceError('scoped process changed during readback')
                args = shlex.split(observed.stdout.strip())
                indexes = [i for i, arg in enumerate(args) if arg in (f'app.builderops.{module}', f'{module}.py')
                           or arg.endswith('/' + module + '.py')]
                if len(indexes) != 1:
                    raise RunFenceError('scoped process identity is ambiguous')
                args = args[indexes[0] + 1:]
                if module == 'openhands_factory':
                    root, number = _option(args, '--state-root'), _option(args, '--issue')
                    if root is None or number is None or not Path(root).is_absolute() or not number.isdigit():
                        raise RunFenceError('factory process target is ambiguous')
                    if Path(root).resolve() == state_root and int(number) == issue:
                        raise RunFenceError('target factory process is active or queued')
                elif module == 'openhands_watcher':
                    if (len(args) != 5 or not Path(args[1]).is_absolute()
                            or not args[2].isdigit()):
                        raise RunFenceError('watcher process target is ambiguous')
                    target = Path(args[1]).resolve()
                    if target == state_root / f'issue-{issue}' or int(args[2]) == issue:
                        raise RunFenceError('target watcher process is active or pending')
                else:
                    directory = _option(args, '--state-dir')
                    if directory is None or not Path(directory).is_absolute():
                        raise RunFenceError('service process target is ambiguous')
                    if Path(directory).resolve() == server:
                        raise RunFenceError('target server process is active or queued')
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            if isinstance(exc, RunFenceError):
                raise
            raise RunFenceError('scoped process readback unavailable') from exc


def check_locked(*, state_root: Path, issue: int, worktree: Path) -> None:
    root = state_root.resolve(strict=True)
    directory = root / f"issue-{issue}"
    server = directory / "server"
    state = service._read(directory)
    server_state = service._read(server)
    if (not isinstance(state, dict) or state.get("issue") != issue
            or state.get("worktree") != str(worktree) or not isinstance(server_state, dict)
            or service._status(server_state) != "stopped"):
        raise RunFenceError("recorded run or server is not stopped and target-bound")
    _check_processes(issue, root, server)


@contextlib.contextmanager
def hold(*, state_root: Path, issue: int, worktree: Path) -> Iterator[None]:
    """Hold existing run locks; refuse absent/ambiguous host evidence or contention."""
    if not state_root.is_absolute() or issue not in (6597, 6601):
        raise RunFenceError('run is outside the qualified legacy scope')
    try:
        root = state_root.resolve(strict=True)
        if root != QUALIFIED_STATE_ROOT.resolve(strict=True):
            raise RunFenceError('run state root does not match the qualified host run')
        directory = root / f'issue-{issue}'
        server = directory / 'server'
        watcher = directory / 'watcher'
        with contextlib.ExitStack() as stack:
            for path in ([watcher / 'watch.lock'] if watcher.exists() else []) + [directory / 'service.lock', server / 'service.lock']:
                fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
                stack.callback(os.close, fd)
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise RunFenceError('run lock is not a regular file')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            check_locked(state_root=root, issue=issue, worktree=worktree)
            yield
    except (OSError, service.ServiceError) as exc:
        raise RunFenceError('run lock or state unavailable or busy') from exc
