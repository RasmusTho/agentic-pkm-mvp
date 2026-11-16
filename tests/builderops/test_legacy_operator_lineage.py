from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.builderops import openhands_pr_cycle as cycle
from app.builderops import legacy_owner_recovery as recovery_module
from app.dispatcher import leases
from app.dispatcher.events import claim_event_digest, event_history_digest
from tests.builderops.openhands_disposition_test_support import digest, synthetic_disposition, synthetic_reservation
from tests.builderops.test_openhands_pr_cycle import CONFORMING, setup as setup_worker
from tests.scripts.test_legacy_successor_recovery import operator_case as operator_case_fixture, _args, _git  # noqa: F401

REAL_GIT_READ = cycle.legacy_owner_recovery._git_read
REAL_REVIEW_CONTEXT = cycle._review_context


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


@pytest.fixture
def recovery(monkeypatch):
    issue, pr = 6601, 6602
    historical_body = f'Governing-Issue: #{issue}\nFixes #{issue}\n'
    task = f'github-RasmusTho--agentic-pkm-mvp-issue-{issue}'
    branch, path = 'codex/issue-6601', '/isolated/worktree'
    old = {'event_id': 'old', 'timestamp': '2026-11-08T00:00:00Z', 'task_id': task,
           'event_type': 'task.claimed', 'actor': 'old-agent', 'lease_id': 'old-lease', 'payload': {'ttl_minutes': 1440}}
    new = {'event_id': 'new', 'timestamp': '2026-11-15T08:00:03Z', 'task_id': task,
           'event_type': 'task.claimed', 'actor': 'new-agent', 'lease_id': 'new-lease',
           'payload': {'ttl_minutes': 60, 'session': 'new-session', 'takeover': {'previous_holder': 'old-agent',
                       'previous_lease_id': 'old-lease', 'previous_expires_at': '2026-11-09T00:00:00Z'}}}
    prior = {'path': path, 'branch': branch, 'generation': 'a'*32, 'owner': 'old-session', 'status': 'active',
             'registered_at': stamp('2026-11-08T00:00:00Z'), 'expires_at': stamp('2026-11-09T00:00:00Z')}
    candidate = {'path': path, 'branch': branch, 'generation': 'a'*32, 'head': 'b'*40, 'tree': 'e'*40,
                 'status_digest': hashlib.sha256(b'').hexdigest()}
    observed_registration = {'path': path, 'branch': branch, 'generation': 'a'*32, 'owner': 'old-session',
        'state': 'expired', 'registered_at': '2026-11-08T00:00:00Z', 'expires_at': '2026-11-09T00:00:00Z',
        'history_digest': hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest(), 'branch_history_digest': 'c'*64}
    predecessor = {'task_id': task, 'repo': 'RasmusTho/agentic-pkm-mvp', 'issue_number': issue, 'holder': 'old-agent',
       'lease_id': 'old-lease', 'claim_event_id': 'old', 'claim_event_digest': claim_event_digest(old),
       'history_digest': event_history_digest([old]), 'session': None, 'expires_at': '2026-11-09T00:00:00Z'}
    transfer = {'branch': branch, 'base': 'd'*40, 'base_sha': 'd'*40, 'head': 'b'*40,
                'changed_files': ['file.py'], 'clean': True, 'observed_at': stamp('2026-11-15T08:00:03.500000Z')}
    reg = {'path': path, 'branch': branch, 'generation': 'a'*32, 'owner': 'new-session',
           'registration_epoch': 'f'*32, 'authority_since': stamp('2026-11-15T08:00:04Z'),
           'expires_at': stamp('2026-11-15T09:00:00Z'), 'prior_owner': dict(prior),
           'previous_registration': dict(prior)}
    ack_reg = {'path': path, 'branch': branch, 'generation': 'a'*32, 'owner': 'new-session',
               'epoch': 'f'*32, 'observed_at': reg['authority_since']}
    receipt = {'issue': issue, 'mode': 'operator', 'account': 'RasmusTho',
       'mandate': {'reference': 'session instruction', 'effects': ['reconcile', 'claim', 'register', 'acknowledge'],
                   'repo': 'RasmusTho/agentic-pkm-mvp', 'issue': issue},
       'successor': {'agent': 'new-agent', 'session': 'new-session'}, 'predecessor': predecessor,
       'registration': observed_registration, 'candidate': candidate,
       'writer': {'state': 'stopped', 'delegations': 'stopped', 'restart': 'reconciled',
                  'last_activity': '2026-11-09T00:00:00Z', 'boot': '2026-11-14T00:00:00Z',
                  'sources': {'execution': ['execution observation'], 'delegations': ['delegation observation'], 'restart': ['boot observation']}},
       'publication': {'state': 'reconciled', 'pr': pr, 'head': 'b'*40, 'repo': 'RasmusTho/agentic-pkm-mvp',
                       'branch': branch, 'pr_state': 'OPEN',
                       'body_sha256': hashlib.sha256(historical_body.encode()).hexdigest(),
                       'sources': {'attempts': ['attempt observation'], 'github': ['PR observation']}},
       'branch': branch, 'writable_worktree': path, 'predecessor_registration': prior,
       'branch_history_digest': 'c'*64, 'base': 'd'*40, 'unpublished_candidate_head': 'b'*40, 'changed_files': ['file.py']}
    def comment(number, at, body):
        return {'id': number, 'author_association': 'OWNER', 'user': {'login': 'RasmusTho'},
                'issue_url': f'https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/{issue}',
                'created_at': at, 'updated_at': at, 'body': json.dumps({'operator_reconciliation.v1': body})}
    c1 = comment(1, '2026-11-15T08:00:00Z', receipt)
    c2 = comment(2, '2026-11-15T08:00:06Z', {**receipt, 'successor_acknowledgment':
                  {'successor_registration': ack_reg, 'candidate_readback': transfer, 'ack_attempt_id': '1'*32}})
    proof = {'state': 'pinned', 'issue': issue, 'pending_comment_id': 1, 'ack_comment_id': 2,
             'pending_digest': hashlib.sha256(c1['body'].encode()).hexdigest(),
             'ack_digest': hashlib.sha256(c2['body'].encode()).hexdigest(), 'predecessor': prior,
             'branch_history_digest': 'c'*64, 'candidate_readback': transfer, 'epoch': 'f'*32,
             'authority_since': reg['authority_since'], 'registration_read_at': reg['authority_since'],
             'ack_intent': {'attempt_id': '1'*32, 'intent_at': stamp('2026-11-15T08:00:05Z')},
             'ack_at': stamp(c2['created_at']), 'verified_through': stamp('2026-11-15T08:00:08Z')}
    reg['operator_registration'] = proof
    monkeypatch.setattr(cycle.legacy_owner_recovery, 'read_clean_candidate', lambda **kw: candidate)
    def git_read(worktree, *args):
        if args[0] == 'merge-base': return b''
        if args[0] == 'rev-parse': return (candidate['tree'] + '\n').encode()
        return b'file.py\0'
    monkeypatch.setattr(cycle.legacy_owner_recovery, '_git_read', git_read)
    return dict(events=[old, new], owner={'task_id': task, 'lease_id': 'new-lease', 'lease_holder': 'new-agent'},
       origin={'mode': 'dispatcher-backed', 'lease_id': 'new-lease', 'agent': 'new-agent', 'path': path}, registration=reg, records={path: reg},
       comments=[c1, c2], issue_comments=[], issue=issue, pr_number=pr, branch=branch, head='b'*40,
       files=['file.py'], entry={'claimant': 'new-agent', 'session': 'new-session', 'lease_id': 'new-lease', 'base_sha': 'd'*40,
                                  'lifecycle_repo': '/isolated/repo'})


def test_pinned_operator_recovery_binds_the_real_legacy_takeover(recovery):
    proof = recovery['registration']['operator_registration']
    assert proof['candidate_readback']['observed_at'] < proof['registration_read_at']
    cycle._operator_lineage(**recovery)


@pytest.mark.parametrize('mutation', ['prepared', 'digest', 'session', 'unknown', 'missing', 'claim',
                                     'extra_claim', 'expiry', 'candidate', 'edited', 'registry',
                                     'no_intent', 'intent_id', 'ack_id', 'no_ack_id',
                                     'intent_before_registration', 'intent_at_ack', 'invalid_intent',
                                     'no_body_hash', 'invalid_body_hash'])
def test_operator_recovery_refuses_drift_or_unknown(recovery, mutation):
    data = copy.deepcopy(recovery)
    proof = data['registration']['operator_registration']
    if mutation == 'prepared': proof['state'] = 'prepared'
    if mutation == 'digest': proof['ack_digest'] = '0'*64
    if mutation == 'session': data['registration']['owner'] = 'other'
    if mutation == 'unknown':
        comment = data['comments'][0]
        body = json.loads(comment['body'])
        body['operator_reconciliation.v1']['writer']['state'] = 'UNKNOWN'
        comment['body'] = json.dumps(body)
        proof['pending_digest'] = hashlib.sha256(comment['body'].encode()).hexdigest()
    if mutation == 'missing': data['comments'].pop()
    if mutation == 'claim': data['events'][1]['payload']['takeover']['previous_holder'] = 'other'
    if mutation == 'extra_claim': data['events'].append(copy.deepcopy(data['events'][1]))
    if mutation == 'expiry': data['events'][0]['payload']['ttl_minutes'] = 5
    if mutation == 'candidate': data['head'] = '0'*40
    if mutation == 'edited': data['comments'][1]['updated_at'] = '2026-11-15T08:00:07Z'
    if mutation == 'registry': data['records']['/another'] = {'branch': data['branch']}
    if mutation == 'no_intent': proof.pop('ack_intent')
    if mutation == 'intent_id': proof['ack_intent']['attempt_id'] = '2'*32
    if mutation == 'intent_before_registration': proof['ack_intent']['intent_at'] = proof['registration_read_at'] - 1
    if mutation == 'intent_at_ack': proof['ack_intent']['intent_at'] = proof['ack_at']
    if mutation == 'invalid_intent': proof['ack_intent']['attempt_id'] = 'UNKNOWN'
    if mutation in ('ack_id', 'no_ack_id'):
        comment = data['comments'][1]
        body = json.loads(comment['body'])
        ack = body['operator_reconciliation.v1']['successor_acknowledgment']
        if mutation == 'ack_id': ack['ack_attempt_id'] = '2'*32
        else: ack.pop('ack_attempt_id')
        comment['body'] = json.dumps(body)
        proof['ack_digest'] = hashlib.sha256(comment['body'].encode()).hexdigest()
    if mutation in ('no_body_hash', 'invalid_body_hash'):
        for comment, digest in zip(data['comments'], ('pending_digest', 'ack_digest')):
            body = json.loads(comment['body'])
            publication = body['operator_reconciliation.v1']['publication']
            if mutation == 'no_body_hash': publication.pop('body_sha256')
            else: publication['body_sha256'] = 'not-a-sha'
            comment['body'] = json.dumps(body)
            proof[digest] = hashlib.sha256(comment['body'].encode()).hexdigest()
    with pytest.raises(cycle.CycleError):
        cycle._operator_lineage(**data)


@pytest.mark.parametrize('rewrite', [False, True])
def test_operator_candidate_allows_only_real_descendants(recovery, tmp_path, monkeypatch, rewrite):
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    git('init', '-q')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (tmp_path / 'file.py').write_text('base\n')
    git('add', 'file.py')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    (tmp_path / 'file.py').write_text('pin\n')
    git('commit', '-qam', 'pin')
    pin = git('rev-parse', 'HEAD')
    pin_tree = git('rev-parse', 'HEAD^{tree}')
    if rewrite:
        git('checkout', '-q', '--detach', base)
    (tmp_path / 'file.py').write_text('reviewed fix\n')
    git('commit', '-qam', 'fix')
    head = git('rev-parse', 'HEAD')

    data = copy.deepcopy(recovery)
    reg = data['registration']
    proof = reg['operator_registration']
    pending = json.loads(data['comments'][0]['body'])['operator_reconciliation.v1']
    path = str(tmp_path)
    reg['path'] = path
    reg['prior_owner']['path'] = path
    reg['previous_registration']['path'] = path
    proof['predecessor']['path'] = path
    pending['predecessor_registration']['path'] = path
    pending['registration']['path'] = path
    pending['registration']['history_digest'] = hashlib.sha256(
        json.dumps(pending['predecessor_registration'], sort_keys=True).encode()).hexdigest()
    pending['writable_worktree'] = path
    pending['candidate'].update(path=path, head=pin, tree=pin_tree)
    pending['unpublished_candidate_head'] = pin
    pending['base'] = base
    proof['candidate_readback'].update(head=pin, base=base, base_sha=base)
    ack = json.loads(data['comments'][1]['body'])['operator_reconciliation.v1']['successor_acknowledgment']
    ack['successor_registration']['path'] = path
    ack['candidate_readback'] = copy.deepcopy(proof['candidate_readback'])
    data['comments'][0]['body'] = json.dumps({'operator_reconciliation.v1': pending})
    data['comments'][1]['body'] = json.dumps({'operator_reconciliation.v1':
        {**pending, 'successor_acknowledgment': ack}})
    proof['pending_digest'] = hashlib.sha256(data['comments'][0]['body'].encode()).hexdigest()
    proof['ack_digest'] = hashlib.sha256(data['comments'][1]['body'].encode()).hexdigest()
    data['records'] = {path: reg}
    data['origin']['path'] = path
    data['head'] = head
    data['entry']['base_sha'] = base
    current = {**pending['candidate'], 'head': head, 'tree': git('rev-parse', 'HEAD^{tree}')}
    monkeypatch.setattr(cycle.legacy_owner_recovery, '_git_read', REAL_GIT_READ)
    monkeypatch.setattr(cycle.legacy_owner_recovery, 'read_clean_candidate', lambda **kw: current)
    if rewrite:
        with pytest.raises(cycle.CycleError, match='candidate readback'):
            cycle._operator_lineage(**data)
    else:
        cycle._operator_lineage(**data)


def test_operator_review_context_binds_descendant_diff_and_ack(recovery, monkeypatch):
    head = 'f' * 40
    data = recovery
    registration = data['registration']
    observed = json.loads(data['comments'][0]['body'])['operator_reconciliation.v1']['candidate']
    monkeypatch.setattr(cycle.legacy_owner_recovery, 'read_clean_candidate', lambda **kw: {**observed, 'head': head})
    monkeypatch.setattr(cycle, '_lifecycle_owner', lambda *a: (registration, data['records']))
    monkeypatch.setattr(cycle.closure, '_pr', lambda *a: {'head': {'ref': data['branch'], 'sha': head},
                                                          'base': {'sha': data['entry']['base_sha']}})
    monkeypatch.setattr(cycle, 'resolve_native_issue_authority', lambda body:
                        SimpleNamespace(governing_issue=data['issue'], closing_issues=[data['issue']]))
    monkeypatch.setattr(cycle, '_api_pages', lambda executor, cwd, endpoint:
                        [{'filename': 'file.py'}] if endpoint.startswith('/pulls/') else
                        (data['comments'] if endpoint.startswith(f"/issues/{data['issue']}/") else []))
    monkeypatch.setattr(cycle, '_pickup_origin', lambda *a, **kw: (data['origin'], None))
    monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', lambda *a: ({}, data['events'], {}))
    monkeypatch.setattr(cycle.closure, '_dispatcher_snapshot_from_task', lambda *a, **kw: data['owner'])
    monkeypatch.setattr(cycle.closure, '_validate_claimant_history', lambda *a: None)
    def git(args, cwd):
        if 'rev-parse' in args: return head
        if 'status' in args or 'merge-base' in args: return ''
        if 'diff' in args: return 'reviewed descendant diff'
        raise AssertionError(args)
    monkeypatch.setattr(cycle.agent_worktree.git_hygiene, 'run_git', git)
    pr = {'number': data['pr_number'], 'head_sha': head, 'body': 'contract',
          'review_context': {}, 'review_material': {}}
    cycle._add_transfer_review_context(None, data['entry'], pr)
    material = pr['review_material']['transfer_to_current']
    assert material == {'transfer_head': observed['head'], 'current_head': head, 'diff': 'reviewed descendant diff'}
    assert pr['review_context']['transfer_delta_digest'] == cycle._digest(
        {**material, 'ack_digest': registration['operator_registration']['ack_digest']})


def _saved_review(layout, entry, pr, *, operation='operation', conversation='conversation'):
    """Produce the bound synthetic review inputs consumed by the real premerge gate."""
    identity = cycle.completion.work_identity(pr)
    expected = cycle.report_expectations(layout, entry, pr, identity)
    review = {**copy.deepcopy(CONFORMING), 'identity': identity, 'head_sha': expected['head_sha'],
              'verify_targets': expected['verify_targets'], 'verdict': 'pass', 'findings': [],
              'covered_sources': expected['sources'],
              'closing_assessments': {number: {
                  'acceptance': 'covered', 'verify_coverage': 'covered', 'limitations': [],
                  'criteria': {criterion: {'assessment': 'covered', 'rationale': 'verified'}
                               for criterion in criteria}}
                  for number, criteria in expected['criteria'].items()}}
    entry['review_disposition'] = synthetic_disposition(review)
    synthetic_reservation(layout, pr['number'], identity, operation)
    return {'number': pr['number'], 'identity': identity, 'review_operation': operation,
            'conversation_provenance': {'reviewer': conversation},
            'execution_proof': {'operation_id': operation, 'engine': entry['engine'], 'model': entry['model'],
                'auth': 'chatgpt', 'source': 'native-session-metadata', 'native_session_id': 'native',
                'conversation_id': conversation, 'timestamp': '2026-11-15T08:00:00Z', 'effort': 'high'},
            'review': review,
            'verification': {'passed': True, 'head_sha': pr['head_sha'], 'targets': entry['verify_targets'],
                             'disposition_sha256': digest(entry['review_disposition'])}}


@pytest.fixture
def production_path(operator_case_fixture, tmp_path, monkeypatch):  # noqa: F811 - imported pytest fixture
    case = operator_case_fixture
    result = recovery_module.execute_operator_pickup(**_args(case))
    leases.heartbeat(case['store'], result['task_id'], 'new-agent')
    (case['worktree'] / 'file.txt').write_text('candidate plus reviewed repair\n')
    _git(case['worktree'], 'add', 'file.txt')
    _git(case['worktree'], 'commit', '-m', 'repair')
    head = _git(case['worktree'], 'rev-parse', 'HEAD')
    assert head != case['receipt']['candidate']['head']
    layout, config, _ = setup_worker(tmp_path / 'workers', monkeypatch)
    monkeypatch.setattr(cycle, '_review_context', REAL_REVIEW_CONTEXT)
    entry = {**config[0], 'number': case['pr'], 'head_sha': head, 'lifecycle_repo': str(case['cwd']),
             'owner_worktree': str(case['worktree']), 'claimant': case['agent'], 'session': case['session'],
             'lease_id': result['lease_id']}
    checkout = layout.checkout(entry['worker'])
    (checkout / 'tests').mkdir(parents=True, exist_ok=True)
    (checkout / 'tests' / 'example.py').write_text('def test_example(): pass\n')
    body = (f"Governing-Issue: #{case['issue']}\nFixes #{case['issue']}\n"
            f"Pickup-Receipt: {result['pickup_receipt']}\n"
            f"## Validation\nReviewed repair at {head}.")
    issue_body = '## Acceptance Criteria\n- [ ] Correct result\n  Verify: tests/example.py::test_example\n'
    issue = {'number': case['issue'], 'state': 'open', 'title': 'Recovery', 'body': issue_body, 'labels': []}
    repo = cycle.completion.REPOSITORY
    live = {'number': case['pr'], 'state': 'open', 'draft': False, 'labels': [], 'title': 'Recovery', 'body': body,
            'head': {'sha': head, 'ref': 'codex/example', 'repo': {'full_name': repo}},
            'base': {'ref': 'main', 'sha': case['receipt']['base']}}
    controls = {'ci': 0, 'ci_calls': 0, 'fence': False, 'pr_comments': []}
    files = [{'filename': 'file.txt', 'patch': '@@ -1 +1 @@\n-base\n+candidate plus reviewed repair'}]
    class Executor:
        def __init__(self, **kwargs): pass
        def run(self, argv, *, cwd, input_text=None):
            if 'verification-status' in argv:
                data = {'ok': True, 'runs': ([{'pr_number': case['pr'], 'repository': repo}] if controls['fence'] else [])}
                return subprocess.CompletedProcess(argv, 0, json.dumps(data), '')
            if 'Accept: application/vnd.github.v3.diff' in argv:
                return subprocess.CompletedProcess(argv, 0, 'diff --git a/file.txt b/file.txt\n+candidate', '')
            return subprocess.CompletedProcess(argv, 0, 'RasmusTho\n', '')
    monkeypatch.setattr(cycle, 'SubprocessExecutor', Executor)
    def api(executor, cwd, repository, method, endpoint):
        if endpoint == '': return {'full_name': repo, 'default_branch': 'main'}
        if endpoint.startswith(f"/issues/{case['issue']}/comments"):
            return list(case['comments'].values())
        if endpoint.startswith(f"/issues/{case['pr']}/comments"): return controls['pr_comments']
        if endpoint.startswith(f"/pulls/{case['pr']}/files"): return files
        if endpoint.startswith(f"/pulls/{case['pr']}/commits"):
            return [{'commit': {'message': 'reviewed repair'}}]
        if endpoint.startswith('/git/trees/'): return {'truncated': False, 'tree': []}
        if endpoint == '/branches/main/protection': return {}
        if endpoint.startswith('/rulesets?'): return []
        raise AssertionError(endpoint)
    monkeypatch.setattr(cycle.closure, '_api', api)
    monkeypatch.setattr(cycle.closure, '_pr', lambda *a: live)
    monkeypatch.setattr(cycle.closure, '_issue', lambda *a: issue)
    monkeypatch.setattr(cycle.closure, '_closing_issue_references', lambda *a: [case['issue']])
    def inspect(*args):
        task = case['store'].get_task(result['task_id']).to_dict()
        task['linked_pr'] = case['pr']
        lease = case['store'].get_lease(result['lease_id']).to_dict()
        return task, [event.to_dict() for event in case['store'].list_events(result['task_id'])], lease
    monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', inspect)
    monkeypatch.setattr(cycle, '_assert_review_threads_clear', lambda *a: None)
    def ci_once(*args):
        controls['ci_calls'] += 1
        return {'exit_code': controls['ci']}
    monkeypatch.setattr(cycle, 'ci_once', ci_once)
    def fetch(path, timeout):
        if '/reviews' in path: data = []
        elif f"/pulls/{case['pr']}" in path: data = live
        elif f"/issues/{case['issue']}" in path: data = issue
        else: raise AssertionError(path)
        return 200, json.dumps(data).encode()
    monkeypatch.setattr(cycle, 'github_fetch', fetch)
    pr = cycle.observation._observe(cycle.observation._Reader(fetch, cycle.time.monotonic), case['pr'])
    assert pr is not None
    pr.update(route='native', check_config={})
    pr['review_context'], pr['review_material'] = cycle._review_context(pr)
    cycle._add_transfer_review_context(layout, entry, pr)
    saved = _saved_review(layout, entry, pr)
    return {'layout': layout, 'entry': entry, 'pr': pr, 'saved': saved, 'controls': controls, 'live': live, 'case': case}


def test_operator_full_path_accepts_reviewed_descendant_and_successor_heartbeat(production_path):
    f = production_path
    authority = cycle.native_authority(f['layout'], f['pr'], f['entry'])
    assert authority['head_sha'] == f['pr']['head_sha']
    assert cycle._premerge(f['layout'], f['pr'], f['entry'], f['saved'])['head_sha'] == f['pr']['head_sha']
    assert f['controls']['ci_calls'] == 1
    assert f['pr']['review_material']['transfer_to_current']['current_head'] == f['pr']['head_sha']


def test_later_pr_body_update_requires_fresh_review_identity(production_path):
    f = production_path
    historical_digest = f['case']['receipt']['publication']['body_sha256']
    f['live']['body'] += '\nReview context: updated after recovery.\n'
    assert hashlib.sha256(f['live']['body'].encode()).hexdigest() != historical_digest
    with pytest.raises(cycle.CycleError, match='PR contract, head or actionable review drifted'):
        cycle._premerge(f['layout'], f['pr'], f['entry'], f['saved'])
    updated = cycle.observation._observe(cycle.observation._Reader(cycle.github_fetch, cycle.time.monotonic),
                                          f['case']['pr'])
    assert updated is not None
    updated.update(route='native', check_config={})
    updated['review_context'], updated['review_material'] = cycle._review_context(updated)
    cycle._add_transfer_review_context(f['layout'], f['entry'], updated)
    assert cycle.completion.work_identity(updated) != cycle.completion.work_identity(f['pr'])
    rereview = _saved_review(f['layout'], f['entry'], updated,
                            operation='new-review', conversation='new-conversation')
    assert cycle._premerge(f['layout'], updated, f['entry'], rereview)['head_sha'] == updated['head_sha']


@pytest.fixture
def recovered_child_scope(production_path, monkeypatch):
    f = production_path
    claim, parent = f['case']['issue'], 6615
    # Recovery was produced and pinned with governing == claim. Only the later
    # live PR contract changes; the original child-bound proof stays untouched.
    assert cycle.native_authority(f['layout'], f['pr'], f['entry'])['claim_issue'] == claim
    original_issue, original_fetch = cycle.closure._issue, cycle.github_fetch
    parent_issue = copy.deepcopy(original_issue(None, None, None, claim))
    parent_issue.update(number=parent, body=parent_issue['body'] + f'\nChild #{claim}\n',
                        labels=[{'name': name} for name in
                                ('type:epic', 'agent:blocked', 'action:wait-dependency')])
    f['live']['body'] = f['pr']['body'].replace(f'Governing-Issue: #{claim}', f'Governing-Issue: #{parent}')
    monkeypatch.setattr(cycle.closure, '_issue', lambda executor, cwd, repo, number:
                        parent_issue if number == parent else original_issue(executor, cwd, repo, number))
    monkeypatch.setattr(cycle, 'github_fetch', lambda path, timeout:
                        (200, json.dumps(parent_issue).encode()) if path.endswith(f'/issues/{parent}')
                        else original_fetch(path, timeout))
    updated = cycle.observation._observe(cycle.observation._Reader(cycle.github_fetch, cycle.time.monotonic),
                                         f['case']['pr'])
    assert updated is not None
    updated.update(route='native', check_config={})
    updated['review_context'], updated['review_material'] = cycle._review_context(updated)
    cycle._add_transfer_review_context(f['layout'], f['entry'], updated)
    assert cycle.completion.work_identity(updated) != cycle.completion.work_identity(f['pr'])
    return {**f, 'pr': updated, 'parent': parent}


def test_recovered_operator_uses_child_claim_after_parent_contract_update(recovered_child_scope):
    f = recovered_child_scope
    assert f['pr']['review_material']['transfer_to_current']['current_head'] == f['pr']['head_sha']
    for purpose in ('admission', 'repair', 'merge'):
        authority = cycle.native_authority(f['layout'], f['pr'], f['entry'], purpose=purpose)
        assert authority['governing_issue'] == f['parent']
        assert authority['claim_issue'] == f['case']['issue']
        assert authority['closing_issues'] == [f['case']['issue']]
        assert authority['head_sha'] == f['pr']['head_sha']
        assert authority['owner']['task_id'] == cycle.github_issue_task_id(cycle.completion.REPOSITORY, f['case']['issue'])
        assert authority['owner']['lease_id'] == f['entry']['lease_id']
        assert authority['worktree_owner']['owner'] == f['entry']['session']


@pytest.mark.parametrize('foreign', ['issue', 'task', 'session'])
def test_recovered_child_scope_refuses_foreign_operator_authority(recovered_child_scope, monkeypatch, foreign):
    f = recovered_child_scope
    if foreign == 'issue':
        registry = cycle.agent_worktree._default_registry_path(f['case']['cwd'])
        with cycle.agent_worktree._locked_registry(registry) as payload:
            payload['worktrees'][str(f['case']['worktree'])]['operator_registration']['issue'] = f['parent']
        expected = 'operator registration is missing or unpinned'
    else:
        original_inspect = cycle.closure._dispatcher_inspect
        def inspect(*args):
            task, events, lease = copy.deepcopy(original_inspect(*args))
            if foreign == 'task':
                task['task_id'] = task['task_id'].replace(str(f['case']['issue']), str(f['parent']))
            else:
                claims = [event for event in events if event['event_type'] == 'task.claimed']
                claims[-1]['payload']['session'] = 'foreign-session'
            return task, events, lease
        monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', inspect)
        expected = 'dispatcher' if foreign == 'task' else 'operator takeover does not bind the legacy claim'
    review_error = cycle.closure.ClosureError if foreign == 'task' else cycle.CycleError
    with pytest.raises(review_error, match=expected):
        cycle._add_transfer_review_context(f['layout'], f['entry'], f['pr'])
    for purpose in ('admission', 'repair', 'merge'):
        with pytest.raises(cycle.CycleError, match=expected):
            cycle.native_authority(f['layout'], f['pr'], f['entry'], purpose=purpose)


@pytest.mark.parametrize('failure', ['head', 'review', 'red_ci', 'pending_ci', 'executor_fence', 'inflight_fence',
                                     'stale_ack'])
def test_operator_full_path_rejects_current_head_or_gate_drift(production_path, failure):
    f = production_path
    if failure == 'head': f['live']['head']['sha'] = '0' * 40
    if failure == 'review': f['saved']['review'] = None
    if failure in ('red_ci', 'pending_ci'): f['controls']['ci'] = 1 if failure == 'red_ci' else 2
    if failure == 'executor_fence': f['controls']['fence'] = True
    if failure == 'inflight_fence':
        f['controls']['pr_comments'].append({'id': 90, 'body': 'verification_dispatch_request.v3'})
    if failure == 'stale_ack':
        comment = f['case']['comments'][2]
        body = json.loads(comment['body'])
        body['operator_reconciliation.v1']['successor_acknowledgment']['ack_attempt_id'] = '0'*32
        comment['body'] = json.dumps(body)
        registry = cycle.agent_worktree._default_registry_path(f['case']['cwd'])
        with cycle.agent_worktree._locked_registry(registry) as payload:
            proof = payload['worktrees'][str(f['case']['worktree'])]['operator_registration']
            proof['ack_digest'] = hashlib.sha256(comment['body'].encode()).hexdigest()
    expected = {'head': 'operator candidate readback', 'review': 'review execution or sandbox verification',
                'red_ci': 'current-head CI', 'pending_ci': 'current-head CI',
                'executor_fence': 'verification-dispatch state', 'inflight_fence': 'verification or fenced authority',
                'stale_ack': 'operator registration or acknowledgment drifted'}
    with pytest.raises(cycle.CycleError, match=expected[failure]):
        cycle._premerge(f['layout'], f['pr'], f['entry'], f['saved'])
    if failure in ('red_ci', 'pending_ci'):
        assert f['controls']['ci_calls'] == 1


@pytest.mark.parametrize('drift', ['old_pickup', 'wrong_owner', 'wrong_path', 'wrong_scope', 'wrong_head'])
def test_successor_body_rejects_unbound_authority(production_path, drift):
    f = production_path
    body = f['live']['body']
    if drift == 'old_pickup':
        predecessor = f['case']['receipt']['predecessor']
        body = body.replace(f"lease_id={f['entry']['lease_id']}", f"lease_id={predecessor['lease_id']}")
        body = body.replace(f"holder={f['entry']['claimant']}", f"holder={predecessor['holder']}")
    elif drift == 'wrong_owner':
        body = body.replace(f"holder={f['entry']['claimant']}", 'holder=other-agent')
    elif drift == 'wrong_path':
        body = body.replace(str(f['case']['worktree']), '/foreign/worktree')
    elif drift == 'wrong_scope':
        body = body.replace(f"Fixes #{f['case']['issue']}", 'Fixes #999999')
    else:
        f['live']['head']['sha'] = '0' * 40
    f['live']['body'] = body
    updated = cycle.observation._observe(cycle.observation._Reader(cycle.github_fetch, cycle.time.monotonic),
                                          f['case']['pr'])
    assert updated is not None
    updated.update(route='native', check_config={})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f['layout'], updated, f['entry'])


def test_operator_successor_proof_adapter_reads_actual_pinned_lineage(production_path, monkeypatch):
    from scripts import verify_operator_successor as adapter
    f = production_path
    case = f['case']
    monkeypatch.setattr(recovery_module, '_verify_current_issue', lambda **kw: None)
    result = adapter.verify(issue=case['issue'], pr=case['pr'], cwd=case['cwd'], worktree=case['worktree'],
        workspace_root=f['layout'].root, agent=case['agent'], session=case['session'])
    assert result['head'] == f['pr']['head_sha']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    with cycle.agent_worktree._locked_registry(registry) as payload:
        payload['worktrees'][str(case['worktree'])]['operator_registration']['state'] = 'prepared'
    with pytest.raises(cycle.CycleError):
        adapter.verify(issue=case['issue'], pr=case['pr'], cwd=case['cwd'], worktree=case['worktree'],
            workspace_root=f['layout'].root, agent=case['agent'], session=case['session'])


@pytest.mark.parametrize('drift', ['lease_released', 'lease_expired', 'lease_replaced', 'registration_expired',
                                   'registration_owner', 'registration_epoch', 'heartbeat'])
def test_operator_successor_proof_rechecks_authority_after_lineage(production_path, monkeypatch, drift):
    from scripts import verify_operator_successor as adapter

    f = production_path
    case = f['case']
    monkeypatch.setattr(recovery_module, '_verify_current_issue', lambda **kw: None)
    original_pr = cycle.closure._pr
    calls = 0

    def change_after_lineage(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            task_id = case['receipt']['predecessor']['task_id']
            if drift in ('lease_released', 'lease_replaced'):
                leases.release(case['store'], task_id, case['agent'])
                if drift == 'lease_replaced':
                    leases.claim(case['store'], task_id, case['agent'])
            elif drift == 'lease_expired':
                task = case['store'].get_task(task_id)
                with case['store']._connect() as conn:
                    conn.execute("UPDATE dispatcher_leases SET expires_at = ? WHERE lease_id = ?",
                                 ('2000-01-01T00:00:00+00:00', task.lease_id))
                    conn.execute("UPDATE dispatcher_tasks SET lease_expires_at = ? WHERE task_id = ?",
                                 ('2000-01-01T00:00:00+00:00', task_id))
            elif drift == 'heartbeat':
                leases.heartbeat(case['store'], task_id, case['agent'])
                cycle.agent_worktree.heartbeat_worktree(case['cwd'], worktree=case['worktree'], owner=case['session'])
            else:
                registry = cycle.agent_worktree._default_registry_path(case['cwd'])
                with cycle.agent_worktree._locked_registry(registry) as payload:
                    row = payload['worktrees'][str(case['worktree'])]
                    if drift == 'registration_expired': row['expires_at'] = 1
                    elif drift == 'registration_owner': row['owner'] = 'other-session'
                    else: row['registration_epoch'] = 'f' * 32
        return original_pr(*args)

    monkeypatch.setattr(cycle.closure, '_pr', change_after_lineage)
    args = dict(issue=case['issue'], pr=case['pr'], cwd=case['cwd'], worktree=case['worktree'],
                workspace_root=f['layout'].root, agent=case['agent'], session=case['session'])
    if drift == 'heartbeat':
        assert adapter.verify(**args)['head'] == f['pr']['head_sha']
    else:
        with pytest.raises((cycle.CycleError, cycle.closure.ClosureError)):
            adapter.verify(**args)
    assert calls == 2


def test_operator_successor_refuses_registry_drift_during_final_dispatcher_read(production_path, monkeypatch):
    from scripts import verify_operator_successor as adapter

    f = production_path
    case = f['case']
    monkeypatch.setattr(recovery_module, '_verify_current_issue', lambda **kw: None)
    original = adapter._readonly_dispatcher
    calls = 0

    def drift_during_read(**kwargs):
        nonlocal calls
        calls += 1
        result = original(**kwargs)
        if calls == 2:
            registry = cycle.agent_worktree._default_registry_path(case['cwd'])
            payload = json.loads(registry.read_text())
            payload['worktrees'][str(case['worktree'])]['owner'] = 'other-session'
            registry.write_text(json.dumps(payload))
        return result

    monkeypatch.setattr(adapter, '_readonly_dispatcher', drift_during_read)
    with pytest.raises(cycle.CycleError):
        adapter.verify(issue=case['issue'], pr=case['pr'], cwd=case['cwd'], worktree=case['worktree'],
                       workspace_root=f['layout'].root, agent=case['agent'], session=case['session'])
    assert calls == 2


def test_operator_successor_refuses_lease_expiry_during_final_registry_read(production_path, monkeypatch):
    from scripts import verify_operator_successor as adapter

    f = production_path
    case = f['case']
    monkeypatch.setattr(recovery_module, '_verify_current_issue', lambda **kw: None)
    original = adapter._readonly_lifecycle
    calls = 0

    class FutureDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(hours=2)

    def advance_after_read(**kwargs):
        nonlocal calls
        result = original(**kwargs)
        calls += 1
        if calls == 2:
            monkeypatch.setattr(cycle.closure, 'datetime', FutureDatetime)
        return result

    monkeypatch.setattr(adapter, '_readonly_lifecycle', advance_after_read)
    with pytest.raises(cycle.closure.ClosureError, match='expired'):
        adapter.verify(issue=case['issue'], pr=case['pr'], cwd=case['cwd'], worktree=case['worktree'],
                       workspace_root=f['layout'].root, agent=case['agent'], session=case['session'])
    assert calls == 2


@pytest.mark.parametrize('consumer', ['native', 'review', 'adapter'])
def test_operator_consumers_refuse_poisoned_config_before_source_git(production_path, monkeypatch, consumer):
    from scripts import verify_operator_successor as adapter
    f = production_path
    case = f['case']
    config = case['cwd'].parent / 'agentic-pkm-mvp' / '.git/config'
    with config.open('a') as output:
        output.write('\n[include]\n  path = /tmp/unsupported-config\n')
    calls = []
    def source_git(*args, **kwargs):
        calls.append(args)
        raise AssertionError('source Git ran before configuration screening')
    monkeypatch.setattr(cycle.agent_worktree.git_hygiene, 'run_git', source_git)
    with pytest.raises(cycle.CycleError):
        if consumer == 'native':
            cycle.native_authority(f['layout'], f['pr'], f['entry'])
        elif consumer == 'review':
            cycle._add_transfer_review_context(f['layout'], f['entry'], f['pr'])
        else:
            adapter.verify(issue=case['issue'], pr=case['pr'], cwd=case['cwd'], worktree=case['worktree'],
                workspace_root=f['layout'].root, agent=case['agent'], session=case['session'])
    assert not calls


@pytest.mark.parametrize('failure', ['none', 'red_ci', 'head', 'stale_ack'])
def test_native_operator_proof_then_existing_merge_gates(production_path, monkeypatch, failure):
    from scripts import verify_operator_successor as adapter
    f = production_path
    case = f['case']
    monkeypatch.setattr(recovery_module, '_verify_current_issue', lambda **kw: None)
    if failure == 'head':
        f['live']['head']['sha'] = '0' * 40
    if failure == 'stale_ack':
        case['comments'][2]['body'] += ' '
    if failure == 'red_ci':
        f['controls']['ci'] = 1
    args = dict(issue=case['issue'], pr=case['pr'], cwd=case['cwd'], worktree=case['worktree'],
                workspace_root=f['layout'].root, agent=case['agent'], session=case['session'])
    if failure in ('head', 'stale_ack'):
        with pytest.raises(cycle.CycleError):
            adapter.verify(**args)
    else:
        assert adapter.verify(**args)['head'] == f['pr']['head_sha']
        if failure == 'red_ci':
            with pytest.raises(cycle.CycleError, match='current-head CI'):
                cycle._premerge(f['layout'], f['pr'], f['entry'], f['saved'])
        else:
            assert cycle._premerge(f['layout'], f['pr'], f['entry'], f['saved'])['head_sha'] == f['pr']['head_sha']


@pytest.mark.parametrize('drift', ['valid', 'forged', 'stale', 'other_pr'])
def test_operator_cli_real_unlinked_dispatcher_snapshot(production_path, monkeypatch, capsys, drift):
    from scripts import verify_operator_successor as adapter
    f = production_path
    case = f['case']
    task_id = case['receipt']['predecessor']['task_id']
    assert case['store'].get_task(task_id).linked_pr is None
    if drift == 'forged':
        case['comments'][2]['body'] += ' '
    if drift == 'stale':
        f['live']['head']['sha'] = '0' * 40
    if drift == 'other_pr':
        task = case['store'].get_task(task_id)
        task.linked_pr = '999999'
        case['store'].upsert_task(task)
    monkeypatch.chdir(case['cwd'])
    monkeypatch.setattr(sys, 'argv', ['verify_operator_successor', '--issue', str(case['issue']),
        '--pr', str(case['pr']), '--worktree', str(case['worktree']), '--workspace-root', str(f['layout'].root),
        '--agent', case['agent'], '--session', case['session']])
    status = adapter.main()
    output = json.loads(capsys.readouterr().out)
    assert status == (0 if drift == 'valid' else 1)
    assert output['ok'] is (drift == 'valid')
    if drift == 'valid':
        assert output['head'] == f['pr']['head_sha']
        assert output['task_pr_projection'] is None
        assert case['store'].get_task(task_id).linked_pr is None


def test_operator_proof_does_not_upgrade_old_database(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    from scripts import verify_operator_successor as adapter
    database = tmp_path / 'old.sqlite3'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE dispatcher_meta (key TEXT PRIMARY KEY, value TEXT)')
        conn.execute("INSERT INTO dispatcher_meta VALUES ('schema_version', '1')")
    before = database.read_bytes()
    monkeypatch.setattr(recovery_module, '_operator_dispatcher_paths', lambda *a, **k: SimpleNamespace(db_path=database))
    with pytest.raises(cycle.CycleError, match='schema is not current'):
        adapter._readonly_dispatcher(cwd=tmp_path, task_id='task')
    assert database.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ['old.sqlite3']


def test_operator_proof_does_not_create_registry_lock(production_path):
    from scripts import verify_operator_successor as adapter
    case = production_path['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    lock = registry.with_suffix(registry.suffix + '.lock')
    lock.unlink()
    before = registry.read_bytes()
    with pytest.raises(cycle.CycleError, match='registry or lock'):
        adapter._readonly_lifecycle(cwd=case['cwd'], worktree=case['worktree'], workspace_root=production_path['layout'].root,
                                    branch='codex/example', session=case['session'])
    assert not lock.exists()
    assert registry.read_bytes() == before


@pytest.mark.parametrize('problem', ['missing_registry', 'missing_row', 'malformed_row', 'branch_drift'])
def test_operator_uncertain_registry_is_screened_before_source_git(production_path, monkeypatch, problem):
    f = production_path
    case = f['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    if problem == 'missing_registry':
        registry.unlink()
    else:
        with cycle.agent_worktree._locked_registry(registry) as payload:
            rows = payload['worktrees']
            if problem == 'missing_row': rows.pop(str(case['worktree']))
            elif problem == 'malformed_row': rows[str(case['worktree'])] = 'invalid'
            else: rows[str(case['worktree'])]['branch'] = 'other'
    config = case['cwd'].parent / 'agentic-pkm-mvp' / '.git/config'
    with config.open('a') as output:
        output.write('\n[include]\n  path = /tmp/unsupported-config\n')
    calls = []
    def source_git(*args, **kwargs):
        calls.append(args)
        raise AssertionError('source Git ran before configuration screening')
    monkeypatch.setattr(cycle.agent_worktree.git_hygiene, 'run_git', source_git)
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f['layout'], f['pr'], f['entry'])
    assert not calls


@pytest.mark.parametrize('location', ['outside', 'model', 'prior_binding'])
def test_native_cli_refuses_extra_checkout_before_any_git_in_it(production_path, tmp_path, monkeypatch, capsys, location):
    from scripts import verify_operator_successor as adapter
    f = production_path
    case = f['case']
    extra = (f['layout'].root if location == 'model' else tmp_path) / 'foreign-checkout'
    extra.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(extra)], check=True)
    with (extra / '.git/config').open('a') as output:
        output.write('\n[include]\n  path = /tmp/unsupported-config\n')
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    with cycle.agent_worktree._locked_registry(registry) as payload:
        current = payload['worktrees'][str(case['worktree'])]
        payload['worktrees'][str(extra)] = {key: current[key] for key in
            ('branch', 'expires_at', 'generation', 'heartbeat_at', 'owner', 'registered_at', 'status')}
        payload['worktrees'][str(extra)]['path'] = str(extra)
        if location == 'prior_binding':
            payload['worktrees'][str(extra)]['branch'] = 'other'
            payload['worktrees'][str(extra)]['prior_bindings'] = [{'branch': 'codex/example', 'removed_at': 1.0}]
    delegate = cycle.agent_worktree.git_hygiene.run_git
    extra_calls = []
    def observed(args, cwd):
        if '-C' in args and args[args.index('-C') + 1] == str(extra):
            extra_calls.append(args)
            raise AssertionError('Git ran in the unqualified checkout')
        return delegate(args, cwd)
    monkeypatch.setattr(cycle.agent_worktree.git_hygiene, 'run_git', observed)
    monkeypatch.chdir(case['cwd'])
    monkeypatch.setattr(sys, 'argv', ['verify_operator_successor', '--issue', str(case['issue']),
        '--pr', str(case['pr']), '--worktree', str(case['worktree']), '--workspace-root', str(f['layout'].root),
        '--agent', case['agent'], '--session', case['session']])
    assert adapter.main() == 1
    assert json.loads(capsys.readouterr().out)['ok'] is False
    assert extra_calls == []



def test_native_cli_refuses_registry_symlink_before_read(production_path, monkeypatch, capsys):
    from scripts import verify_operator_successor as adapter
    f = production_path
    case = f['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    target = registry.with_name('symlink-target.json')
    registry.rename(target)
    registry.symlink_to(target)
    before = target.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail('path-based registry reader was invoked')
    monkeypatch.setattr(cycle.agent_worktree, '_read_registry', forbidden)
    monkeypatch.chdir(case['cwd'])
    monkeypatch.setattr(sys, 'argv', ['verify_operator_successor', '--issue', str(case['issue']),
        '--pr', str(case['pr']), '--worktree', str(case['worktree']), '--workspace-root', str(f['layout'].root),
        '--agent', case['agent'], '--session', case['session']])
    assert adapter.main() == 1
    assert json.loads(capsys.readouterr().out)['ok'] is False
    assert registry.is_symlink() and target.read_bytes() == before


@pytest.mark.parametrize('owner_state', ['old_owner', 'expired_same_owner'])
def test_native_cycle_qualifies_legacy_predecessor_before_git(production_path, monkeypatch, owner_state):
    f = production_path
    case = f['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    with cycle.agent_worktree._locked_registry(registry) as payload:
        row = copy.deepcopy(case['old_record'])
        if owner_state == 'expired_same_owner':
            row['owner'] = case['session']
        payload['worktrees'][str(case['worktree'])] = row
    config = case['cwd'].parent / 'agentic-pkm-mvp' / '.git/config'
    with config.open('a') as output:
        output.write('\n[include]\n  path = /tmp/unsupported-config\n')
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError('source Git ran before config qualification')
    monkeypatch.setattr(cycle.agent_worktree.git_hygiene, 'run_git', forbidden)
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f['layout'], f['pr'], f['entry'])
    assert not calls


def test_native_cycle_regular_current_owner_does_not_require_legacy_config(production_path, monkeypatch):
    f = production_path
    case = f['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    with cycle.agent_worktree._locked_registry(registry) as payload:
        row = payload['worktrees'][str(case['worktree'])]
        for key in ('operator_registration', 'prior_owner', 'previous_registration'):
            row.pop(key, None)
    monkeypatch.setattr(cycle.legacy_git_config, 'check', lambda **kwargs: pytest.fail('ordinary owner screened as legacy'))
    record, _ = cycle._lifecycle_owner(f['layout'], f['entry'], 'codex/example')
    assert record['owner'] == case['session']


@pytest.mark.parametrize('problem', ['missing_schema', 'pending_quarantine'])
def test_readonly_dispatcher_refuses_v6_reconciliation_without_writes(tmp_path, monkeypatch, problem):
    import sqlite3
    from types import SimpleNamespace
    from scripts import verify_operator_successor as adapter
    from tests.dispatcher.verification_helpers import ledger
    from tests.dispatcher.test_verification_dispatch import _write_deployed_v1_run
    state = ledger(tmp_path)
    if problem == 'pending_quarantine':
        _write_deployed_v1_run(state, supporting_issues=[])
    else:
        state.store.initialize()
        with sqlite3.connect(state.store.db_path) as conn:
            conn.execute('DROP TABLE verification_runs')
    database = state.store.db_path
    before = database.read_bytes()
    files = sorted(p.name for p in tmp_path.iterdir())
    monkeypatch.setattr(recovery_module, '_operator_dispatcher_paths', lambda *a, **k: SimpleNamespace(db_path=database))
    with pytest.raises(cycle.CycleError, match='schema is incomplete|requires quarantine'):
        adapter._readonly_dispatcher(cwd=tmp_path, task_id='task')
    assert database.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == files


def _add_unrelated_operator_history(case, tmp_path):
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    with cycle.agent_worktree._locked_registry(registry) as payload:
        original = payload['worktrees'][str(case['worktree'])]
        for index, status in enumerate(('active', 'released', 'complete')):
            row = copy.deepcopy(original)
            row['path'] = str(tmp_path / f'unrelated-{index}')
            row['branch'] = f'codex/unrelated-{index}'
            row['status'] = status
            payload['worktrees'][row['path']] = row


def test_native_operator_siblings_and_terminal_history_do_not_collide(production_path, tmp_path):
    f = production_path
    _add_unrelated_operator_history(f['case'], tmp_path)
    authority = cycle.native_authority(f['layout'], f['pr'], f['entry'])
    assert authority['head_sha'] == f['pr']['head_sha']
    cycle._add_transfer_review_context(f['layout'], f['entry'], f['pr'])
    assert cycle._premerge(f['layout'], f['pr'], f['entry'], f['saved'])['head_sha'] == f['pr']['head_sha']


def test_unrelated_native_owner_is_not_treated_as_operator(production_path, tmp_path, monkeypatch):
    f = production_path
    case = f['case']
    _add_unrelated_operator_history(case, tmp_path)
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    with cycle.agent_worktree._locked_registry(registry) as payload:
        row = payload['worktrees'][str(case['worktree'])]
        for key in ('operator_registration', 'prior_owner', 'previous_registration'):
            row.pop(key, None)
    monkeypatch.setattr(cycle.legacy_git_config, 'check', lambda **kwargs: pytest.fail('ordinary owner screened as legacy'))
    result, _ = cycle._lifecycle_owner(f['layout'], f['entry'], 'codex/example')
    assert result['owner'] == case['session']


def test_same_candidate_operator_conflict_refuses_before_checkout_git(production_path, tmp_path, monkeypatch):
    f = production_path
    case = f['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    extra = tmp_path / 'conflicting-checkout'
    extra.mkdir()
    with cycle.agent_worktree._locked_registry(registry) as payload:
        row = copy.deepcopy(payload['worktrees'][str(case['worktree'])])
        row['path'] = str(extra)
        payload['worktrees'][str(extra)] = row
    calls = []
    delegate = cycle.agent_worktree.git_hygiene.run_git
    def observed(args, cwd):
        if '-C' in args and args[args.index('-C') + 1] == str(extra):
            calls.append(args)
            raise AssertionError('Git ran in conflicting checkout')
        return delegate(args, cwd)
    monkeypatch.setattr(cycle.agent_worktree.git_hygiene, 'run_git', observed)
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f['layout'], f['pr'], f['entry'])
    assert calls == []


def test_native_owner_keeps_registry_lock_through_classification_and_binding(production_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    f = production_path
    case = f['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    entered, allow, writer_started, writer_entered = (threading.Event() for _ in range(4))
    original = cycle.legacy_git_config.check
    def paused_check(**kwargs):
        original(**kwargs)
        entered.set()
        if not allow.wait(10):
            raise AssertionError('test did not release classifier')
    monkeypatch.setattr(cycle.legacy_git_config, 'check', paused_check)
    def writer():
        writer_started.set()
        with cycle.agent_worktree._locked_registry(registry) as payload:
            writer_entered.set()
            payload['worktrees'][str(case['worktree'])]['owner'] = 'different-successor'
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(cycle._lifecycle_owner, f['layout'], f['entry'], 'codex/example')
        try:
            assert entered.wait(10)
            competing = pool.submit(writer)
            assert writer_started.wait(10)
            assert not writer_entered.wait(0.25)
        finally:
            allow.set()
        assert owner.result(timeout=10)[0]['owner'] == case['session']
        competing.result(timeout=10)
    assert writer_entered.is_set()


@pytest.mark.parametrize('problem', [
    'prior_owner', 'previous_registration', 'transfer_registration',
    'generation', 'registered_at', 'heartbeat_at', 'authority_since',
    'prior_binding_empty_branch', 'prior_binding_bad_time',
    'raw_sibling', 'sibling_empty_branch', 'released_incomplete',
])
def test_native_malformed_registry_qualifies_config_before_any_source_git(production_path, tmp_path, monkeypatch, problem):
    f = production_path
    case = f['case']
    registry = cycle.agent_worktree._default_registry_path(case['cwd'])
    with cycle.agent_worktree._locked_registry(registry) as payload:
        row = payload['worktrees'][str(case['worktree'])]
        for key in ('operator_registration', 'prior_owner', 'previous_registration'):
            row.pop(key, None)
        sibling = str(tmp_path / 'malformed-sibling')
        if problem == 'raw_sibling':
            payload['worktrees'][sibling] = 'not-a-record'
        elif problem == 'sibling_empty_branch':
            payload['worktrees'][sibling] = {'path': sibling, 'branch': ''}
        elif problem == 'released_incomplete':
            payload['worktrees'][sibling] = {'path': sibling, 'branch': 'codex/example', 'status': 'released'}
        elif problem == 'prior_binding_empty_branch':
            row['prior_bindings'] = [{'branch': '', 'removed_at': 1.0}]
        elif problem == 'prior_binding_bad_time':
            row['prior_bindings'] = [{'branch': 'another-branch', 'removed_at': 'not-a-time'}]
        elif problem in {'generation', 'registered_at', 'heartbeat_at', 'authority_since'}:
            row[problem] = 'not-valid'
        else:
            row[problem] = 'not-a-predecessor'
    config = case['cwd'].parent / 'agentic-pkm-mvp' / '.git/config'
    with config.open('a') as output:
        output.write('\n[include]\n  path = /tmp/unsupported-config\n')
    source_git = []
    checks = []
    original_check = cycle.legacy_git_config.check
    def checked(**kwargs):
        checks.append(1)
        return original_check(**kwargs)
    def forbidden(*args, **kwargs):
        source_git.append(args)
        raise AssertionError('source Git ran before config qualification')
    monkeypatch.setattr(cycle.legacy_git_config, 'check', checked)
    monkeypatch.setattr(cycle.agent_worktree.git_hygiene, 'run_git', forbidden)
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f['layout'], f['pr'], f['entry'])
    assert checks == [1] and source_git == []


def test_pinned_native_refuses_conflicting_authenticated_ack(recovery):
    data = copy.deepcopy(recovery)
    duplicate = copy.deepcopy(data['comments'][1])
    duplicate['id'] = 3
    body = json.loads(duplicate['body'])
    body['operator_reconciliation.v1']['successor_acknowledgment']['ack_attempt_id'] = '0' * 32
    duplicate['body'] = json.dumps(body)
    data['comments'].append(duplicate)
    with pytest.raises(cycle.CycleError, match='ambiguous'):
        cycle._operator_lineage(**data)

@pytest.mark.parametrize('extra_commit_path,wrong_bytes', [(False, False), (True, False), (False, True)])
def test_dirty_first_patch_requires_exact_complete_delta(tmp_path, monkeypatch, extra_commit_path, wrong_bytes):
    from app.builderops import legacy_git_config
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-q')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    names = ('tests/properties/_machinery.py', 'tests/properties/test_guard_at_seam.py')
    (tmp_path / 'tests/properties').mkdir(parents=True)
    for name in names:
        (tmp_path / name).write_text('base\n')
    (tmp_path / 'other').write_text('base\n')
    git('add', '.')
    git('commit', '-qm', 'base')
    parent = git('rev-parse', 'HEAD')
    blobs = {name: git('rev-parse', f'HEAD:{name}') for name in names}
    for name in names:
        (tmp_path / name).write_text(f'preserved {name}\n')
    hashes = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in names}
    if wrong_bytes:
        (tmp_path / names[0]).write_text('different\n')
    git('add', *names)
    if extra_commit_path:
        (tmp_path / 'other').write_text('staged extra\n')
        git('add', 'other')
    git('commit', '-qm', 'first patch')
    head = git('rev-parse', 'HEAD')
    # Preserved unrelated staging after the first commit is not discarded or treated as committed.
    (tmp_path / 'other').write_text('later staged material\n')
    git('add', 'other')
    material = {'tree': git('rev-parse', f'{parent}^{{tree}}'), 'index_sha256': 'a' * 64,
                'index_blobs': blobs, 'file_sha256': hashes, 'patch_sha256': 'b' * 64,
                'backup': str(tmp_path / 'backup')}
    candidate = {'head': parent, 'clean': False, 'dirty_material': material}
    monkeypatch.setattr(legacy_git_config, 'check_host_config', lambda: None)
    monkeypatch.setattr(legacy_git_config, 'check', lambda **kwargs: None)
    monkeypatch.setattr(cycle.legacy_owner_recovery, '_git_read', REAL_GIT_READ)
    if extra_commit_path or wrong_bytes:
        with pytest.raises(cycle.CycleError):
            cycle._verify_dirty_first_patch(cwd=tmp_path, worktree=tmp_path, candidate=candidate, head=head)
    else:
        cycle._verify_dirty_first_patch(cwd=tmp_path, worktree=tmp_path, candidate=candidate, head=head)
        assert git('diff', '--cached', '--name-only') == 'other'
