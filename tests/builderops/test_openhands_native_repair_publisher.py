"""Native PR full publisher: real gates and receipts, synthetic external ports."""
import json
from pathlib import Path

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_pr_cycle as cycle
from app.builderops.publication import CommandResult
from tests.builderops.test_openhands_pr_cycle import (
    BLOCKING_FINDING, CONFORMING, HEAD, bind_worker_endpoint, fake_completed_review_stop, fetch, setup,
)

BASE = 'f' * 40
NEW = 'd' * 40
TREE = 'b' * 40
BODY = 'Governing-Issue: #6618\nFixes #6618\n'
ISSUE = '## Acceptance Criteria\n\n- [ ] Repair works.\n  - Verify: `tests/example.py::test_example`\n'
PARENT_ISSUE = '## Context\n\nChild #6618.\n\n## Acceptance Criteria\n\n- [ ] Future parent work.\n  - Verify: `tests/parent_future.py::test_future`\n'
TITLE = 'Native repair'
BRANCH = 'codex/example'
REPO = delivery.REPOSITORY
REAL_NATIVE_AUTHORITY = cycle.native_authority


class Port:
    def __init__(self, host, body=BODY, parent_scope=False):
        self.host = host
        self.body = body
        self.remote = HEAD
        self.draft = False
        self.tree = TREE
        self.fail_push = False
        self.applied = False
        self.calls = []
        self.before_push = None
        self.fail_history_once = False
        self.issue = {'number': 6618, 'state': 'open', 'title': 'repair issue', 'body': ISSUE,
                      'labels': [{'name': 'agent:in-progress'}]}
        self.issues = {6618: self.issue}
        if parent_scope:
            self.issues[6615] = {'number': 6615, 'state': 'open', 'title': 'parent', 'body': PARENT_ISSUE,
                                 'labels': [{'name': 'agent:blocked'}, {'name': 'action:wait-dependency'},
                                            {'name': 'type:epic'}]}
    def run(self, argv, *, cwd, input_text=None):
        a = tuple(argv)
        self.calls.append(a)
        if 'app.dispatcher' in a:
            if 'status' in a:
                return CommandResult(a, 0, '{"ok":true,"db_exists":true,"coordination_mode":"dispatcher-backed","fallback_reason":null}', '')
            if 'verification-status' in a:
                return CommandResult(a, 0, '{"ok":true,"runs":[]}', '')
        if Path(cwd) != self.host:
            if 'verification-status' in a:
                return CommandResult(a, 0, '{"ok":true,"runs":[]}', '')
            if a[:3] == ('gh', 'api', '--hostname') and 'user' in a:
                return CommandResult(a, 0, 'RasmusTho\n', '')
            raise AssertionError((a, cwd))
        out = ''
        code = 0
        if a == ('git', 'rev-parse', '--show-toplevel'):
            out = str(self.host)
        elif a == ('git', 'branch', '--show-current'):
            out = BRANCH
        elif a == ('git', 'rev-parse', 'HEAD'):
            out = NEW
        elif a == ('git', 'rev-parse', 'HEAD^{tree}'):
            out = self.tree
        elif a == ('git', 'rev-parse', 'origin/main'):
            out = BASE
        elif a[:3] == ('git', 'remote', 'get-url'):
            out = f'https://github.com/{REPO}.git'
        elif a[:2] == ('git', 'ls-remote'):
            ref = a[-1]
            sha = BASE if ref == 'refs/heads/main' else self.remote
            out = f'{sha}\t{ref}'
        elif a[:3] == ('git', 'merge-base', '--is-ancestor'):
            out = ''
        elif a[:2] == ('git', 'rev-list'):
            out = f'{NEW} {HEAD}'
        elif a[:2] == ('git', 'show'):
            out = 'bounded repair\n'
        elif a[:2] == ('git', 'diff-tree'):
            out = 'feature.txt\0'
        elif a[:2] in (('git', 'diff'), ('git', 'ls-files')):
            out = ''
        elif a[:2] == ('git', 'push'):
            if self.before_push:
                self.before_push()
            if not self.fail_push or self.applied:
                self.remote = NEW
            code = 1 if self.fail_push else 0
        elif any('agent_workspace_preflight.sh' in x or 'review_before_ci_gate.py' in x for x in a):
            out = '{}'
        elif a[:6] == ('gh', 'api', '--hostname', 'github.com', '--method', 'GET'):
            endpoint = a[6]
            if '/issues/' in endpoint and endpoint.rsplit('/', 1)[-1].isdigit():
                out = json.dumps(self.issues[int(endpoint.rsplit('/', 1)[-1])])
            elif endpoint.endswith('/git/ref/heads/main'):
                out = json.dumps({'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': BASE}})
            elif endpoint.endswith('/pulls'):
                if self.fail_history_once and self.remote == NEW:
                    self.fail_history_once = False
                    return CommandResult(a, 1, '', 'synthetic readback loss')
                out = json.dumps([{'number': 10, 'state': 'open', 'draft': self.draft, 'merged_at': None,
                    'title': TITLE, 'body': self.body, 'html_url': 'https://example.invalid/pull/10',
                    'head': {'sha': self.remote, 'ref': BRANCH, 'repo': {'full_name': REPO}},
                    'base': {'sha': BASE, 'ref': 'main', 'repo': {'full_name': REPO}}}])
            elif endpoint.endswith('/check-runs'):
                out = json.dumps({'total_count': 0, 'check_runs': []})
            elif endpoint.endswith('/status'):
                out = json.dumps({'sha': NEW, 'state': 'pending', 'total_count': 0, 'statuses': []})
            else:
                raise AssertionError(a)
        else:
            raise AssertionError(a)
        return CommandResult(a, code, out, '')


def prepare(tmp_path, monkeypatch, *, real_authority=False, parent_scope=False):
    host = (tmp_path / 'host').resolve()
    host.mkdir()
    body = BODY
    if parent_scope:
        task_id = cycle.github_issue_task_id(REPO, 6618)
        body = (f'Governing-Issue: #6615\nCloses #6618\nPickup-Receipt: pickup-claim-complete issue=6618 '
                f'branch={BRANCH} worktree={host} coordination_mode=dispatcher-backed fallback_reason=none '
                f'task_id={task_id} lease_id=lease holder=owner-6618 evidence=verified-dispatcher-lease\n')
    governing = 6615 if parent_scope else 6618
    governing_body = PARENT_ISSUE if parent_scope else ISSUE
    layout, config, server = setup(tmp_path / 'worker', monkeypatch)
    ew._record_worker(layout, 6618, branch=BRANCH, image='worker@sha256:' + 'c' * 64,
                      network='epicws', budget={'cpus': '1.0', 'memory': '1536m', 'pids': 512},
                      lifecycle_owner='owner-6618', builder_session='builder-session-6618')
    config[0].update(claimant='owner-6618', session='builder-session-6618')
    port_holder = []
    def collector(path, timeout):
        if parent_scope and path.endswith('/issues/6615'):
            return 200, json.dumps({'number': 6615, 'state': 'open', 'body': PARENT_ISSUE}).encode()
        status, data = fetch(path, timeout)
        if path.endswith('/pulls/10'):
            row = json.loads(data)
            row.update(body=body, title=TITLE)
            if port_holder:
                row["head"]["sha"] = port_holder[0].remote
            data = json.dumps(row).encode()
        elif path.endswith('/issues/6618'):
            data = json.dumps({'number': 6618, 'state': 'open', 'body': ISSUE}).encode()
        elif parent_scope and path.endswith('/issues/6615'):
            data = json.dumps({'number': 6615, 'state': 'open', 'body': PARENT_ISSUE}).encode()
        return status, data
    cycle.advance(layout, config, fetch=collector, http=server)
    state = ew._load_state(layout)
    review = next(r for r in state['compact_receipts'] if r.get('kind') == 'pr_cycle')
    cid = state['issue_mappings']['6618']['conversation']['id']
    server.conversations[cid]['execution_status'] = 'finished'
    report = {**CONFORMING, 'identity': review['identity'], 'head_sha': HEAD, 'verdict': 'findings',
              'findings': [BLOCKING_FINDING], 'verify_targets': config[0]['verify_targets']}
    server.final_responses[cid] = json.dumps(report)
    def first_stop(layout, worker, **kwargs):
        fake_completed_review_stop(layout, worker, **kwargs)
        mapping = cycle._mapping(layout, worker)
        ew._record_worker(layout, 6618, conversation={**mapping['conversation'], 'status': ew.CONVERSATION_ENDED},
                          work_at_stop={**mapping['work_at_stop'], 'head': HEAD})
    monkeypatch.setattr(ew, 'stop_worker', first_stop)
    config[0]['owner_worktree'] = str(host)
    registration = {'path': str(host), 'branch': BRANCH, 'owner': 'builder-session-6618',
                    'generation': '1' * 32, 'registration_epoch': '2' * 32, 'expires_at': 9999999999}
    authority = {'number': 10, 'head_sha': HEAD, 'body': body, 'title': TITLE, 'branch': BRANCH,
                 'owner': {'lease_id': 'lease'}, 'claim_issue': 6618, 'governing_issue': governing,
                 'governing_issue_hashes': {'body_sha256': delivery._sha(governing_body)}, 'closing_issues': [6618],
                 'base_ref': 'main', 'worktree_owner': registration}
    port = Port(host, body, parent_scope)
    port_holder.append(port)
    def native_authority(layout, pr, entry, **kwargs):
        assert pr['head_sha'] == port.remote
        return {**authority, 'head_sha': port.remote}
    if real_authority:
        config[0]['lease_id'] = 'lease'
        config[0]['lifecycle_repo'] = str(host)
        task_id = cycle.github_issue_task_id(REPO, 6618)
        task = {'task_id': task_id, 'repo': REPO, 'issue_number': 6618, 'status': 'claimed',
                'claimed_by': 'owner-6618', 'lease_id': 'lease',
                'lease_expires_at': '2099-01-01T00:00:00Z', 'linked_pr': 10}
        lease = {'lease_id': 'lease', 'holder': 'owner-6618', 'resource': 'issue:6618',
                 'expires_at': task['lease_expires_at'], 'released_at': None}
        events = [{'task_id': task_id, 'event_type': 'task.claimed', 'actor': 'owner-6618', 'lease_id': 'lease',
                   'timestamp': '2026-11-13T00:00:00Z',
                   'payload': {'session': 'builder-session-6618', 'ttl_minutes': 90}}]
        registration['registered_at'] = 100.0
        monkeypatch.setattr(cycle, 'native_authority', REAL_NATIVE_AUTHORITY)
        monkeypatch.setattr(cycle, 'SubprocessExecutor', lambda **kwargs: port)
        monkeypatch.setattr(cycle, '_api_pages', lambda *args, **kwargs: [])
        monkeypatch.setattr(cycle, '_lifecycle_owner', lambda *args: (registration, {}))
        monkeypatch.setattr(cycle.closure, '_api', lambda *args: {'full_name': REPO, 'default_branch': 'main'})
        def live_pr(*args):
            return {'number': 10, 'state': 'open', 'draft': False, 'title': TITLE, 'body': body, 'labels': [],
                    'head': {'sha': port.remote, 'ref': BRANCH, 'repo': {'full_name': REPO}},
                    'base': {'ref': 'main', 'sha': BASE}}
        monkeypatch.setattr(cycle.closure, '_pr', live_pr)
        monkeypatch.setattr(cycle.closure, '_issue', lambda *args: port.issues[args[-1]])
        monkeypatch.setattr(cycle.closure, '_closing_issue_references', lambda *args: [6618])
        monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', lambda *args: (task, events, lease))
    else:
        monkeypatch.setattr(cycle, 'native_authority', native_authority)
    def takeover(layout, worker, **kwargs):
        mapping = cycle._mapping(layout, worker)
        ew._record_worker(layout, 6618, takeover={'status': 'authorized', 'stop_id': mapping['stop_id'], 'generation': 1})
    def launch(layout, worker, **kwargs):
        mapping = cycle._mapping(layout, worker)
        bind_worker_endpoint(layout, monkeypatch, 'e' * 64)
        ew._record_worker(layout, 6618, state='running', container_id='e' * 64,
                          takeover={'status': 'consumed', 'stop_id': mapping['stop_id'], 'generation': 1})
    monkeypatch.setattr(ew, '_takeover_locked', takeover)
    monkeypatch.setattr(ew, '_start_openhands_worker_locked', launch)
    assert cycle.advance(layout, config, fetch=collector, http=server)['results'][1]['action'] == 'repair-author'
    author = cycle._mapping(layout, 'reviewer')['conversation']
    server.conversations[author['id']]['execution_status'] = 'finished'
    monkeypatch.setattr(cycle, 'native_execution_proof', lambda layout, worker, op, admission, **kw: {
        'operation_id': op, 'conversation_id': author['id'], 'container_id': 'e' * 64,
        'engine': admission['engine'], 'model': admission['model']})
    def author_stop(layout, worker, **kwargs):
        mapping = cycle._mapping(layout, worker)
        stop_id = kwargs['stop_intent']['stop_id']
        cp = {'ref': 'refs/checkpoints/ckpt-0001', 'status': 'preserved', 'tree': TREE,
              'ignored_count': 0, 'branch': BRANCH}
        work = {'stop_id': stop_id, 'present': True, 'readable': True, 'unique_work': True,
                'branch': BRANCH, 'head': HEAD, 'checkpoint': cp}
        ew._record_worker(layout, 6618, state='stopped_verified', stop_id=stop_id, work_at_stop=work,
                          checkpoints=[cp], conversation={**mapping['conversation'], 'status': ew.CONVERSATION_ENDED})
    monkeypatch.setattr(ew, 'stop_worker', author_stop)
    monkeypatch.setattr(cycle, 'SubprocessExecutor', lambda **kwargs: port)
    config[0]['repair_publication'] = {'candidate_head': NEW}
    bound = cycle.advance(layout, config, fetch=collector, http=server)['results'][1]
    assert bound['action'] == 'awaiting-candidate-review', bound
    pr = {'number': 10, 'head_sha': HEAD, 'body': body, 'title': TITLE, 'draft': False,
          'restrictions': [], 'governing_issue': {'body': governing_body, 'state': 'open'}}
    review_file = tmp_path / 'review.txt'
    review_file.write_text(f'Independent review of {NEW}: no blocking findings ' +
                           (f'{delivery._sha(PARENT_ISSUE)} {delivery._sha(ISSUE)}' if parent_scope else ''))
    test_file = tmp_path / 'test-output.txt'
    test_file.write_text('1 passed in 0.1s')
    evidence = {'version': 1, 'repository': REPO, 'issue': governing, 'base_sha': BASE, 'head_sha': NEW,
                'risk_surfaces': ['concurrency', 'state-machine'],
                'review': {'reviewer': 'independent-reviewer', 'verdict': 'pass', 'head_sha': NEW,
                           'blocking_findings': [], 'evidence': {'path': str(review_file)}},
                'verification': [{'target': 'tests/example.py::test_example', 'head_sha': NEW,
                                  'result': 'pass', 'evidence': {'path': str(test_file)}}]}
    if parent_scope:
        evidence['review']['scope_issue_body_sha256'] = {'6615': delivery._sha(PARENT_ISSUE),
                                                          '6618': delivery._sha(ISSUE)}
    evidence_file = tmp_path / 'evidence.json'
    evidence_file.write_text(json.dumps(evidence))
    return layout, config, pr, bound['identity'], port, evidence_file, authority, server, collector


def call(data):
    layout, config, pr, identity, port, evidence_file, _ = data[:7]
    return delivery.publish_native_repair(layout, pr, config[0], identity, ['feature.txt'], evidence_file, executor=port)


def test_existing_native_pr_push_and_repeated_readback(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch)
    def check_intent():
        mapping = cycle._mapping(data[0], 'reviewer')
        [op] = mapping['publication_ops']
        assert op['status'] == 'intended' and op['expect_sha'] == NEW
        assert cycle._find(data[0], 10, data[3])['repair_publication']['state'] == 'update_pushing'
    data[4].before_push = check_intent
    first = call(data)
    assert first['draft'] is False and first['pr_number'] == 10 and first['commit_sha'] == NEW
    assert call(data)['commit_sha'] == NEW
    port = data[4]
    assert len([c for c in port.calls if c[:2] == ('git', 'push')]) == 1
    assert not any(c[:3] == ('gh', 'pr', 'create') for c in port.calls)
    mapping = cycle._mapping(data[0], 'reviewer')
    [op] = mapping['publication_ops']
    assert op['status'] == 'confirmed' and op['result']['sha'] == NEW


@pytest.mark.parametrize('applied', [True, False])
def test_lost_push_is_reconciled_or_held(tmp_path, monkeypatch, applied):
    data = prepare(tmp_path, monkeypatch)
    port = data[4]
    port.fail_push, port.applied = True, applied
    if applied:
        assert call(data)['commit_sha'] == NEW
        assert call(data)['commit_sha'] == NEW
    else:
        with pytest.raises(delivery.DeliveryError, match='uncertain'):
            call(data)
        cycle_result = cycle.advance(data[0], data[1], fetch=data[8], http=data[7])['results'][1]
        assert cycle_result['action'] == 'wait' and 'existing trusted publication' in cycle_result['reason']
        assert cycle._find(data[0], 10, data[3])['repair_candidate']['candidate_head'] == NEW
        with pytest.raises(delivery.DeliveryError, match='unresolved'):
            call(data)
        assert cycle._mapping(data[0], 'reviewer')['publication_ops'][0]['status'] == 'intended'
    assert len([c for c in port.calls if c[:2] == ('git', 'push')]) == 1
    assert not any(c[:3] == ('gh', 'pr', 'create') for c in port.calls)


@pytest.mark.parametrize('fault', ['draft', 'head', 'authority', 'evidence', 'tree', 'missing'])
def test_mismatch_refuses_before_push(tmp_path, monkeypatch, fault):
    data = prepare(tmp_path, monkeypatch)
    port, evidence, authority = data[4], data[5], data[6]
    if fault == 'draft':
        port.draft = True
    elif fault == 'head':
        port.remote = 'e' * 40
    elif fault == 'authority':
        authority['owner'] = {'lease_id': 'changed'}
    elif fault == 'tree':
        port.tree = 'c' * 40
    elif fault == 'missing':
        evidence.unlink()
    else:
        receipt = json.loads(evidence.read_text())
        receipt['review']['head_sha'] = HEAD
        evidence.write_text(json.dumps(receipt))
    with pytest.raises((delivery.DeliveryError, cycle.CycleError, FileNotFoundError)):
        call(data)
    assert not any(c[:2] == ('git', 'push') for c in port.calls)


def test_reconcile_applied_push_before_requiring_fresh_evidence(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch)
    port, evidence = data[4], data[5]
    port.fail_history_once = True
    with pytest.raises(delivery.publication.PublicationCommandError):
        call(data)
    assert cycle._mapping(data[0], 'reviewer')['publication_ops'][0]['status'] == 'intended'
    receipt = json.loads(evidence.read_text())
    receipt['review']['head_sha'] = HEAD
    evidence.write_text(json.dumps(receipt))
    with pytest.raises(delivery.DeliveryError, match='review'):
        call(data)
    assert cycle._mapping(data[0], 'reviewer')['publication_ops'][0]['status'] == 'confirmed'
    assert len([c for c in port.calls if c[:2] == ('git', 'push')]) == 1


def test_real_native_authority_rejects_foreign_claim_before_push(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch)
    layout, config, pr, _, port, _, authority = data[:7]
    config[0]['lease_id'] = 'lease'
    config[0]['lifecycle_repo'] = str(port.host)
    class AuthorityPort:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd, input_text=None):
            return CommandResult(tuple(argv), 0, 'RasmusTho\n', '')
    monkeypatch.setattr(cycle, 'SubprocessExecutor', AuthorityPort)
    monkeypatch.setattr(cycle, 'native_authority', REAL_NATIVE_AUTHORITY)
    monkeypatch.setattr(cycle, '_api_pages', lambda *args, **kwargs: [])
    monkeypatch.setattr(cycle, '_lifecycle_owner', lambda *args: (authority['worktree_owner'], {}))
    monkeypatch.setattr(cycle.closure, '_api', lambda *args: {'full_name': REPO, 'default_branch': 'main'})
    live = {'number': 10, 'state': 'open', 'draft': False, 'title': TITLE, 'body': BODY, 'labels': [],
            'head': {'sha': HEAD, 'ref': BRANCH, 'repo': {'full_name': REPO}}, 'base': {'ref': 'main'}}
    monkeypatch.setattr(cycle.closure, '_pr', lambda *args: live)
    monkeypatch.setattr(cycle.closure, '_issue', lambda *args: port.issue)
    monkeypatch.setattr(cycle.closure, '_closing_issue_references', lambda *args: [6618])
    task_id = cycle.github_issue_task_id(REPO, 6618)
    task = {'task_id': task_id, 'repo': REPO, 'issue_number': 6618, 'status': 'claimed',
            'claimed_by': 'foreign', 'lease_id': 'lease', 'lease_expires_at': '2099-01-01T00:00:00Z', 'linked_pr': 10}
    lease = {'lease_id': 'lease', 'holder': 'foreign', 'resource': 'issue:6618',
             'expires_at': task['lease_expires_at'], 'released_at': None}
    events = [{'task_id': task_id, 'event_type': 'task.claimed', 'actor': 'foreign', 'lease_id': 'lease',
               'timestamp': '2026-11-13T00:00:00Z', 'payload': {'session': 'builder-session-6618', 'ttl_minutes': 90}}]
    monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', lambda *args: (task, events, lease))
    with pytest.raises(cycle.CycleError, match='native owner or lease'):
        call(data)
    assert not any(c[:2] == ('git', 'push') for c in port.calls)


def test_valid_publication_runs_real_native_authority_reader(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch, real_authority=True)
    assert call(data)['commit_sha'] == NEW
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


def test_pr_hold_and_worker_owned_evidence_refuse_before_push(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch)
    data[2]['body'] += '\nDo not merge\n'
    with pytest.raises(delivery.DeliveryError, match='admission'):
        call(data)
    data[2]['body'] = BODY
    worker_evidence = data[0].root / 'untrusted-evidence.json'
    worker_evidence.write_text(data[5].read_text())
    rejected = (*data[:5], worker_evidence, *data[6:])
    with pytest.raises(delivery.DeliveryError, match='outside'):
        call(rejected)
    assert not any(c[:2] == ('git', 'push') for c in data[4].calls)


def test_open_parent_child_verified_native_publication(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch, real_authority=True, parent_scope=True)
    assert call(data)['commit_sha'] == NEW
    assert call(data)['commit_sha'] == NEW
    assert data[4].issues[6615]['state'] == 'open'
    assert len([c for c in data[4].calls if c[:2] == ('git', 'push')]) == 1


def test_open_parent_missing_child_verify_refuses(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch, real_authority=True, parent_scope=True)
    receipt = json.loads(data[5].read_text())
    receipt['verification'][0]['target'] = 'tests/parent_future.py::test_future'
    data[5].write_text(json.dumps(receipt))
    with pytest.raises(delivery.DeliveryError, match='closing Issue Verify'):
        call(data)
    assert not any(c[:2] == ('git', 'push') for c in data[4].calls)


@pytest.mark.parametrize('fault', ['child_body', 'review_scope', 'child_hold'])
def test_parent_child_contract_changes_refuse_before_push(tmp_path, monkeypatch, fault):
    data = prepare(tmp_path, monkeypatch, real_authority=True, parent_scope=True)
    if fault == 'child_body':
        data[4].issue['body'] += '\nChanged contract.\n'
    elif fault == 'child_hold':
        data[4].issue['labels'].append({'name': 'agent:needs-human'})
    else:
        receipt = json.loads(data[5].read_text())
        receipt['review']['scope_issue_body_sha256'].pop('6618')
        data[5].write_text(json.dumps(receipt))
    with pytest.raises((delivery.DeliveryError, cycle.CycleError)):
        call(data)
    assert not any(c[:2] == ('git', 'push') for c in data[4].calls)


def test_full_evidence_requires_all_closings_and_parent_when_closed(tmp_path, monkeypatch):
    data = prepare(tmp_path, monkeypatch, parent_scope=True)
    other = '## Acceptance Criteria\n\n- [ ] Other child.\n  - Verify: `tests/other.py::test_other`\n'
    receipt = json.loads(data[5].read_text())
    contracts = {6618: ISSUE, 6619: other}
    scope = {'6615': delivery._sha(PARENT_ISSUE), **{str(k): delivery._sha(v) for k, v in contracts.items()}}
    receipt['review']['scope_issue_body_sha256'] = scope
    Path(receipt['review']['evidence']['path']).write_text(f'{NEW} ' + ' '.join(scope.values()))
    Path(receipt['verification'][0]['evidence']['path']).write_text('3 passed in 0.1s')
    extra = dict(receipt['verification'][0], target='tests/other.py::test_other')
    receipt['verification'].append(extra)
    data[5].write_text(json.dumps(receipt))
    state = {'issue': 6615, 'worktree': str(data[4].host), 'agent_id': 'owner-6618',
             'session_id': 'builder-session-6618'}
    delivery._full_evidence(data[5], state, NEW, BASE, PARENT_ISSUE, closing_contracts=contracts)
    receipt['verification'].pop()
    data[5].write_text(json.dumps(receipt))
    with pytest.raises(delivery.DeliveryError, match='closing Issue Verify'):
        delivery._full_evidence(data[5], state, NEW, BASE, PARENT_ISSUE, closing_contracts=contracts)
    receipt['verification'].append(extra)
    data[5].write_text(json.dumps(receipt))
    with pytest.raises(delivery.DeliveryError, match='closing Issue Verify'):
        delivery._full_evidence(data[5], state, NEW, BASE, PARENT_ISSUE,
                                closing_contracts={**contracts, 6615: PARENT_ISSUE})
