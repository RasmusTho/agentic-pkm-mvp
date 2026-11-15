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


def test_unknown_publication_does_not_stop_peer_review(tmp_path, monkeypatch):
    from app.builderops import epic_workspace as ew
    from tests.builderops.test_epic_workspace_isolation import FakeEngine

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
    peer.pop('repair_publication')
    config['admissions'].append(peer)
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
    assert len([c for c in port.calls if c[:2] == ('git', 'push')]) == 1


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
