"""Default candidate binding with real retained source and publisher Git."""

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_epic_workspace_lifecycle import _git
from tests.builderops.test_openhands_candidate_commit import fixture
from tests.builderops.openhands_peer_test_support import registered_peer


def bind(data):
    layout, _, _, _, pr, entry, saved, mapping, _ = data
    with cycle._single_advancement(layout), ew._worker_lifecycle_lock(layout, 'w-a'):
        return cycle._bind_stopped_repair_candidate(layout, 'w-a', pr, entry, saved, mapping)


def test_default_binding_commits_projected_tree_and_replays(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    row = bind(data)
    candidate = data[6]['repair_candidate']
    assert row['action'] == 'awaiting-candidate-review'
    assert candidate['source_kind'] == 'versioned_projection'
    assert candidate['tree'] != candidate['checkpoint_tree']
    assert candidate['candidate_head'] == _git(data[2], 'rev-parse', 'HEAD')
    assert candidate['tree'] == _git(data[2], 'rev-parse', 'HEAD^{tree}')
    assert (data[1] / 'private.cache').read_text() == 'ignored unique work\n'
    assert not (data[2] / 'private.cache').exists()
    data[6].clear()
    data[6].update(cycle._find(data[0], 10, 'fixture-identity'))
    assert bind(data)['action'] == 'awaiting-candidate-review'
    assert data[6]['repair_candidate']['candidate_head'] == candidate['candidate_head']
    assert _git(data[2], 'rev-list', '--count', f"{data[4]['head_sha']}..HEAD") == '1'


def test_binding_refuses_drift_and_keeps_publisher_work(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    (data[2] / 'unrelated.txt').write_text('retain me\n')
    with pytest.raises(cycle.CycleError, match='unrelated'):
        bind(data)
    assert (data[2] / 'unrelated.txt').read_text() == 'retain me\n'
    assert _git(data[2], 'rev-parse', 'HEAD') == data[4]['head_sha']


def test_projection_revalidation_rejects_source_drift(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    bind(data)
    (data[1] / 'private.cache').write_text('changed retained work\n')
    with ew._worker_lifecycle_lock(data[0], 'w-a'):
        with pytest.raises((cycle.CycleError, ew.EpicWorkspaceError)):
            cycle._verify_repair_candidate_projection_locked(data[0], 'w-a', data[4], data[6], data[7],
                                                              data[6]['repair_candidate'])
    assert (data[1] / 'private.cache').read_text() == 'changed retained work\n'


def advance_fixture(tmp_path, capsys, monkeypatch, *, test_source="def test_example(): pass\n"):
    import json
    from app.builderops import epic_run_state, publication

    data = fixture(tmp_path, capsys, monkeypatch, test_source=test_source)
    layout, _, _, _, original, entry, saved, mapping, _ = data
    entry.update(head_sha=original['head_sha'], native_session_owned=True, engine='codex',
                 model='gpt-6.1-terra', verify_targets=['tests/example.py::test_example'], test_venv='/synthetic')
    issue = {'number': 6617, 'state': 'open', 'title': 'Repair',
             'body': original['governing_issue']['body'], 'labels': [{'name': 'agent:in-progress'}]}

    def fetch(path, timeout):
        if '/pulls?' in path:
            obj = [{'number': 10}]
        elif '/pulls/10/reviews' in path:
            obj = []
        elif '/pulls/10' in path:
            obj = {'number': 10, 'state': 'open', 'title': original['title'], 'body': original['body'],
                   'draft': False, 'labels': [], 'head': {'sha': original['head_sha'],
                   'repo': {'full_name': cycle.completion.REPOSITORY}},
                   'base': {'sha': original['head_sha'], 'ref': 'main'}}
        elif '/issues/6617' in path:
            obj = issue
        else:
            raise AssertionError(path)
        return 200, json.dumps(obj).encode()

    previous_executor = cycle.SubprocessExecutor

    class External(previous_executor):
        def run(self, argv, *, cwd, input_text=None):
            if argv[0] == 'gh' and 'Accept: application/vnd.github.v3.diff' in argv:
                return publication.CommandResult(tuple(argv), 0, 'diff --git a/README.md b/README.md\n', '')
            return super().run(argv, cwd=cwd, input_text=input_text)

    monkeypatch.setattr(cycle, 'SubprocessExecutor', External)
    monkeypatch.setattr(cycle, '_api_pages', lambda executor, cwd, path:
                        [{'filename': 'README.md', 'patch': '@@ -1 +1 @@'}] if '/files' in path else [])
    def api(executor, cwd, repo, method, path):
        if not path:
            return {'full_name': cycle.completion.REPOSITORY, 'default_branch': 'main'}
        if path.startswith('/git/trees/'):
            return {'truncated': False, 'tree': []}
        if path == '/branches/main/protection':
            return {}
        if path.startswith('/rulesets?'):
            return []
        raise AssertionError(path)
    monkeypatch.setattr(cycle.closure, '_api', api)
    observed = cycle.observation.collect(fetch)['observations'][0]
    observed.update(route='native', owner='unknown', effect_outcome='none', review_outcome='missing',
                    check_config={'verify_targets': entry['verify_targets'], 'test_venv': entry['test_venv']})
    observed['review_context'], observed['review_material'] = cycle._review_context(observed)
    identity = cycle.completion.work_identity(observed)
    report = {'synthetic': 'review'}
    report_sha = cycle._digest(report)
    operation = 'pr-completion-' + cycle._digest({'identity': identity, 'request': 'repair-author',
                                                  'report_sha256': report_sha})
    conversation = {**mapping['conversation'], 'operation_id': operation}
    ew._record_worker(layout, 6617, conversation=conversation)
    mapping = cycle._mapping(layout, 'w-a')
    saved.update(identity=identity, repair_operation=operation, repair_engine='codex',
                 repair_model='gpt-6.1-terra', review=report, repair_review_sha256=report_sha,
                 repair_execution_proof={**saved['repair_execution_proof'], 'operation_id': operation},
                 repair_stop_intent={**saved['repair_stop_intent'], 'assignment': ew.assignment_of(mapping)})
    saved['repair_result'].update(identity=identity, operation_id=operation, native_proof=saved['repair_execution_proof'])
    def update(state):
        state['compact_receipts'] = [r for r in state['compact_receipts'] if r.get('kind') != 'pr_cycle']
        state['dispatch_decisions'].append({'operation_id': operation, 'request': 'repair-author',
                                           'repository': cycle.completion.REPOSITORY, 'number': 10,
                                           'route': 'native', 'identity': identity, 'outcome': 'unknown',
                                           'review_sha256': report_sha})
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=update,
                                         expected_epic_issue_number=layout.epic)
    cycle._save(layout, saved, expected_worker='w-a', expected_assignment=mapping)
    return data, fetch, identity


def test_advance_default_prepares_and_restarts_same_candidate(tmp_path, capsys, monkeypatch):
    data, fetch, identity = advance_fixture(tmp_path, capsys, monkeypatch)
    result = cycle.advance(data[0], [data[5]], fetch=fetch)
    assert result['results'][0]['action'] == 'awaiting-candidate-review', result
    candidate = cycle._find(data[0], 10, identity)['repair_candidate']
    assert candidate['candidate_head'] == _git(data[2], 'rev-parse', 'HEAD')
    again = cycle.advance(data[0], [data[5]], fetch=fetch)
    # This legacy fixture records a diagnostic author without native execution proof.
    # The default cycle now holds that source before creating a review worker.
    assert again['results'][0]['action'] == 'wait', again
    assert 'native execution proof' in again['results'][0]['reason']
    assert cycle._find(data[0], 10, identity)['repair_candidate'] == candidate
    assert _git(data[2], 'rev-list', '--count', f"{data[4]['head_sha']}..HEAD") == '1'


def test_real_publisher_checks_projected_source_before_review_gate(tmp_path, capsys, monkeypatch):
    import json
    from app.builderops import openhands_delivery as delivery, publication

    data = fixture(tmp_path, capsys, monkeypatch)
    bind(data)
    layout, _, publisher, _, pr, entry, saved, _, _ = data
    candidate = saved['repair_candidate']
    old, head = pr['head_sha'], candidate['candidate_head']
    issue = {'number': 6617, 'state': 'open', 'title': 'Repair', 'body': pr['governing_issue']['body'],
             'labels': [{'name': 'agent:in-progress'}]}
    review = tmp_path / 'synthetic-review.txt'
    review.write_text(f'Synthetic independent review of {head}.\n')
    verify = tmp_path / 'synthetic-verify.txt'
    verify.write_text('1 passed in 0.1s\n')
    evidence = tmp_path / 'synthetic-evidence.json'
    evidence.write_text(json.dumps({'version': 1, 'repository': cycle.completion.REPOSITORY,
        'issue': 6617, 'base_sha': old, 'head_sha': head, 'risk_surfaces': ['concurrency', 'state-machine'],
        'review': {'reviewer': 'synthetic-reviewer', 'verdict': 'pass', 'head_sha': head,
                   'blocking_findings': [], 'evidence': {'path': str(review)}},
        'verification': [{'target': 'tests/example.py::test_example', 'head_sha': head,
                          'result': 'pass', 'evidence': {'path': str(verify)}}]}))
    bindir = tmp_path / 'fake-network-bin'
    bindir.mkdir()
    gh = bindir / 'gh'
    gh.write_text('#!/bin/sh\nexit 1\n')
    gh.chmod(0o755)
    monkeypatch.setenv('PATH', str(bindir) + ':' + __import__('os').environ['PATH'])
    calls = []

    class Network(publication.SubprocessExecutor):
        def run(self, argv, *, cwd, input_text=None):
            args = tuple(argv)
            calls.append(args)
            if args[:3] == ('git', 'remote', 'get-url'):
                return publication.CommandResult(args, 0, f'https://github.com/{cycle.completion.REPOSITORY}.git\n', '')
            if args[:2] == ('git', 'ls-remote'):
                return publication.CommandResult(args, 0, f'{old}\t{args[-1]}\n', '')
            if args[:2] == ('git', 'push'):
                return publication.CommandResult(args, 1, '', 'synthetic network blocked')
            if args[:2] == ('gh', 'api'):
                endpoint = args[6]
                if endpoint.endswith('/issues/6617'):
                    obj = issue
                elif endpoint.endswith('/git/ref/heads/main'):
                    obj = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': old}}
                elif endpoint.endswith('/pulls'):
                    obj = [{'number': 10, 'state': 'open', 'draft': False, 'merged_at': None,
                            'title': pr['title'], 'body': pr['body'], 'html_url': 'https://example.invalid/pull/10',
                            'head': {'sha': old, 'ref': 'b/a', 'repo': {'full_name': cycle.completion.REPOSITORY}},
                            'base': {'sha': old, 'ref': 'main', 'repo': {'full_name': cycle.completion.REPOSITORY}}}]
                else:
                    raise AssertionError(args)
                return publication.CommandResult(args, 0, json.dumps(obj), '')
            return super().run(argv, cwd=cwd, input_text=input_text)

    # The source check happens within the real full publisher snapshot. A real
    # downstream gate may stop because this synthetic repository has no PR.
    entry.update(head_sha=old, native_session_owned=True)
    try:
        delivery.publish_native_repair(layout, pr, entry, saved['identity'],
                                       ['README.md', 'remove.py', 'new.py', 'link.py'], evidence, executor=Network())
    except (cycle.CycleError, delivery.DeliveryError, publication.PublicationCommandError,
            publication.PublicationRefusal) as exc:
        assert any('agent_workspace_preflight.sh' in arg for cmd in calls for arg in cmd), str(exc)
    assert (data[1] / 'private.cache').read_text() == 'ignored unique work\n'
    assert not (publisher / 'private.cache').exists()
    (data[1] / 'private.cache').write_text('changed after stop\n')
    prior_pushes = sum(cmd[:2] == ('git', 'push') for cmd in calls)
    with pytest.raises((cycle.CycleError, ew.EpicWorkspaceError, delivery.DeliveryError)):
        delivery.publish_native_repair(layout, pr, entry, saved['identity'],
                                       ['README.md', 'remove.py', 'new.py', 'link.py'], evidence, executor=Network())
    assert sum(cmd[:2] == ('git', 'push') for cmd in calls) == prior_pushes


def test_explicit_candidate_with_ignored_custody_uses_real_projection(tmp_path, capsys, monkeypatch):
    from app.builderops import publication
    from tests.builderops.test_openhands_candidate_commit import run_commit

    data = fixture(tmp_path, capsys, monkeypatch)
    prepared = run_commit(data)
    data[5]['repair_publication'] = {'candidate_head': prepared['head']}
    external = cycle.SubprocessExecutor

    class Hybrid(external):
        def run(self, argv, *, cwd, input_text=None):
            if argv[0] == 'git':
                return publication.SubprocessExecutor().run(argv, cwd=cwd, input_text=input_text)
            return super().run(argv, cwd=cwd, input_text=input_text)

    monkeypatch.setattr(cycle, 'SubprocessExecutor', Hybrid)
    assert bind(data)['action'] == 'awaiting-candidate-review'
    assert data[6]['repair_candidate']['source_kind'] == 'versioned_projection_explicit'
    assert data[6]['repair_candidate']['candidate_head'] == prepared['head']
    assert (data[1] / 'private.cache').read_text() == 'ignored unique work\n'


def test_default_binding_refuses_foreign_claim(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    data[8]['holder'] = 'foreign'
    with pytest.raises(cycle.CycleError, match='lease|owner'):
        bind(data)
    assert _git(data[2], 'rev-parse', 'HEAD') == data[4]['head_sha']
    assert (data[2] / 'publisher.cache').read_text() == 'publisher ignored work\n'


def test_unknown_projected_publication_does_not_block_actual_peer_review(tmp_path, capsys, monkeypatch):
    """Reconcile a prior unknown push before admission filtering while a peer starts."""
    import json
    import subprocess

    from app.builderops import publication
    from tests.builderops.test_epic_workspace_openhands import FakeAgentServer

    real_lifecycle_owner = cycle._lifecycle_owner
    data, fetch, identity = advance_fixture(tmp_path, capsys, monkeypatch)
    layout, _, publisher, engine, pr, entry, _, _, _ = data
    assert cycle.advance(layout, [entry], fetch=fetch)['results'][0]['action'] == 'awaiting-candidate-review'
    saved = cycle._find(layout, 10, identity)
    candidate = saved['repair_candidate']
    old, head = pr['head_sha'], candidate['candidate_head']
    original = cycle.observation.collect(fetch)['observations'][0]
    saved['repair_publication_original_pr'] = original
    saved['repair_publication'] = {
        'state': 'update_pushing', 'operation_id': 'branch_push-1', 'pr_number': 10,
        'previous_candidate': {'issue': 6617, 'branch': 'b/a', 'base': old, 'head': old,
                               'title': pr['title'], 'body_sha256': cycle.hashlib.sha256(pr['body'].encode()).hexdigest()},
        'candidate': {'head': head, 'identity': identity}, 'binding_sha256': 'synthetic-prior-binding',
    }
    ew._record_worker(layout, 6617, publication_ops=[{'id': 'branch_push-1', 'kind': 'branch_push',
        'branch': 'b/a', 'expect_sha': head, 'status': 'intended'}])
    cycle._save(layout, saved)
    server = FakeAgentServer()
    ew.create_worker(layout, 'peer', issue=6619, branch='b/peer', next_action='review peer', runner=engine)
    with ew._worker_lifecycle_lock(layout, 'peer'):
        ew._start_openhands_worker_locked(layout, 'peer', runner=engine, http=server)
    peer_mapping = cycle._mapping(layout, 'peer')
    peer_id = peer_mapping['container_id']
    previous_command = cycle._command

    def command(argv, *, timeout):
        if argv[:2] == ['docker', 'inspect'] and argv[-1] == peer_id:
            return subprocess.CompletedProcess(argv, 0, json.dumps([{
                'Id': peer_id, 'Name': '/' + layout.container_name('peer'), 'State': {'Running': True},
                'Config': {'Labels': {ew.LABEL_EPIC: str(layout.epic), ew.LABEL_WORKER: 'peer'}}}]), '')
        return previous_command(argv, timeout=timeout)

    monkeypatch.setattr(cycle, '_command', command)
    original_pr = cycle.closure._pr
    original_issue = cycle.closure._issue
    original_refs = cycle.closure._closing_issue_references
    peer_issue = {'number': 6619, 'state': 'open', 'title': 'Peer',
                  'body': pr['governing_issue']['body'], 'labels': [{'name': 'agent:in-progress'}]}
    def get_pr(executor, cwd, repo, number):
        if number == 9:
            return {'number': 9, 'state': 'open', 'draft': False, 'title': 'Peer',
                    'body': 'Governing-Issue: #6619\nFixes #6619\n', 'labels': [],
                    'head': {'sha': old, 'ref': 'b/peer', 'repo': {'full_name': cycle.completion.REPOSITORY}},
                    'base': {'sha': old, 'ref': 'main'}}
        return original_pr(executor, cwd, repo, number)
    monkeypatch.setattr(cycle.closure, '_pr', get_pr)
    monkeypatch.setattr(cycle.closure, '_issue', lambda executor, cwd, repo, number:
                        peer_issue if number == 6619 else original_issue(executor, cwd, repo, number))
    monkeypatch.setattr(cycle.closure, '_closing_issue_references', lambda executor, cwd, repo, number:
                        [6619] if number == 9 else original_refs(executor, cwd, repo, number))
    def peer_fetch(path, timeout):
        if '/pulls?' in path:
            obj = [{'number': 9}, {'number': 10}]
        elif '/pulls/9/reviews' in path:
            obj = []
        elif path.endswith('/pulls/9'):
            obj = get_pr(None, None, None, 9)
        elif path.endswith('/issues/6619'):
            obj = peer_issue
        elif path.endswith('/pulls/10'):
            status, body = fetch(path, timeout)
            obj = json.loads(body)
            obj['head']['sha'] = head
        else:
            return fetch(path, timeout)
        return 200, json.dumps(obj).encode()
    calls = []
    class Network(publication.SubprocessExecutor):
        def run(self, argv, *, cwd, input_text=None):
            args = tuple(argv)
            calls.append(args)
            if args[:3] == ('git', 'remote', 'get-url'):
                return publication.CommandResult(args, 0, f'https://github.com/{cycle.completion.REPOSITORY}.git\n', '')
            if args[:2] == ('git', 'ls-remote'):
                remote = old if args[-1] == 'refs/heads/main' else head
                return publication.CommandResult(args, 0, f'{remote}\t{args[-1]}\n', '')
            if args[:2] == ('git', 'push'):
                raise AssertionError('unknown publication must not be pushed again')
            if args[:2] == ('gh', 'api'):
                endpoint = args[6]
                if endpoint.endswith('/pulls'):
                    obj = [{'number': 10, 'state': 'open', 'draft': False, 'merged_at': None,
                        'title': pr['title'], 'body': pr['body'],
                        'head': {'sha': head, 'ref': 'b/a', 'repo': {'full_name': cycle.completion.REPOSITORY}},
                        'base': {'sha': old, 'ref': 'main', 'repo': {'full_name': cycle.completion.REPOSITORY}}}]
                elif endpoint.endswith('/git/ref/heads/main'):
                    obj = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': old}}
                elif endpoint.endswith('/issues/6617'):
                    obj = {'number': 6617, 'state': 'open', 'title': 'Repair',
                           'body': pr['governing_issue']['body'], 'labels': [{'name': 'agent:in-progress'}]}
                else:
                    raise AssertionError(args)
                return publication.CommandResult(args, 0, json.dumps(obj), '')
            return super().run(argv, cwd=cwd, input_text=input_text)
    candidate_entry = {**entry, 'repair_publication': {'paths': ['README.md', 'remove.py', 'new.py', 'link.py'],
                        'evidence_file': str(tmp_path / 'missing-evidence.json')}}
    peer_entry = registered_peer(tmp_path, monkeypatch, layout, entry, real_lifecycle_owner)
    admission = tmp_path / 'admissions.json'
    admission.touch(mode=0o600, exist_ok=False)
    admission.write_text(json.dumps({'admissions': [peer_entry, candidate_entry]}))
    result = cycle.advance(layout, admission, fetch=peer_fetch, http=server, publisher_executor=Network())
    assert result['results'][0]['action'] == 'independent-review', result
    assert result['results'][1]['action'] == 'wait', result
    assert len([call for call in server.calls if call[0] == 'POST']) == 1
    assert not any(call[:2] == ('git', 'push') for call in calls)
    assert cycle._find(layout, 10, identity)['repair_publication']['state'] == 'update_pushed'
    assert cycle._mapping(layout, 'w-a')['publication_ops'][0]['status'] == 'confirmed'
    assert _git(publisher, 'rev-parse', 'HEAD') == head
    result = cycle.advance(layout, admission, fetch=peer_fetch, http=server, publisher_executor=Network())
    assert result['results'][1]['action'] == 'wait', result
    assert len([call for call in server.calls if call[0] == 'POST']) == 1
    assert not any(call[:2] == ('git', 'push') for call in calls)
