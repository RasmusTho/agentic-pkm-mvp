"""Candidate Verify through production OpenHands Bash lifecycle, with synthetic ports."""

import json
import os
import subprocess
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from app.builderops import openhands_pr_cycle as cycle
from app.builderops import epic_workspace as ew
from tests.builderops.test_openhands_candidate_repair_v4 import finding_ready
from tests.builderops.test_openhands_candidate_result_v3 import prepared


def repaired_review(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, home, _, _ = finding_ready(tmp_path, capsys, monkeypatch)
    layout, _, publisher, engine, pr, entry, _, _, _ = data

    def advance():
        return cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=home)['results'][0]

    def native_port(worker, cid, session):
        container_id = cycle._mapping(layout, worker)['container_id']
        original = cycle._command

        def command(argv, *, timeout):
            if argv[:2] == ['docker', 'inspect'] and worker in engine.containers and argv[-1] == container_id:
                return subprocess.CompletedProcess(argv, 0, json.dumps([{'Id': container_id, 'Image': 'sha256:image',
                    'Name': '/' + layout.container_name(worker), 'State': {'Running': True}, 'Config': {
                        'Image': ew.OPENHANDS_IMAGE, 'Env': [], 'Labels': {
                            ew.LABEL_EPIC: str(layout.epic), ew.LABEL_WORKER: worker}}}]), '')
            if argv[1:3] == ['image', 'inspect']:
                return subprocess.CompletedProcess(argv, 0, '[{"Id":"sha256:image"}]', '')
            if argv[1:3] == ['exec', container_id]:
                if argv[-2:] == ['login', 'status']:
                    value = 'Logged in using ChatGPT'
                elif argv[-2:] == ['codex', cid]:
                    value = json.dumps({'engine': 'codex', 'conversation_id': cid, 'session_id': session,
                        'model': 'gpt-6.1-terra', 'effort': 'ultra', 'timestamp': '2026-11-15T00:00:00Z'})
                else:
                    value = 'route-ok\n'
                return subprocess.CompletedProcess(argv, 0, value, '')
            return original(argv, timeout=timeout)

        monkeypatch.setattr(cycle, '_command', command)
        server.conversations[cid].update(execution_status='finished',
            agent={'kind': 'ACPAgent', 'acp_server': 'codex', 'acp_model': 'gpt-6.1-terra'},
            current_model_id='gpt-6.1-terra', current_effort='ultra', available_efforts=[{'value': 'ultra'}],
            agent_state={'acp_session_id': session, 'acp_session_cwd': '/workspace'})
        server.events = [{'kind': 'MessageEvent', 'source': 'agent'}]

    author = advance()
    assert author['action'] == 'candidate-repair-author', author
    (layout.checkout(author['worker']) / 'new.py').write_text('repaired candidate\n')
    native_port(author['worker'], author['conversation_id'], 'repair-native')
    assert advance()['action'] == 'awaiting-candidate-review'
    reviewer = advance()
    assert reviewer['action'] == 'candidate-review-dispatched', reviewer
    native_port(reviewer['worker'], reviewer['conversation_id'], 'fresh-review-native')
    saved = cycle._find(layout, 10, identity)
    criterion = cycle.closure._acceptance_criteria(pr['governing_issue']['body'], repo_root=publisher)[0]['criterion_sha256']
    report = {'report_contract': cycle.REPORT_CONTRACT, 'identity': saved['candidate_review_dispatch']['binding_sha256'],
        'head_sha': saved['repair_candidate']['candidate_head'], 'verdict': 'pass', 'findings': [],
        'verify_targets': entry['verify_targets'], 'covered_sources': [],
        'scope_assessment': {'acceptance': 'covered', 'verify_coverage': 'covered', 'limitations': []},
        'owner_doc': {'outcome': 'no_change', 'inspected_paths': ['README.md'], 'rationale': 'unchanged'},
        'closing_assessments': {'6617': {'acceptance': 'covered', 'verify_coverage': 'covered', 'limitations': [],
            'criteria': {criterion: {'assessment': 'covered', 'rationale': 'checked'}}}}}
    server.final_responses[reviewer['conversation_id']] = json.dumps(report)
    return data, fetch, identity, server, home


def verify_fixture(tmp_path, capsys, monkeypatch, *, fail=False, lose=False, lose_output=False, repaired=False,
                   missing_api=False):
    source = 'def test_example(): assert False\n' if fail else 'def test_example(): pass\n'
    if repaired:
        data, fetch, identity, server, home = repaired_review(tmp_path, capsys, monkeypatch)
    else:
        data, fetch, identity, server, home, _, _, _, _ = prepared(tmp_path, capsys, monkeypatch, test_source=source)
    layout, _, publisher, _, pr, entry, _, _, _ = data
    venv = tmp_path / 'approved-venv'
    (venv / 'bin').mkdir(parents=True)
    (venv / 'bin/python').symlink_to('/usr/local/bin/python3.12')
    (venv / 'pyvenv.cfg').write_text('version = 3.12.0\ninclude-system-site-packages = true\n')
    entry['test_venv'] = str(venv)
    events = []
    calls = []
    lost = [lose]
    lost_result = [lose_output]

    def http(method, port, key, path, body, timeout):
        if path.startswith('/bash/'):
            calls.append((method, path, body))
            if missing_api:
                return 404, None
            if method == 'POST' and path == '/bash/start_bash_command':
                saved = cycle._find(layout, 10, identity)
                intent = saved['candidate_verification']
                assert intent['commands'][-1]['state'] == 'sent_unknown'
                worker = intent['worker']
                mounts = [data[3].runs()[-1][i + 1] for i, value in enumerate(data[3].runs()[-1]) if value == '--mount']
                reviewer = saved['candidate_review_dispatch']['worker']
                assert any(m == f'type=bind,source={venv},target=/opt/pr-cycle-venv,readonly' for m in mounts)
                assert all(str(data[1]) not in m and str(publisher) not in m and str(layout.checkout(reviewer)) not in m
                           and '/run/codex-home' not in m for m in mounts)
                source_worker = saved.get('repair_worker', 'w-a')
                assert all(str(layout.checkout(source_worker)) not in m for m in mounts)
                cid = uuid.uuid4().hex
                event = {'kind': 'BashCommand', 'id': cid, **body}
                events.append(event)
                cmd = body['command'].replace('/opt/pr-cycle-venv', str(venv)).replace('/workspace', str(layout.checkout(worker)))
                result = subprocess.run(cmd, shell=True, cwd=layout.checkout(worker), capture_output=True, text=True,
                                        env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}, timeout=30)
                events.append({'kind': 'BashOutput', 'id': str(uuid.uuid4()), 'command_id': cid,
                               'order': 0, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
                if lost[0]:
                    lost[0] = False
                    raise OSError('synthetic lost create response')
                return 200, event
            if method == 'GET' and path.startswith('/bash/bash_events/search?'):
                query = parse_qs(urlsplit(path).query)
                kind = query.get('kind__eq', [''])[0]
                command_id = query.get('command_id__eq', [None])[0]
                if kind == 'BashOutput' and lost_result[0]:
                    lost_result[0] = False
                    return 503, None
                return 200, {'items': [e for e in events if e['kind'] == kind and
                            (command_id is None or uuid.UUID(e['command_id']) == uuid.UUID(command_id))],
                             'next_page_id': None}
            raise AssertionError((method, path))
        return server(method, port, key, path, body, timeout)

    def advance():
        return cycle.advance(layout, [entry], fetch=fetch, http=http, codex_home=home)['results'][0]

    assert advance()['action'] == 'awaiting-candidate-verify'
    return data, fetch, identity, server, home, http, advance, events, calls


def test_real_pytest_produces_full_validator_accepted_artifact(tmp_path, capsys, monkeypatch):
    data, _, identity, _, _, _, advance, events, calls = verify_fixture(tmp_path, capsys, monkeypatch, lose=True)
    result = advance()
    # Direct in-memory admissions intentionally cannot refresh a publication admission.
    assert result['action'] == 'wait', result
    saved = cycle._find(data[0], 10, identity)
    verify = saved['candidate_verification']
    assert verify['state'] == 'artifact_ready', result
    assert verify['commands'][0]['exit_code'] == 0
    assert '1 passed' in verify['commands'][0]['stdout']
    assert verify['commands'][0]['output_event_ids'] and verify['commands'][0]['output_events_sha256']
    assert len([c for c in calls if c[0] == 'POST']) == 1
    assert len([e for e in events if e['kind'] == 'BashCommand']) == 1
    receipt = json.loads(cycle.Path(verify['evidence_file']).read_text())
    assert receipt['head_sha'] == saved['repair_candidate']['candidate_head']
    assert receipt['verification'][0]['result'] == 'pass'
    assert cycle._mapping(data[0], verify['worker'])['state'] == 'stopped_verified'


def test_failed_real_pytest_holds_without_publication(tmp_path, capsys, monkeypatch):
    data, _, identity, _, _, _, advance, _, _ = verify_fixture(tmp_path, capsys, monkeypatch, fail=True)
    result = advance()
    assert result['action'] == 'candidate-verify-failed', result
    saved = cycle._find(data[0], 10, identity)
    assert saved['candidate_verification']['commands'][0]['exit_code'] == 1
    assert 'tests/example.py::test_example' in saved['candidate_verification']['next_action']
    assert saved['candidate_verification']['stop_verified'] is True
    assert 'repair_publication' not in saved


def test_lost_result_readback_reconciles_the_same_command(tmp_path, capsys, monkeypatch):
    data, _, identity, _, _, _, advance, _, calls = verify_fixture(tmp_path, capsys, monkeypatch, lose_output=True)
    first = advance()
    assert first['action'] == 'wait', first
    saved = cycle._find(data[0], 10, identity)
    worker = saved['candidate_verification']['worker']
    assert cycle._mapping(data[0], worker)['state'] == 'running'
    second = advance()
    assert second['action'] == 'wait', second  # in-memory admission cannot be refreshed
    assert cycle._find(data[0], 10, identity)['candidate_verification']['state'] == 'artifact_ready'
    assert len([call for call in calls if call[0] == 'POST']) == 1


def test_stale_artifact_is_refused_without_reexecuting(tmp_path, capsys, monkeypatch):
    data, _, identity, _, _, _, advance, _, calls = verify_fixture(tmp_path, capsys, monkeypatch)
    assert advance()['action'] == 'wait'
    saved = cycle._find(data[0], 10, identity)
    artifact = cycle.Path(saved['candidate_verification']['evidence_file'])
    artifact.write_text('changed\n')
    held = advance()
    assert held['action'] == 'wait' and 'artifact changed' in held['reason'], held
    assert len([call for call in calls if call[0] == 'POST']) == 1
    assert 'repair_publication' not in cycle._find(data[0], 10, identity)


def test_source_drift_stops_pending_verifier(tmp_path, capsys, monkeypatch):
    data, _, identity, _, _, _, advance, _, calls = verify_fixture(tmp_path, capsys, monkeypatch, lose_output=True)
    assert advance()['action'] == 'wait'
    worker = cycle._find(data[0], 10, identity)['candidate_verification']['worker']
    (data[1] / 'private.cache').write_text('changed retained work\n')
    held = advance()
    assert held['action'] == 'wait', held
    assert cycle._mapping(data[0], worker)['state'] == 'stopped_verified'
    assert (data[1] / 'private.cache').read_text() == 'changed retained work\n'
    assert len([call for call in calls if call[0] == 'POST']) == 1


def test_missing_upstream_bash_api_holds_without_command(tmp_path, capsys, monkeypatch):
    data, _, identity, _, _, _, advance, _, calls = verify_fixture(tmp_path, capsys, monkeypatch, missing_api=True)
    held = advance()
    assert held['action'] == 'wait' and 'event readback' in held['reason'], held
    verify = cycle._find(data[0], 10, identity)['candidate_verification']
    assert verify['commands'][0]['state'] == 'intent'
    assert not [call for call in calls if call[0] == 'POST']


@pytest.mark.parametrize(('repaired', 'lost_push', 'explicit'),
                         [(False, False, False), (True, True, False), (False, False, True)])
def test_default_artifact_reaches_real_native_publisher(tmp_path, capsys, monkeypatch, repaired, lost_push, explicit):
    import shutil
    from app.builderops import publication

    data, fetch, identity, _, home, http, advance, _, calls = verify_fixture(tmp_path, capsys, monkeypatch, repaired=repaired)
    layout, _, publisher, _, original, entry, _, _, _ = data
    candidate = cycle._find(layout, 10, identity)['repair_candidate']
    base = entry['head_sha']
    repo = cycle.completion.REPOSITORY
    issue = {'number': 6617, 'state': 'open', 'title': 'Repair', 'body': original['governing_issue']['body'],
             'labels': [{'name': 'agent:in-progress'}]}
    fakebin = tmp_path / 'fake-bin'
    fakebin.mkdir()
    real_git = shutil.which('git')
    (fakebin / 'git').write_text('#!/usr/local/bin/python3.12\nimport os,sys\n'
        f'if sys.argv[1:] == ["remote", "get-url", "origin"]: print("https://github.com/{repo}.git"); sys.exit(0)\n'
        f'os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n')
    (fakebin / 'gh').write_text('#!/usr/local/bin/python3.12\nimport json,os,sys\n'
        'd=json.load(open(os.environ["SYNTHETIC_GH_DATA"])); p=sys.argv[-1]\n'
        'v=([[]] if "--paginate" in sys.argv else [d["pr"]] if "/pulls?" in p else '
        'd["pr"] if p.endswith("/pulls/10") else d["issue"] if p.endswith("/issues/6617") else None)\n'
        'print(json.dumps(v)); sys.exit(0 if v is not None else 2)\n')
    (fakebin / 'git').chmod(0o755)
    (fakebin / 'gh').chmod(0o755)
    github_data = tmp_path / 'synthetic-github.json'

    class FakeGithubPort:
        def __init__(self):
            self.remote = base
            self.calls = []
            self.failures = []
            self.lost_push = lost_push

        def run(self, argv, *, cwd, input_text=None):
            argv = tuple(argv)
            self.calls.append(argv)
            if argv[:3] == ('git', 'remote', 'get-url'):
                return publication.CommandResult(argv, 0, f'https://github.com/{repo}.git\n', '')
            if argv[:2] == ('git', 'ls-remote'):
                ref = argv[-1]
                sha = base if ref == 'refs/heads/main' else self.remote
                return publication.CommandResult(argv, 0, f'{sha}\t{ref}\n', '')
            if argv[:2] == ('git', 'push'):
                self.remote = candidate['candidate_head']
                if self.lost_push:
                    self.lost_push = False
                    raise RuntimeError('synthetic lost push reply')
                return publication.CommandResult(argv, 0, '', '')
            if argv[:6] == ('gh', 'api', '--hostname', 'github.com', '--method', 'GET'):
                endpoint = argv[6]
                if endpoint.endswith('/issues/6617'):
                    obj = issue
                elif endpoint.endswith('/git/ref/heads/main'):
                    obj = {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': base}}
                elif endpoint.endswith('/pulls'):
                    obj = [self.pr()]
                elif endpoint.endswith('/check-runs'):
                    obj = {'total_count': 0, 'check_runs': []}
                elif endpoint.endswith('/status'):
                    obj = {'sha': self.remote, 'state': 'pending', 'total_count': 0, 'statuses': []}
                else:
                    raise AssertionError(argv)
                return publication.CommandResult(argv, 0, json.dumps(obj), '')
            github_data.write_text(json.dumps({'pr': self.pr(), 'issue': issue}))
            env = {**os.environ, 'PATH': str(fakebin) + os.pathsep + os.environ['PATH'],
                   'SYNTHETIC_GH_DATA': str(github_data)}
            result = subprocess.run(list(argv), cwd=cwd, input=input_text, text=True, capture_output=True, check=False, env=env)
            if result.returncode:
                self.failures.append((argv, result.stdout, result.stderr))
            return publication.CommandResult(argv, result.returncode, result.stdout, result.stderr)

        def pr(self):
            return {'number': 10, 'state': 'open', 'draft': False, 'merged_at': None,
                'title': original['title'], 'body': original['body'], 'labels': [], 'user': {'login': 'synthetic-author'},
                'html_url': 'https://example.invalid/pull/10',
                'head': {'sha': self.remote, 'ref': candidate['branch'], 'repo': {'full_name': repo}},
                'base': {'sha': base, 'ref': 'main', 'repo': {'full_name': repo}}}

    port = FakeGithubPort()
    monkeypatch.setattr(cycle.closure, '_pr', lambda *args: port.pr())
    def collector(path, timeout):
        status, raw = fetch(path, timeout)
        if path.endswith('/pulls/10'):
            row = json.loads(raw)
            row['head']['sha'] = port.remote
            raw = json.dumps(row).encode()
        return status, raw

    if explicit:
        assert advance()['action'] == 'wait'  # Produce the artifact before supplying its explicit compatibility path.
        verify = cycle._find(layout, 10, identity)['candidate_verification']
        entry['repair_publication'] = {'evidence_file': verify['evidence_file'], 'paths': verify['paths']}
    admission_path = tmp_path / 'admissions.json'
    admission_path.write_text(json.dumps({'admissions': [entry]}))
    result = cycle.advance(layout, admission_path, fetch=collector, http=http, codex_home=home,
                           publisher_executor=port)['results'][0]
    if lost_push:
        assert result['action'] == 'wait', (result, port.failures)
        result = cycle.advance(layout, admission_path, fetch=collector, http=http, codex_home=home,
                               publisher_executor=port)['results'][0]
    assert result['action'] == 'published-awaiting-new-head-review', (result, port.failures)
    assert port.remote == candidate['candidate_head']
    assert json.loads(admission_path.read_text())['admissions'][0]['head_sha'] == candidate['candidate_head']
    assert len([call for call in port.calls if call[:2] == ('git', 'push')]) == 1
    assert len([call for call in calls if call[0] == 'POST']) == 1


def test_installed_bash_service_records_actual_fixture_exit(tmp_path, monkeypatch):
    import asyncio
    import shlex
    import sys
    from openhands.agent_server.bash_service import BashEventService
    from openhands.agent_server.models import ExecuteBashRequest

    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    test = tmp_path / 'test_fixture.py'
    test.write_text('def test_fixture(): assert 2 + 2 == 4\n')

    async def run():
        service = BashEventService(bash_events_dir=tmp_path / 'bash-events', default_cwd=str(tmp_path))
        request = ExecuteBashRequest(command=shlex.join([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(test)]),
                                     cwd=str(tmp_path), timeout=30)
        command, task = await service.start_bash_command(request)
        await task
        events = await service.search_bash_events(kind__eq='BashOutput', command_id__eq=command.id)
        return command.model_dump(mode='json'), [event.model_dump(mode='json') for event in events.items]

    command, outputs = asyncio.run(run())
    assert command['kind'] == 'BashCommand'
    assert outputs[-1]['kind'] == 'BashOutput' and outputs[-1]['exit_code'] == 0
    assert outputs[-1]['command_id'] == command['id'] and '1 passed' in outputs[-1]['stdout']


def test_artifact_file_replay_preserves_foreign_content(tmp_path):
    path = tmp_path / 'evidence.json'
    first = cycle._write_candidate_evidence(path, 'same\n')
    assert cycle._write_candidate_evidence(path, 'same\n') == first
    with pytest.raises(cycle.CycleError, match='changed'):
        cycle._write_candidate_evidence(path, 'different\n')
    assert path.read_text() == 'same\n'
