"""Assembled cycle and governed native publisher using synthetic external ports."""
import json

import pytest

from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_native_repair_publisher import HEAD, NEW, prepare


def prepared(tmp_path, monkeypatch, *, parent_scope=False):
    data = prepare(tmp_path, monkeypatch, real_authority=True, parent_scope=parent_scope)
    layout, config, _, _, port, evidence, _, server, collector = data
    config[0]['repair_publication'].update(paths=['feature.txt'], evidence_file=str(evidence))
    path = tmp_path / 'controller-admissions.json'
    path.write_text(json.dumps({'admissions': config, 'other': {'keep': True}}))
    return data, path


def tick(data, path):
    return cycle.advance(data[0], path, fetch=data[8], http=data[7], publisher_executor=data[4])


def admission(path):
    return json.loads(path.read_text())['admissions'][0]


@pytest.mark.parametrize('parent_scope', [False, True])
def test_advance_publishes_and_refreshes_exact_head(tmp_path, monkeypatch, parent_scope):
    data, path = prepared(tmp_path, monkeypatch, parent_scope=parent_scope)
    config = json.loads(path.read_text())
    config['admissions'][0]['review_disposition'] = {'stale': True}
    peer = {**config['admissions'][0], 'number': 11, 'worker': 'peer'}
    config['admissions'].append(peer)
    path.write_text(json.dumps(config))
    result = tick(data, path)['results'][-1]
    assert result['action'] == 'published-awaiting-new-head-review', result
    assert admission(path)['head_sha'] == NEW
    assert 'repair_publication' not in admission(path)
    assert 'review_disposition' not in admission(path)
    updated = json.loads(path.read_text())
    assert updated['other'] == {'keep': True} and updated['admissions'][1] == peer
    tick(data, path)
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1
    assert not any(c[:3] == ('gh', 'pr', 'create') for c in data[4].calls)


def test_advance_recovers_applied_push_after_lost_readback(tmp_path, monkeypatch):
    data, path = prepared(tmp_path, monkeypatch)
    data[4].fail_history_once = True
    first = tick(data, path)['results'][-1]
    assert first['action'] == 'wait' and admission(path)['head_sha'] == HEAD
    assert data[4].remote == NEW
    second = tick(data, path)['results'][-1]
    assert second['action'] == 'published-awaiting-new-head-review', second
    assert admission(path)['head_sha'] == NEW
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


def test_advance_unknown_unapplied_never_retries(tmp_path, monkeypatch):
    data, path = prepared(tmp_path, monkeypatch)
    data[4].fail_push = True
    first = tick(data, path)['results'][-1]
    second = tick(data, path)['results'][-1]
    assert first['action'] == second['action'] == 'wait'
    assert admission(path)['head_sha'] == HEAD and data[4].remote == HEAD
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


@pytest.mark.parametrize('fault', ['missing', 'stale', 'missing_child'])
def test_advance_waits_for_current_evidence(tmp_path, monkeypatch, fault):
    data, path = prepared(tmp_path, monkeypatch, parent_scope=True)
    receipt = json.loads(data[5].read_text())
    if fault == 'missing':
        data[5].unlink()
    elif fault == 'stale':
        receipt['review']['scope_issue_body_sha256']['6618'] = '0' * 64
        data[5].write_text(json.dumps(receipt))
    else:
        receipt['verification'][0]['target'] = 'tests/parent_future.py::test_future'
        data[5].write_text(json.dumps(receipt))
    result = tick(data, path)['results'][-1]
    assert result['action'] == ('awaiting-candidate-review' if fault == 'missing' else 'wait'), result
    assert admission(path)['head_sha'] == HEAD
    assert not any(c[:2] == ('git', 'push') for c in data[4].calls)


@pytest.mark.parametrize('missing_candidate_admission', [False, True])
def test_unknown_publication_does_not_stop_peer_review(tmp_path, monkeypatch, missing_candidate_admission):
    from app.builderops import epic_workspace as ew
    from tests.builderops.test_epic_workspace_isolation import FakeEngine

    if missing_candidate_admission:
        data, path = _automatic_bound_candidate(tmp_path, monkeypatch)
        tick(data, path)
    else:
        data, path = prepared(tmp_path, monkeypatch)
    layout, port, server, original_fetch = data[0], data[4], data[7], data[8]
    port.fail_push = True
    worker, cid = 'peer', 'f' * 64
    checkout = layout.checkout(worker)
    checkout.mkdir(parents=True, exist_ok=True)
    ew._reserve_worker(layout, 6619, worker, state='running', runtime='openhands', port=18701,
                       container_id=cid, checkout=str(checkout))
    ew._session_key_file(layout, worker)
    engine = FakeEngine()
    engine.ids[layout.container_name(worker)] = cid
    engine.containers[worker] = 'running'
    engine.labels[worker] = [f'{ew.LABEL_EPIC}=6615', f'{ew.LABEL_WORKER}={worker}']
    engine.ports[worker] = 18701
    engine.launches[worker] = ['docker', 'create', '--mount', f'type=bind,source={checkout},target=/workspace']
    monkeypatch.setattr(cycle, '_worker_runner', engine)
    config = json.loads(path.read_text())
    peer = {**config['admissions'][0], 'number': 11, 'worker': worker}
    peer.pop('repair_publication', None)
    for key in ('_automatic_native', '_automatic_context', '_automatic_owner_binding'):
        peer.pop(key, None)
    peer_host = tmp_path / 'peer-owner'
    peer_host.mkdir()
    peer.update(claimant='peer-owner', session='peer-builder-session', lease_id='peer-lease',
                lifecycle_repo=str(peer_host), owner_worktree=str(peer_host))
    # The publisher fixture now carries its real lifecycle source. Give the unrelated
    # peer its own existing registration/claim ports instead of borrowing that authority.
    original_registration = cycle._lifecycle_owner
    peer_registration = {'path': str(peer_host), 'branch': 'codex/peer', 'owner': peer['session'],
                         'generation': '3' * 32, 'registration_epoch': '4' * 32,
                         'registered_at': 100.0, 'expires_at': 9999999999.0}
    monkeypatch.setattr(cycle, '_lifecycle_owner', lambda layout, entry, branch:
                        (peer_registration, {}) if entry['worker'] == worker else original_registration(layout, entry, branch))
    original_inspect = cycle.closure._dispatcher_inspect
    peer_task_id = cycle.github_issue_task_id(cycle.completion.REPOSITORY, 6619)
    peer_task = {'task_id': peer_task_id, 'repo': cycle.completion.REPOSITORY, 'issue_number': 6619,
                 'status': 'claimed', 'claimed_by': peer['claimant'], 'lease_id': peer['lease_id'],
                 'lease_expires_at': '2099-01-01T00:00:00Z', 'linked_pr': 11}
    peer_lease = {'lease_id': peer['lease_id'], 'holder': peer['claimant'], 'resource': 'issue:6619',
                  'expires_at': peer_task['lease_expires_at'], 'released_at': None}
    peer_events = [{'task_id': peer_task_id, 'event_type': 'task.claimed', 'actor': peer['claimant'],
                   'lease_id': peer['lease_id'], 'timestamp': '2026-11-13T00:00:00Z',
                   'payload': {'session': peer['session'], 'ttl_minutes': 90}}]
    monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', lambda executor, cwd, task_id:
                        (peer_task, peer_events, peer_lease) if task_id == peer_task_id else original_inspect(executor, cwd, task_id))
    original_pr = cycle.closure._pr
    monkeypatch.setattr(cycle.closure, '_pr', lambda executor, cwd, repo, number:
                        {'head': {'sha': HEAD, 'ref': 'codex/peer'}} if number == 11 else original_pr(executor, cwd, repo, number))
    config['admissions'].append(peer)
    if missing_candidate_admission:
        config['admissions'] = [peer]
    path.write_text(json.dumps(config))
    def collector(route, timeout):
        if '/pulls?state=open' in route:
            return 200, json.dumps([{'number': 10}, {'number': 11}]).encode()
        if '/pulls/11/reviews' in route:
            return 200, b'[]'
        if route.endswith('/pulls/11'):
            row = {'number': 11, 'state': 'open', 'draft': False, 'labels': [],
                   'title': 'Peer', 'body': 'Governing-Issue: #6619\nFixes #6619\n',
                   'head': {'sha': HEAD, 'repo': {'full_name': cycle.completion.REPOSITORY}},
                   'base': {'sha': 'b' * 40, 'ref': 'main'}}
            return 200, json.dumps(row).encode()
        if route.endswith('/issues/6619'):
            return 200, json.dumps({'number': 6619, 'state': 'open', 'body': 'Peer issue'}).encode()
        return original_fetch(route, timeout)
    first = cycle.advance(layout, path, fetch=collector, http=server, publisher_executor=port)
    actions = {row['number']: row for row in first['results']}
    assert actions[10]['action'] == 'wait'
    assert 11 in actions, first
    assert actions[11]['action'] == 'independent-review', actions[11]
    assert any(call[0] == 'POST' and call[3]['tags']['worker'] == worker for call in server.calls)
    assert len([c for c in port.calls if c[:2] == ('git', 'push')]) == (0 if missing_candidate_admission else 1)


def test_applied_readback_precedes_fresh_evidence_check(tmp_path, monkeypatch):
    data, path = prepared(tmp_path, monkeypatch)
    data[4].fail_history_once = True
    assert tick(data, path)['results'][-1]['action'] == 'wait'
    original = data[5].read_text()
    data[5].unlink()
    assert tick(data, path)['results'][-1]['action'] == 'wait'
    assert cycle._mapping(data[0], 'reviewer')['publication_ops'][0]['status'] == 'confirmed'
    assert admission(path)['head_sha'] == HEAD
    data[5].write_text(original)
    assert tick(data, path)['results'][-1]['action'] == 'published-awaiting-new-head-review'
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


@pytest.mark.parametrize('outcome', ['lost_readback', 'unapplied'])
def test_automatic_admission_reconciles_original_publication_before_new_head(tmp_path, monkeypatch, outcome):
    data, path = prepared(tmp_path, monkeypatch)
    config = json.loads(path.read_text())
    settings = {'claimant': 'owner-6618', 'session': 'builder-session-6618',
                'lifecycle_repo': str(tmp_path / 'controller-repository'), 'test_venv': '/approved/venv',
                'engine': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high'}
    config['automatic_native'] = settings
    config['admissions'][0]['_automatic_native'] = settings
    path.write_text(json.dumps(config))

    original_admission = cycle._automatic_admission

    def no_replacement(layout, pr, settings):
        if pr['number'] == 10:
            raise AssertionError('initial admission must not replace an unsettled candidate/publication')
        return original_admission(layout, pr, settings)

    monkeypatch.setattr(cycle, '_automatic_admission', no_replacement)
    if outcome == 'lost_readback':
        data[4].fail_history_once = True
    else:
        data[4].fail_push = True
    first = tick(data, path)['results'][-1]
    assert first['action'] == 'wait'
    assert admission(path)['head_sha'] == HEAD
    second = tick(data, path)['results'][-1]
    if outcome == 'lost_readback':
        assert data[4].remote == NEW
        assert second['action'] == 'published-awaiting-new-head-review', second
        assert admission(path)['head_sha'] == NEW
    else:
        assert second['action'] == 'wait'
        assert admission(path)['head_sha'] == HEAD
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


def _automatic_bound_candidate(tmp_path, monkeypatch):
    """Real automatic producer/native reader/publisher; reuse the existing synthetic authority ports."""
    path = tmp_path / 'controller-admissions.json'
    # Persist real automatic admission before producing the candidate. Emptying an
    # existing candidate's admission would exercise loss/recovery, not first intake.
    data = prepare(tmp_path, monkeypatch, real_authority=True, automatic_path=path)
    data[1][0]['repair_publication'].update(paths=['feature.txt'], evidence_file=str(data[5]))
    return data, path


@pytest.mark.parametrize('row_state', ['retained', 'missing', 'replaced'])
@pytest.mark.parametrize('observed_head', [HEAD, NEW], ids=['same-head', 'changed-head'])
def test_unpublished_candidate_fences_admission_before_rederivation(tmp_path, monkeypatch, row_state, observed_head):
    data, path = _automatic_bound_candidate(tmp_path, monkeypatch)
    tick(data, path)
    before = cycle.workspace._load_state(data[0])
    original = [r for r in before['compact_receipts'] if r.get('kind') == 'pr_cycle']
    assert len(original) == 1 and original[0]['repair_candidate']['old_head'] == HEAD
    assert original[0].get('repair_publication') is None
    config = json.loads(path.read_text())
    original_row = dict(config['admissions'][0])
    if row_state == 'missing':
        config['admissions'] = []
    elif row_state == 'replaced':
        config['admissions'][0]['head_sha'] = NEW
    path.write_text(json.dumps(config))
    expected_config = path.read_bytes()
    data[4].remote = observed_head
    result = tick(data, path)
    after = cycle.workspace._load_state(data[0])
    assert path.read_bytes() == expected_config, result
    cycles = [r for r in after['compact_receipts'] if r.get('kind') == 'pr_cycle']
    assert len(cycles) == 1 and cycles[0]['identity'] == original[0]['identity']
    assert cycles[0]['repair_candidate'] == original[0]['repair_candidate']
    if row_state != 'retained' or observed_head != HEAD:
        assert result['results'][-1]['action'] == 'wait', result
        assert after['dispatch_decisions'] == before['dispatch_decisions']
    assert not any(c[:2] == ('git', 'push') for c in data[4].calls)
    # Restore only the original controller record; no regenerated authority is used.
    if row_state != 'retained':
        config['admissions'] = [original_row]
        path.write_text(json.dumps(config))
        data[4].remote = HEAD
        resumed = tick(data, path)
        assert admission(path) == original_row, resumed
        assert 'persisted admission' not in resumed['results'][-1].get('reason', '')


@pytest.mark.parametrize('publication_state', [
    'native_published', 'update_pushed', 'check_readback_pending', 'native_published_wrong_head',
])
def test_only_terminal_publication_allows_missing_row_readmission(tmp_path, monkeypatch, publication_state):
    data, path = _automatic_bound_candidate(tmp_path, monkeypatch)
    tick(data, path)
    config = json.loads(path.read_text())
    config['admissions'][0]['repair_publication'] = data[1][0]['repair_publication']
    path.write_text(json.dumps(config))
    assert tick(data, path)['results'][-1]['action'] == 'published-awaiting-new-head-review'
    state = cycle.workspace._load_state(data[0])
    saved = next(r for r in state['compact_receipts'] if r.get('kind') == 'pr_cycle')
    assert saved['repair_publication']['state'] == 'native_published'
    assert saved['repair_publication']['published_head'] == NEW
    if publication_state == 'native_published_wrong_head':
        saved['repair_publication']['published_head'] = HEAD
    else:
        saved['repair_publication']['state'] = publication_state
    cycle._save(data[0], saved)
    config['admissions'] = []
    path.write_text(json.dumps(config))
    result = tick(data, path)
    rows = json.loads(path.read_text())['admissions']
    if publication_state == 'native_published':
        assert len(rows) == 1 and rows[0]['head_sha'] == NEW, result
        assert rows[0]['_automatic_context'] and rows[0]['_automatic_owner_binding']
    else:
        assert rows == [] and result['results'][-1]['action'] == 'wait', result
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


@pytest.mark.parametrize('lost_readback', [False, True])
def test_empty_automatic_config_composes_bound_publication_refresh_and_restart(tmp_path, monkeypatch, lost_readback):
    data, path = _automatic_bound_candidate(tmp_path, monkeypatch)
    first = tick(data, path)['results'][-1]
    rows = json.loads(path.read_text())['admissions']
    assert len(rows) == 1 and rows[0]['number'] == 10, first
    assert rows[0]['head_sha'] == HEAD and rows[0]['_automatic_context']
    original_context = rows[0]['_automatic_context']
    assert not any(c[:2] == ('git', 'push') for c in data[4].calls)
    # The existing owning workflow supplies its independent evidence on the generated row.
    # No PR number, worker, owner, targets or admission marker is hand-created here.
    with cycle._single_advancement(data[0]):
        config = json.loads(path.read_text())
        config['admissions'][0]['repair_publication'] = data[1][0]['repair_publication']
        path.write_text(json.dumps(config))
    data[4].fail_history_once = lost_readback
    result = tick(data, path)['results'][-1]
    if lost_readback:
        assert result['action'] == 'wait', result
        assert admission(path)['head_sha'] == HEAD and data[4].remote == NEW
        result = tick(data, path)['results'][-1]
    assert result['action'] == 'published-awaiting-new-head-review', result
    assert admission(path)['head_sha'] == NEW
    assert 'repair_publication' not in admission(path)
    assert 'review_disposition' not in admission(path)
    # New invocations load the actual file/state again, including the refreshed head.
    after_refresh = tick(data, path)['results'][-1]
    assert admission(path)['head_sha'] == NEW
    assert admission(path)['_automatic_context'] != original_context, after_refresh
    decision_count = len(cycle.workspace._load_state(data[0])['dispatch_decisions'])
    restarted = tick(data, path)['results'][-1]
    assert restarted['action'] in ('wait', 'reconcile'), restarted
    assert len(cycle.workspace._load_state(data[0])['dispatch_decisions']) == decision_count
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


@pytest.mark.parametrize('applied', [False, True], ids=['same-head', 'changed-head'])
def test_missing_automatic_row_holds_unsettled_publication_instead_of_readmitting(tmp_path, monkeypatch, applied):
    data, path = _automatic_bound_candidate(tmp_path, monkeypatch)
    tick(data, path)
    config = json.loads(path.read_text())
    assert len(config['admissions']) == 1
    config['admissions'][0]['repair_publication'] = data[1][0]['repair_publication']
    path.write_text(json.dumps(config))
    data[4].fail_history_once = applied
    data[4].fail_push = not applied
    assert tick(data, path)['results'][-1]['action'] == 'wait'
    assert data[4].remote == (NEW if applied else HEAD) and admission(path)['head_sha'] == HEAD
    # Lost controller configuration is not a fresh admission opportunity.
    original = path.read_text()
    config['admissions'] = []
    path.write_text(json.dumps(config))
    result = tick(data, path)['results'][-1]
    assert result['action'] == 'wait'
    assert 'persisted admission' in result['reason'], result
    assert json.loads(path.read_text())['admissions'] == []
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1
    # Restoring the existing controller record resumes the same effect, without a new push.
    path.write_text(original)
    assert tick(data, path)['results'][-1]['action'] == ('published-awaiting-new-head-review' if applied else 'wait')
    assert admission(path)['head_sha'] == (NEW if applied else HEAD)
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


@pytest.mark.parametrize('missing', ['owner', 'placement'])
def test_automatic_published_head_rescan_preserves_owner_and_placement_holds(tmp_path, monkeypatch, missing):
    data, path = _automatic_bound_candidate(tmp_path, monkeypatch)
    tick(data, path)
    config = json.loads(path.read_text())
    config['admissions'][0]['repair_publication'] = data[1][0]['repair_publication']
    path.write_text(json.dumps(config))
    assert tick(data, path)['results'][-1]['action'] == 'published-awaiting-new-head-review'
    before = path.read_bytes()
    from app.builderops import epic_workspace as workspace
    workspace._record_worker(data[0], 6618, **({'lifecycle_owner': 'another-owner'} if missing == 'owner' else {'worker': None}))
    result = tick(data, path)['results'][-1]
    assert result['action'] == 'wait'
    assert ('another lifecycle owner' if missing == 'owner' else 'placement missing') in result['reason'], result
    assert path.read_bytes() == before
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1
