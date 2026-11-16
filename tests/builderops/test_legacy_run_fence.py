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

# Reuse the real Git/SQLite producer fixture while keeping this regression separate.
import importlib.util  # noqa: E402

from app.builderops import legacy_owner_recovery as recovery  # noqa: E402
from scripts import agent_worktree  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    'legacy_successor_fixture', Path(__file__).parents[1] / 'scripts/test_legacy_successor_recovery.py')
assert _spec and _spec.loader
_fixture_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture_module)
operator_case = _fixture_module.operator_case


def test_changed_run_after_ack_stays_unadmitted_then_resume(operator_case, monkeypatch):
    case = operator_case
    read_ack = recovery._read_unique_operator_ack
    server_state = case['run_state_root'] / 'issue-6601/server/service.json'

    def changed_after_ack(**kwargs):
        result = read_ack(**kwargs)
        server_state.write_text(json.dumps({'version': 1, 'state': 'running'}))
        return result

    monkeypatch.setattr(recovery, '_read_unique_operator_ack', changed_after_ack)
    with pytest.raises(recovery.RecoveryEvidenceError, match='not stopped'):
        recovery.execute_operator_pickup(**_fixture_module._args(case))
    assert 2 in case['comments']  # ACK was actually created before the failed fence.
    row = agent_worktree._locked_lifecycle_snapshot(
        agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match='unpinned'):
        agent_worktree.assert_operator_registration_pinned(row)
    server_state.write_text(json.dumps({'version': 1, 'state': 'stopped'}))
    monkeypatch.setattr(recovery, '_read_unique_operator_ack', read_ack)
    result = recovery.resume_operator_pickup(**_fixture_module._args(case))
    assert result['state'] == 'pinned' and result['ack_comment_id'] == 2
    assert len(case['comments']) == 2


def test_lost_ack_reply_remains_prepared_when_resume_fence_fails(operator_case, monkeypatch):
    case = operator_case
    delegate = recovery.subprocess.run
    posts = []

    def lost_reply(args, **kwargs):
        if args[0] == 'gh' and 'POST' in args:
            posts.append(1)
            delegate(args, **kwargs)
            return subprocess.CompletedProcess(args, 1, stdout='', stderr='lost')
        return delegate(args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, 'run', lost_reply)
    with pytest.raises(recovery.RecoveryEvidenceError, match='ACK publication outcome unknown'):
        recovery.execute_operator_pickup(**_fixture_module._args(case))
    calls = []

    def changed(*_args):
        calls.append(1)
        if len(calls) == 2:
            raise fence.RunFenceError('target watcher process is active or pending')

    monkeypatch.setattr(fence, '_check_processes', changed)
    with pytest.raises(recovery.RecoveryEvidenceError, match='active or pending'):
        recovery.resume_operator_pickup(**_fixture_module._args(case))
    row = agent_worktree._locked_lifecycle_snapshot(
        agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match='unpinned'):
        agent_worktree.assert_operator_registration_pinned(row)
    assert row['operator_registration']['state'] == 'prepared' and len(posts) == 1
    monkeypatch.setattr(fence, '_check_processes', lambda *_args: None)
    assert recovery.resume_operator_pickup(**_fixture_module._args(case))['state'] == 'pinned'
    assert len(posts) == 1


def test_resume_after_lost_pinned_reply_is_read_only(operator_case, monkeypatch):
    case = operator_case
    result = recovery.execute_operator_pickup(**_fixture_module._args(case))
    # The successful response is discarded; resume must reconstruct it from readbacks.
    delegate = recovery.subprocess.run

    def no_writes(args, **kwargs):
        assert not (args[0] == 'gh' and 'POST' in args)
        assert not ('app.dispatcher' in args and 'claim' in args)
        return delegate(args, **kwargs)

    def no_pin(*_args, **_kwargs):
        raise AssertionError('resume must not pin again')

    monkeypatch.setattr(recovery.subprocess, 'run', no_writes)
    monkeypatch.setattr(agent_worktree, 'pin_operator_registration', no_pin)
    monkeypatch.setattr(agent_worktree, 'begin_operator_ack', no_pin)
    resumed = recovery.resume_operator_pickup(**_fixture_module._args(case))
    assert resumed['pickup_receipt'] == result['pickup_receipt']
    assert resumed['registration_epoch'] == result['registration_epoch']
    assert resumed['ack_comment_id'] == result['ack_comment_id']


@pytest.mark.parametrize('drift', ['ack', 'lease', 'state'])
def test_pinned_resume_refuses_changed_readbacks(operator_case, monkeypatch, drift):
    from app.dispatcher import leases

    case = operator_case
    result = recovery.execute_operator_pickup(**_fixture_module._args(case))
    if drift == 'ack':
        case['comments'][2]['body'] += ' '
    elif drift == 'lease':
        leases.release(case['store'], result['task_id'], case['agent'])
    else:
        (case['run_state_root'] / 'issue-6601/server/service.json').write_text(
            json.dumps({'version': 1, 'state': 'running'}))
    monkeypatch.setattr(agent_worktree, 'pin_operator_registration',
                        lambda *_args, **_kwargs: pytest.fail('unexpected pin'))
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.resume_operator_pickup(**_fixture_module._args(case))


@pytest.mark.parametrize('drift', ['body', 'head', 'ref'])
def test_pr_drift_after_ack_stays_prepared_and_resume_never_reposts(operator_case, monkeypatch, drift):
    case = operator_case
    read_ack = recovery._read_unique_operator_ack
    github_read = recovery._github_read
    original_body = case['pr_data']['body']
    original_head = case['pr_data']['head']['sha']

    def drift_after_ack(**kwargs):
        comment = read_ack(**kwargs)
        if drift == 'body':
            case['pr_data']['body'] = original_body + '\nchanged after ACK\n'
        elif drift == 'head':
            case['pr_data']['head']['sha'] = 'f' * 40
        else:
            def changed_ref(args, *, cwd):
                if any('/git/ref/heads/' in arg for arg in args):
                    return json.dumps({'ref': 'refs/heads/codex/example', 'object': {'sha': 'f' * 40}})
                return github_read(args, cwd=cwd)
            monkeypatch.setattr(recovery, '_github_read', changed_ref)
        return comment

    monkeypatch.setattr(recovery, '_read_unique_operator_ack', drift_after_ack)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_fixture_module._args(case))
    row = agent_worktree._locked_lifecycle_snapshot(
        agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert 2 in case['comments'] and row['operator_registration']['state'] == 'prepared'
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match='unpinned'):
        agent_worktree.assert_operator_registration_pinned(row)
    monkeypatch.setattr(recovery, '_read_unique_operator_ack', read_ack)
    case['pr_data']['body'] = original_body
    case['pr_data']['head']['sha'] = original_head
    monkeypatch.setattr(recovery, '_github_read', github_read)
    delegate = recovery.subprocess.run

    def no_post(args, **kwargs):
        assert not (args[0] == 'gh' and 'POST' in args)
        return delegate(args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, 'run', no_post)
    assert recovery.resume_operator_pickup(**_fixture_module._args(case))['state'] == 'pinned'
    assert len(case['comments']) == 2


def test_pinned_readback_refuses_pr_drift_during_ack_readback(operator_case, monkeypatch):
    case = operator_case
    recovery.execute_operator_pickup(**_fixture_module._args(case))
    read_ack = recovery._read_unique_operator_ack

    def drift_after_ack(**kwargs):
        comment = read_ack(**kwargs)
        case['pr_data']['body'] += '\nchanged during readback\n'
        return comment

    monkeypatch.setattr(recovery, '_read_unique_operator_ack', drift_after_ack)
    monkeypatch.setattr(agent_worktree, 'pin_operator_registration',
                        lambda *_args, **_kwargs: pytest.fail('unexpected pin'))
    with pytest.raises(recovery.RecoveryEvidenceError, match='publication changed'):
        recovery.resume_operator_pickup(**_fixture_module._args(case))
