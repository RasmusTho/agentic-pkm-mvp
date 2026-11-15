"""Finished author continuation through the real cycle with isolated external ports."""
import json

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_pr_cycle import HEAD, fetch
from tests.builderops.test_openhands_pr_cycle_repair_author import repair_records, repair_setup

REAL_NATIVE_PROOF = cycle.native_execution_proof


def started(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    first = cycle.advance(layout, config, fetch=fetch, http=server)['results'][1]
    assert first['action'] == 'repair-author'
    record = cycle._mapping(layout, 'reviewer')['conversation']
    server.conversations[record['id']]['execution_status'] = 'finished'
    calls = []
    def proof(layout, worker, op, admission, **kwargs):
        calls.append((op, dict(admission)))
        mapping = cycle._mapping(layout, worker)
        return {'operation_id': op, 'conversation_id': mapping['conversation']['id'],
                'container_id': mapping['container_id'], 'engine': admission['engine'],
                'model': admission['model'], 'source': 'native-session-metadata'}
    monkeypatch.setattr(cycle, 'native_execution_proof', proof)
    return layout, config, server, record, calls


def saved(layout):
    return next(r for r in ew._load_state(layout)['compact_receipts'] if r.get('repair_operation'))


def advance(layout, config, server, fetcher=fetch):
    return cycle.advance(layout, config, fetch=fetcher, http=server)['results'][1]


def test_finished_author_preserved_and_pending_across_restart(tmp_path, monkeypatch):
    layout, config, server, author, calls = started(tmp_path, monkeypatch)
    first = advance(layout, config, server)
    assert first['action'] == 'pending-trusted-publication'
    receipt = saved(layout)
    assert receipt['repair_result']['conversation_id'] == author['id']
    assert receipt['repair_result']['work_at_stop']['checkpoint']['ref'] == 'synthetic-checkpoint'
    assert receipt['repair_stop_intent']['stop_id'] == cycle._mapping(layout, 'reviewer')['stop_id']
    assert receipt['repair_result']['head_sha'] == HEAD
    assert advance(layout, config, server)['action'] == 'pending-trusted-publication'
    assert len(calls) == 1 and len(repair_records(layout)) == 1
    assert len([c for c in server.calls if c[0] == 'POST']) == 2


@pytest.mark.parametrize('status', ['running', 'unknown', None])
def test_unfinished_status_never_stops_or_posts(tmp_path, monkeypatch, status):
    layout, config, server, author, calls = started(tmp_path, monkeypatch)
    server.conversations[author['id']]['execution_status'] = status
    assert advance(layout, config, server)['action'] == 'repair-author'
    assert not calls and 'repair_stop_intent' not in saved(layout)
    assert len([c for c in server.calls if c[0] == 'POST']) == 2


@pytest.mark.parametrize(('code', 'detail', 'failure'), [
    ('ACPAuthRequired', 'authentication required', 'authentication'),
    ('ACPStartupTimeout', 'timeout', 'transient_network'),
    ('LLMContextWindowExceedError', 'too long', 'context_exhausted'),
    ('ACPSpawnError', 'failed', 'task_failure'),
    ('ACPPromptError', 'usage limit reached', 'quota_exhausted'),
])
def test_failure_classification_preserves_work(tmp_path, monkeypatch, code, detail, failure):
    layout, config, server, _, calls = started(tmp_path, monkeypatch)
    server.events = [{'kind': 'ConversationErrorEvent', 'code': code, 'detail': detail}]
    result = advance(layout, config, server)
    assert failure in result['reason'] and saved(layout)['repair_result']['failure_class'] == failure
    assert not calls and 'repair_stop_intent' not in saved(layout)
    assert len([c for c in server.calls if c[0] == 'POST']) == 2


def test_proof_mismatch_does_not_stop(tmp_path, monkeypatch):
    layout, config, server, _, _ = started(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, 'native_execution_proof', lambda *a, **k: {'operation_id': 'other'})
    assert 'native proof' in advance(layout, config, server)['reason']
    assert 'repair_stop_intent' not in saved(layout)


@pytest.mark.parametrize('lost_after_stop', [False, True])
def test_interrupted_stop_resumes_same_intent(tmp_path, monkeypatch, lost_after_stop):
    layout, config, server, author, calls = started(tmp_path, monkeypatch)
    stop = ew.stop_worker
    attempts = []
    def interrupt(layout, worker, **kwargs):
        attempts.append((kwargs['expected_container_id'], kwargs['stop_intent']['stop_id']))
        assert saved(layout)['repair_stop_intent']['stop_id'] == attempts[-1][1]
        if len(attempts) == 1:
            if lost_after_stop:
                stop(layout, worker, **kwargs)
            raise ew.EpicWorkspaceError('synthetic response loss')
        return stop(layout, worker, **kwargs)
    monkeypatch.setattr(ew, 'stop_worker', interrupt)
    assert 'response loss' in advance(layout, config, server)['reason']
    assert advance(layout, config, server)['action'] == 'pending-trusted-publication'
    assert attempts[0] == attempts[1] and attempts[0][0] == 'e' * 64
    assert saved(layout)['repair_result']['conversation_id'] == author['id'] and len(calls) == 1


def test_branch_drift_is_preserved_and_held(tmp_path, monkeypatch):
    layout, config, server, _, _ = started(tmp_path, monkeypatch)
    stop = ew.stop_worker
    def drift(layout, worker, **kwargs):
        stop(layout, worker, **kwargs)
        mapping = cycle._mapping(layout, worker)
        ew._record_worker(layout, 6618, work_at_stop={**mapping['work_at_stop'], 'branch': 'other-branch'})
    monkeypatch.setattr(ew, 'stop_worker', drift)
    result = advance(layout, config, server)
    assert result['action'] == 'wait' and 'branch drift' in result['reason']
    assert saved(layout)['repair_result']['work_at_stop']['checkpoint']['ref'] == 'synthetic-checkpoint'
    assert saved(layout)['repair_result']['status'] == 'stopped'


def test_owner_and_head_changes_do_not_publish(tmp_path, monkeypatch):
    layout, config, server, _, _ = started(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, lifecycle_owner='other')
    assert 'owner changed' in advance(layout, config, server)['reason']
    assert saved(layout)['repair_result']['status'] == 'stopped'
    def changed_fetch(path, timeout):
        code, body = fetch(path, timeout)
        if path.endswith('/pulls/10'):
            row = json.loads(body)
            row['head']['sha'] = 'b' * 40
            body = json.dumps(row).encode()
        return code, body
    assert advance(layout, config, server, changed_fetch)['reason'] == 'not admitted at this head'
    assert len([c for c in server.calls if c[0] == 'POST']) == 2


@pytest.mark.parametrize('login_ok', [True, False])
def test_actual_native_proof_is_consumed_before_stop(tmp_path, monkeypatch, login_ok):
    layout, config, server, author, _ = started(tmp_path, monkeypatch)
    cid = author['id']
    image = 'worker@sha256:' + 'c' * 64
    ew._record_worker(layout, 6618, credentials={'codex': 'chatgpt-login-dir'})
    server.conversations[cid].update(
        agent={'kind': 'ACPAgent', 'acp_server': 'codex', 'acp_model': 'gpt-6.1-terra'},
        agent_state={'acp_session_id': 'native-session', 'acp_session_cwd': '/workspace'},
        current_model_id='gpt-6.1-terra', current_effort='ultra',
        available_efforts=[{'value': 'ultra'}])
    def command(argv, *, timeout):
        if argv[1] == 'inspect':
            body = [{'Id': 'e' * 64, 'Image': 'sha256:image',
                     'Config': {'Image': image, 'Env': []}}]
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps(body), '')
        if argv[1:3] == ['image', 'inspect']:
            return cycle.subprocess.CompletedProcess(argv, 0, '[{"Id":"sha256:image"}]', '')
        if argv[-3:] == [cycle.CODEX_CLI, 'login', 'status']:
            return cycle.subprocess.CompletedProcess(argv, 0, 'Logged in using ChatGPT' if login_ok else 'no login', '')
        if len(argv) > 7 and argv[-2:] == ['codex', cid]:
            evidence = {'engine': 'codex', 'conversation_id': cid, 'session_id': 'native-session',
                        'model': 'gpt-6.1-terra', 'effort': 'ultra', 'timestamp': '2026-11-15T00:00:00Z'}
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps(evidence), '')
        return cycle.subprocess.CompletedProcess(argv, 0, 'route-ok\n', '')
    monkeypatch.setattr(cycle, '_command', command)
    monkeypatch.setattr(cycle, 'native_execution_proof', REAL_NATIVE_PROOF)
    stop = ew.stop_worker
    def checked_stop(layout, worker, **kwargs):
        assert saved(layout)['repair_execution_proof']['native_session_id'] == 'native-session'
        assert saved(layout)['repair_stop_intent']['container_id'] == 'e' * 64
        return stop(layout, worker, **kwargs)
    monkeypatch.setattr(ew, 'stop_worker', checked_stop)
    result = advance(layout, config, server)
    if login_ok:
        assert result['action'] == 'pending-trusted-publication'
        assert saved(layout)['repair_execution_proof']['native_session_id'] == 'native-session'
        assert saved(layout)['repair_execution_proof']['effort'] == 'ultra'
    else:
        assert 'authentication not verified' in result['reason']
        assert 'repair_stop_intent' not in saved(layout)


def test_unknown_publication_preserves_stopped_source(tmp_path, monkeypatch):
    layout, config, server, _, _ = started(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, publication_ops=[{'id': 'branch_push-1', 'kind': 'branch_push',
                                                      'branch': 'codex/example', 'status': 'intended'}])
    result = advance(layout, config, server)
    assert result['action'] == 'wait' and 'publication remains unresolved' in result['reason']
    assert saved(layout)['repair_result']['status'] == 'stopped'
    assert saved(layout)['repair_result']['work_at_stop']['checkpoint']['ref'] == 'synthetic-checkpoint'


def test_changed_owner_is_held_while_other_pr_advances(tmp_path, monkeypatch):
    layout, config, server, _, _ = started(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, lifecycle_owner='other')
    ew._reserve_worker(layout, 6619, 'peer', state='running', runtime='openhands', port=18701,
                       container_id='f' * 64)
    config.insert(0, {**config[0], 'number': 9, 'worker': 'peer'})
    def peer_fetch(path, timeout):
        if '/issues/6619' in path:
            return 200, json.dumps({'number': 6619, 'state': 'open', 'body': 'Peer contract'}).encode()
        status, body = fetch(path, timeout)
        if path.endswith('/pulls/9'):
            row = json.loads(body)
            row.update(draft=False, body='Governing-Issue: #6619')
            body = json.dumps(row).encode()
        return status, body
    monkeypatch.setattr(cycle, 'start_or_reconcile_review', lambda *args, **kwargs:
                        {'id': 'synthetic-peer', 'status': 'created'})
    results = cycle.advance(layout, config, fetch=peer_fetch, http=server)['results']
    assert results[0]['action'] == 'independent-review'
    assert results[1]['action'] == 'wait' and 'owner changed' in results[1]['reason']
    assert saved(layout)['repair_result']['status'] == 'stopped'


def test_advance_real_stop_preserves_drift_and_unpublished_fixture(tmp_path, monkeypatch):
    import subprocess

    from tests.builderops.test_epic_workspace_isolation import _seed_repo
    from tests.builderops.test_epic_workspace_lifecycle import GIT_ENV, _git

    layout, config, server, _, _ = started(tmp_path, monkeypatch)
    checkout = layout.checkout('reviewer')
    origin = _seed_repo(tmp_path)
    subprocess.run(['git', 'clone', '--quiet', '--bare', origin, str(layout.source)], check=True, env=GIT_ENV)
    subprocess.run(['git', 'clone', '--quiet', origin, str(checkout)], check=True, env=GIT_ENV)
    _git(checkout, 'checkout', '--quiet', '-b', 'drifted')
    (checkout / 'unique.txt').write_text('unpublished change\n')
    (checkout / '.gitignore').write_text('ignored.txt\n')
    (checkout / 'ignored.txt').write_text('ignored content\n')
    engine = cycle._worker_runner
    def stop(layout, worker, **kwargs):
        return ew._stop_worker(layout, worker, runner=engine, image=ew.DEFAULT_IMAGE, **kwargs)
    def absent(layout, worker, mapping):
        assert mapping['state'] == 'stopped_verified'
        assert ew._container_state(layout, worker, engine) is None
    monkeypatch.setattr(ew, 'stop_worker', stop)
    monkeypatch.setattr(cycle, '_assert_stopped', absent)
    result = advance(layout, config, server)
    assert result['action'] == 'wait' and 'branch drift' in result['reason'], result
    work = saved(layout)['repair_result']['work_at_stop']
    assert work['branch'] == 'drifted' and work['checkpoint']['ref']
    assert (checkout / 'unique.txt').read_text() == 'unpublished change\n'
    assert (checkout / 'ignored.txt').read_text() == 'ignored content\n'
    assert 'ignored.txt' in work['ignored_paths'] and 'reviewer' not in engine.containers
