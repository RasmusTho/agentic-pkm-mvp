import fcntl
import json
import subprocess
from pathlib import Path

import pytest

from app.builderops import legacy_run_fence as fence


def _run(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    root = tmp_path / 'runs'
    directory = root / 'issue-6597'
    server = directory / 'server'
    watcher = directory / 'watcher'
    server.mkdir(parents=True)
    watcher.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    monkeypatch.setattr(fence, "QUALIFIED_STATE_ROOT", root)
    (directory / 'service.json').write_text(json.dumps({'version': 1, 'issue': 6597, 'worktree': str(worktree)}))
    (server / 'service.json').write_text(json.dumps({'version': 1, 'state': 'stopped'}))
    for path in (directory / 'service.lock', server / 'service.lock', watcher / 'watch.lock'):
        path.touch()
    return root, worktree


def test_locks_are_held_in_scope_and_released(tmp_path, monkeypatch):
    root, worktree = _run(tmp_path, monkeypatch)
    monkeypatch.setattr(fence, '_check_processes', lambda *args: None)
    with fence.hold(state_root=root, issue=6597, worktree=worktree):
        for path in (root / 'issue-6597/watcher/watch.lock', root / 'issue-6597/service.lock',
                     root / 'issue-6597/server/service.lock'):
            with path.open('r+') as lock, pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with (root / 'issue-6597/service.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_busy_and_unknown_run_refused(tmp_path, monkeypatch):
    root, worktree = _run(tmp_path, monkeypatch)
    monkeypatch.setattr(fence, '_check_processes', lambda *args: None)
    with (root / 'issue-6597/server/service.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(fence.RunFenceError), fence.hold(state_root=root, issue=6597, worktree=worktree):
            pass
    with pytest.raises(fence.RunFenceError), fence.hold(state_root=root, issue=123, worktree=worktree):
        pass


@pytest.mark.parametrize('command', [
    'python -m app.builderops.openhands_factory --issue=6597 finish --state-root {root}',
    'python -m app.builderops.openhands_factory --state-root {root} start --issue 6597',
    'python -m app.builderops.openhands_service --state-dir {root}/issue-6597/server start',
    'python -m app.builderops.openhands_watcher /install {root}/issue-6597 6597 /repo /worktrees',
])
def test_scoped_active_or_queued_command_refused(tmp_path, monkeypatch, command):
    root, worktree = _run(tmp_path, monkeypatch)
    def run(args, **kwargs):
        del kwargs
        if args[0] == 'pgrep':
            module = args[-1]
            match = module in command
            return subprocess.CompletedProcess(args, 0 if match else 1, '91234\n' if match else '', '')
        return subprocess.CompletedProcess(args, 0, command.format(root=root), '')
    monkeypatch.setattr(fence.subprocess, 'run', run)
    with pytest.raises(fence.RunFenceError), fence.hold(state_root=root, issue=6597, worktree=worktree):
        pass


def test_copied_run_root_is_rejected(tmp_path, monkeypatch):
    root, worktree = _run(tmp_path, monkeypatch)
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.setattr(fence, 'QUALIFIED_STATE_ROOT', other)
    monkeypatch.setattr(fence, '_check_processes', lambda *args: None)
    with pytest.raises(fence.RunFenceError, match='qualified host run'):
        with fence.hold(state_root=root, issue=6597, worktree=worktree):
            pass
