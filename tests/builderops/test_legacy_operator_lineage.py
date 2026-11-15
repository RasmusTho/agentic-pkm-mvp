from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.builderops import openhands_pr_cycle as cycle
from app.builderops import legacy_owner_recovery as recovery_module
from app.dispatcher import leases
from app.dispatcher.events import claim_event_digest, event_history_digest
from tests.builderops.test_openhands_pr_cycle import setup as setup_worker
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
    criteria = cycle.closure._acceptance_criteria(issue_body, repo_root=checkout)
    saved = {'review_operation': 'operation', 'conversation_provenance': {'reviewer': 'conversation'},
             'execution_proof': {'operation_id': 'operation', 'engine': entry['engine'], 'model': entry['model'],
                 'auth': 'chatgpt', 'source': 'native-session-metadata', 'native_session_id': 'native',
                 'conversation_id': 'conversation', 'timestamp': '2026-11-15T08:00:00Z', 'effort': 'high'},
             'review': {'verdict': 'pass', 'findings': [], 'covered_sources': [],
                        'scope_assessment': {'acceptance': 'covered', 'verify_coverage': 'covered', 'limitations': []},
                        'owner_doc': {'outcome': 'no_change', 'inspected_paths': ['docs/owner'], 'rationale': 'reviewed'},
                        'closing_assessments': {str(case['issue']): {'acceptance': 'covered', 'verify_coverage': 'covered',
                            'limitations': [], 'criteria': {criteria[0]['criterion_sha256']:
                                {'assessment': 'covered', 'rationale': 'verified'}}}}},
             'verification': {'passed': True, 'head_sha': head, 'targets': entry['verify_targets']}}
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
    rereview = copy.deepcopy(f['saved'])
    rereview['review_operation'] = 'new-review'
    rereview['execution_proof']['operation_id'] = 'new-review'
    rereview['execution_proof']['conversation_id'] = 'new-conversation'
    rereview['conversation_provenance']['reviewer'] = 'new-conversation'
    assert cycle._premerge(f['layout'], updated, f['entry'], rereview)['head_sha'] == updated['head_sha']


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
