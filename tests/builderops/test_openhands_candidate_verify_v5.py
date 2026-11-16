"""Candidate Verify through production OpenHands Bash lifecycle, with synthetic ports.

Miniature child suites deliberately load no optional plugins or repository configuration.
Clear only their inherited pytest options; outer CI timeouts and finite child deadlines remain.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
import venv as venv_module
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


def _private_test_venv(path):
    # The real controller guard requires private fixture output regardless of CI's umask.
    previous_umask = os.umask(0o077)
    try:
        path.mkdir(mode=0o700)
        venv_module.EnvBuilder(system_site_packages=True, symlinks=False).create(path)
        # Copy operations can preserve the source mode despite the umask. Only
        # touch newly created, owned entries, never a link or a shared inode.
        for root, dirs, files in os.walk(path, followlinks=False):
            for name in ['.', *dirs, *files]:
                item = cycle.Path(root) / name
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode):
                    continue
                if info.st_uid != os.geteuid() or not (stat.S_ISDIR(info.st_mode) or
                        (stat.S_ISREG(info.st_mode) and info.st_nlink == 1)):
                    raise RuntimeError('unexpected shared or unowned venv fixture entry')
                item.chmod(stat.S_IMODE(info.st_mode) & 0o700)
    finally:
        os.umask(previous_umask)


def _write_private_admissions(path, admissions):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump({'admissions': admissions}, output)


def test_private_admissions_real_guard_and_atomic_refresh_under_permissive_umask(tmp_path):
    layout = ew.Layout(tmp_path / 'workers', 6615)
    private, unsafe = tmp_path / 'private.json', tmp_path / 'unsafe.json'
    previous_umask = os.umask(0o002)
    try:
        _write_private_admissions(private, [])
        assert os.umask(0o002) == 0o002
        assert private.stat().st_uid == os.geteuid()
        assert private.stat().st_mode & 0o777 == 0o600
        assert cycle._read_configuration(layout, private) == {'admissions': []}
        expected = private.read_text()
        cycle._write_configuration(private, {'admissions': [], 'refreshed': True}, expected)
        assert private.stat().st_mode & 0o777 == 0o600
        assert cycle._read_configuration(layout, private)['refreshed'] is True
        unsafe.write_text('{"admissions": []}')
        assert unsafe.stat().st_mode & 0o777 == 0o664
        with pytest.raises(cycle.CycleError, match='controller-owned'):
            cycle._read_configuration(layout, unsafe)
        with pytest.raises(FileExistsError):
            _write_private_admissions(private, [])
        assert os.umask(0o002) == 0o002
    finally:
        os.umask(previous_umask)


def test_private_test_venv_modes_and_real_guard_under_permissive_umask(tmp_path):
    layout = ew.Layout(tmp_path / 'workers', 6615)
    private = tmp_path / 'private-venv'
    inherited = tmp_path / 'inherited-venv'
    previous_umask = os.umask(0o002)
    try:
        _private_test_venv(private)
        assert os.umask(0o002) == 0o002
        assert cycle._test_venv_source(layout, str(private)) == private
        assert private.stat().st_mode & 0o777 == 0o700
        assert (private / 'pyvenv.cfg').stat().st_mode & 0o777 == 0o600
        # Both negatives reach the unmodified production guard on owned real venvs.
        venv_module.EnvBuilder(system_site_packages=True, symlinks=False).create(inherited)
        assert inherited.stat().st_mode & 0o777 == 0o775
        assert (inherited / 'pyvenv.cfg').stat().st_mode & 0o777 == 0o664
        with pytest.raises(cycle.CycleError, match='ownership or mode is unsafe'):
            cycle._test_venv_source(layout, str(inherited))
        (private / 'pyvenv.cfg').chmod(0o664)
        with pytest.raises(cycle.CycleError, match='ownership or mode is unsafe'):
            cycle._test_venv_source(layout, str(private))
    finally:
        os.umask(previous_umask)


def test_private_test_venv_restores_umask_after_creation_failure(tmp_path, monkeypatch):
    def failed_creation(self, path):
        assert os.umask(0o077) == 0o077
        raise OSError('synthetic venv creation failure')

    monkeypatch.setattr(venv_module.EnvBuilder, 'create', failed_creation)
    previous_umask = os.umask(0o002)
    try:
        with pytest.raises(OSError, match='synthetic venv creation failure'):
            _private_test_venv(tmp_path / 'failed-venv')
        assert os.umask(0o002) == 0o002
    finally:
        os.umask(previous_umask)


def test_private_test_venv_scrubs_copy_preserved_modes(tmp_path, monkeypatch):
    source = tmp_path / 'permissive-source'
    source.write_text('fixture copy\n')
    source.chmod(0o664)
    setup_python = venv_module.EnvBuilder.setup_python

    def copy_permissive_source(self, context):
        setup_python(self, context)
        copied = cycle.Path(context.bin_path) / 'copied-fixture'
        shutil.copy2(source, copied)
        assert copied.stat().st_mode & 0o777 == 0o664

    monkeypatch.setattr(venv_module.EnvBuilder, 'setup_python', copy_permissive_source)
    private = tmp_path / 'private-venv'
    _private_test_venv(private)
    assert source.stat().st_mode & 0o777 == 0o664
    for root, dirs, files in os.walk(private, followlinks=False):
        for name in ['.', *dirs, *files]:
            info = (cycle.Path(root) / name).lstat()
            assert info.st_uid == os.geteuid()
            if not stat.S_ISLNK(info.st_mode):
                assert info.st_mode & 0o077 == 0
    assert cycle._test_venv_source(ew.Layout(tmp_path / 'workers', 6615), str(private)) == private


def verify_fixture(tmp_path, capsys, monkeypatch, *, fail=False, lose=False, lose_output=False, repaired=False,
                   missing_api=False, test_source=None, sol=False):
    source = test_source or ('def test_example(): assert False\n' if fail else 'def test_example(): pass\n')
    if repaired:
        data, fetch, identity, server, home = repaired_review(tmp_path, capsys, monkeypatch)
    else:
        data, fetch, identity, server, home, _, _, _, _ = prepared(tmp_path, capsys, monkeypatch, test_source=source, sol=sol)
    layout, _, publisher, _, pr, entry, _, _, _ = data
    venv = tmp_path / 'approved-venv'
    # Copy the executing runtime: CI's toolcache path is not present in the worker image.
    # This is an owned fixture, not an escape from the production interpreter allowlist.
    _private_test_venv(venv)
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
                                        env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_ADDOPTS': ''}, timeout=30)
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


@pytest.mark.parametrize('body', [
    'if n: pytest.skip("missing")',
    'if n: pytest.xfail("missing")',
])
def test_incomplete_real_pytest_cannot_make_candidate_artifact(tmp_path, capsys, monkeypatch, body):
    source = ('import pytest\n@pytest.mark.parametrize("n", [0, 1])\n'
              f'def test_example(n):\n    {body}\n    assert True\n')
    data, _, identity, _, _, _, advance, _, _ = verify_fixture(
        tmp_path, capsys, monkeypatch, test_source=source)
    result = advance()
    assert result['action'] == 'candidate-verify-failed', result
    saved = cycle._find(data[0], 10, identity)
    verify = saved['candidate_verification']
    assert verify['commands'][0]['exit_code'] == 0
    assert verify['commands'][0]['output_event_ids'] and verify['stop_verified'] is True
    assert 'evidence_file' not in verify and 'repair_publication' not in saved


def test_missing_real_pytest_collection_cannot_make_candidate_artifact(tmp_path, capsys, monkeypatch):
    data, _, identity, _, _, _, advance, _, _ = verify_fixture(
        tmp_path, capsys, monkeypatch, test_source='def test_other(): pass\n')
    assert advance()['action'] == 'candidate-verify-failed'
    verify = cycle._find(data[0], 10, identity)['candidate_verification']
    assert verify['commands'][0]['exit_code'] != 0 and verify['stop_verified'] is True
    assert 'evidence_file' not in verify


@pytest.mark.parametrize(('case', 'accepted'), [('pass', True), ('skip', False), ('xfail', False), ('missing', False)])
def test_full_validator_checks_real_pytest_summary(tmp_path, case, accepted):
    import sys
    from app.builderops import openhands_delivery as delivery

    work = tmp_path / 'work'
    (work / 'tests').mkdir(parents=True)
    behavior = {'pass': 'pass', 'skip': 'pytest.skip("missing")', 'xfail': 'pytest.xfail("missing")',
                'missing': 'pass'}[case]
    (work / 'tests/test_example.py').write_text(
        'import pytest\n@pytest.mark.parametrize("n", [0, 1])\n'
        f'def test_example(n):\n    if n: {behavior}\n    assert True\n')
    target = 'tests/test_example.py::' + ('test_absent' if case == 'missing' else 'test_example')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', target],
                            cwd=work, capture_output=True, text=True,
                            env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_ADDOPTS': '', 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=30)
    head, base = 'a' * 40, 'b' * 40
    review, output = tmp_path / 'review.txt', tmp_path / 'output.txt'
    review.write_text(f'independent review candidate {head} pass\n')
    output.write_text(result.stdout + '\n' + result.stderr)
    body = f'## Acceptance Criteria\n- [ ] Required behavior.\n  - Verify: `{target}`\n'
    receipt = {'version': 1, 'repository': delivery.REPOSITORY, 'issue': 123, 'head_sha': head, 'base_sha': base,
        'risk_surfaces': [], 'review': {'verdict': 'pass', 'head_sha': head, 'reviewer': 'independent',
        'blocking_findings': [], 'evidence': {'path': str(review)}}, 'verification': [
        {'target': target, 'head_sha': head, 'result': 'pass', 'evidence': {'path': str(output)}}]}
    path = tmp_path / 'evidence.json'
    path.write_text(json.dumps(receipt))
    args = (path, {'worktree': str(work), 'issue': 123}, head, base, body)
    if accepted:
        assert result.returncode == 0
        delivery._full_evidence(*args)
    else:
        with pytest.raises(delivery.DeliveryError, match='Test source does not substantiate'):
            delivery._full_evidence(*args)


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


def test_verify_failure_repairs_real_candidate_then_publishes(tmp_path, capsys, monkeypatch):
    source = 'from pathlib import Path\ndef test_example():\n    assert Path("new.py").read_text() == "fixed\\n"\n'
    fixture = verify_fixture(tmp_path, capsys, monkeypatch, test_source=source, lose_output=True)
    data, _, identity, server, _, _, advance, _, calls = fixture
    layout, original_author, publisher, engine, pr, entry, _, _, _ = data
    assert advance()['action'] == 'wait'  # lost Verify output readback
    failed = advance()
    assert failed['action'] == 'candidate-verify-failed', failed
    saved = cycle._find(layout, 10, identity)
    old = saved['repair_candidate']
    verification = saved['candidate_verification']
    old_review = saved['candidate_review_receipt']
    assert verification['stop_verified'] and verification['commands'][-1]['exit_code'] == 1
    assert 'AssertionError' in verification['commands'][-1]['stdout']
    server.lose_next_create = True
    started = advance()
    assert started['action'] == 'candidate-repair-author' and started['conversation_status'] in ('unknown', 'created'), started
    worker, cid = started['worker'], started['conversation_id']
    post = [c for c in server.calls if c[0] == 'POST' and c[2] == '/conversations'][-1]
    prompt = post[3]['initial_message']['content'][0]['text']
    assert 'tests/example.py::test_example' in prompt and 'AssertionError' in prompt and 'exit 1' in prompt
    assert old['candidate_head'] in prompt
    assert cycle._candidate_git(layout.checkout(worker), 'rev-parse', 'HEAD').strip() == old['candidate_head']
    resumed = advance()
    assert resumed['conversation_id'] == cid and resumed['conversation_status'] == 'created', resumed
    assert len([c for c in server.calls if c[0] == 'POST' and c[2] == '/conversations']) == 2

    def native_finished(worker, cid, session):
        container_id = cycle._mapping(layout, worker)['container_id']
        original_command = cycle._command

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
                        'model': entry['model'], 'effort': entry.get('effort', 'ultra'),
                        'timestamp': '2026-11-15T00:00:00Z'})
                else:
                    value = 'route-ok\n'
                return subprocess.CompletedProcess(argv, 0, value, '')
            return original_command(argv, timeout=timeout)

        monkeypatch.setattr(cycle, '_command', command)
        server.conversations[cid].update(execution_status='finished',
            agent={'kind': 'ACPAgent', 'acp_server': 'codex', 'acp_model': entry['model']},
            current_model_id=entry['model'], current_effort=entry.get('effort', 'ultra'),
            available_efforts=[{'value': entry.get('effort', 'ultra')}],
            agent_state={'acp_session_id': session, 'acp_session_cwd': '/workspace'})
        server.events = [{'kind': 'MessageEvent', 'source': 'agent'}]

    (layout.checkout(worker) / 'new.py').write_text('fixed\n')
    (layout.checkout(worker) / 'repair-unique.cache').write_text('preserved\n')
    native_finished(worker, cid, 'verify-repair-native')
    prepared_result = advance()
    assert prepared_result['action'] == 'awaiting-candidate-review', prepared_result
    saved = cycle._find(layout, 10, identity)
    candidate = saved['repair_candidate']
    assert cycle._candidate_git(publisher, 'rev-parse', 'HEAD^').strip() == old['candidate_head']
    assert candidate['source_base_head'] == old['candidate_head']
    assert saved['candidate_repair_history'][-1]['fields']['candidate_verification'] == verification
    assert saved['candidate_repair_history'][-1]['fields']['candidate_review_receipt'] == old_review
    assert 'candidate_verification' not in saved
    assert cycle._mapping(layout, worker)['state'] == 'stopped_verified'
    assert (layout.checkout(worker) / 'repair-unique.cache').read_text() == 'preserved\n'
    assert (original_author / 'private.cache').read_text() == 'ignored unique work\n'
    reviewer = advance()
    assert reviewer['action'] == 'candidate-review-dispatched', reviewer
    native_finished(reviewer['worker'], reviewer['conversation_id'], 'fresh-review-native')
    saved = cycle._find(layout, 10, identity)
    report = dict(old_review['report'], identity=saved['candidate_review_dispatch']['binding_sha256'],
                  head_sha=candidate['candidate_head'])
    server.final_responses[reviewer['conversation_id']] = json.dumps(report)
    assert advance()['action'] == 'awaiting-candidate-verify'
    _publish_verified_fixture(tmp_path, monkeypatch, fixture, lost_push=True, verify_posts=2)
    assert len([c for c in calls if c[0] == 'POST']) == 2


def test_verify_repair_drift_holds_and_peer_progresses(tmp_path, capsys, monkeypatch):
    import copy
    import time
    from datetime import datetime, timezone

    real_lifecycle_owner = cycle._lifecycle_owner
    fixture = verify_fixture(tmp_path, capsys, monkeypatch, fail=True)
    data, fetch, identity, server, home, http, advance, _, _ = fixture
    layout, _, _, engine, _, entry, _, _, lease = data
    assert advance()['action'] == 'candidate-verify-failed'
    original = cycle._find(layout, 10, identity)
    for drift in ('binding', 'stop', 'scope'):
        changed = copy.deepcopy(original)
        if drift == 'binding':
            changed['candidate_verification']['binding_sha256'] = '0' * 64
        elif drift == 'stop':
            changed['candidate_verification']['stop_intent']['stop_id'] = 'f' * 32
        else:
            changed['candidate_review_dispatch']['binding']['scope_hashes']['6617']['body_sha256'] = '0' * 64
        cycle._save(layout, changed)
        held = advance()
        assert held['action'] == 'wait', (drift, held)
        assert 'candidate_repair' not in cycle._find(layout, 10, identity)
        cycle._save(layout, copy.deepcopy(original))
    old_holder = lease['holder']
    lease['holder'] = 'foreign'
    assert advance()['action'] == 'wait'
    lease['holder'] = old_holder
    assert 'candidate_repair' not in cycle._find(layout, 10, identity)
    verifier = original['candidate_verification']['worker']
    with ew._worker_lifecycle_lock(layout, verifier):
        assert advance()['action'] == 'wait'
        assert 'candidate_repair' not in cycle._find(layout, 10, identity)
    started = advance()
    assert started['action'] == 'candidate-repair-author', started
    worker = started['worker']
    retained = cycle._find(layout, 10, identity)
    retained['candidate_verification']['commands'][-1]['stdout'] += '\nchanged\n'
    cycle._save(layout, retained)

    # Produce an independent peer registration and claim, using the same lifecycle
    # producer and synthetic dispatcher port as the existing authority fixtures.
    source = cycle.Path(entry['lifecycle_repo'])
    peer_checkout = tmp_path / 'peer-owner'
    subprocess.run(['git', '-C', str(source), 'worktree', 'add', '-b', 'b/peer',
                    str(peer_checkout), entry['head_sha']], check=True, capture_output=True, text=True)
    now = int(time.time())
    cycle.agent_worktree.register_worktree(source, worktree=peer_checkout, owner='peer-session',
                                           now=now - 30, ttl_seconds=3600)
    peer_entry = {**entry, 'number': 9, 'worker': 'peer', 'claimant': 'peer-owner',
                  'session': 'peer-session', 'lease_id': 'peer-lease',
                  'owner_worktree': str(peer_checkout.resolve())}
    original_lifecycle = cycle._lifecycle_owner
    monkeypatch.setattr(cycle, '_lifecycle_owner', lambda layout, admitted, branch:
                        real_lifecycle_owner(layout, admitted, branch) if branch == 'b/peer'
                        else original_lifecycle(layout, admitted, branch))
    peer_task_id = cycle.github_issue_task_id(cycle.completion.REPOSITORY, 6619)
    peer_task = {'task_id': peer_task_id, 'repo': cycle.completion.REPOSITORY, 'issue_number': 6619,
                 'status': 'claimed', 'claimed_by': 'peer-owner', 'lease_id': 'peer-lease',
                 'lease_expires_at': '2099-01-01T00:00:00Z', 'linked_pr': 9}
    peer_lease = {'lease_id': 'peer-lease', 'holder': 'peer-owner', 'resource': 'issue:6619',
                  'expires_at': peer_task['lease_expires_at'], 'released_at': None}
    peer_events = [{'task_id': peer_task_id, 'event_type': 'task.claimed', 'actor': 'peer-owner',
                    'lease_id': 'peer-lease', 'timestamp': datetime.fromtimestamp(now - 20, timezone.utc).isoformat(),
                    'payload': {'session': 'peer-session', 'ttl_minutes': 90}}]
    original_dispatcher = cycle.closure._dispatcher_inspect
    monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', lambda executor, cwd, task_id:
                        (peer_task, peer_events, peer_lease) if task_id == peer_task_id
                        else original_dispatcher(executor, cwd, task_id))
    registration, records = real_lifecycle_owner(layout, peer_entry, 'b/peer')
    history = dict(registration=registration, records=records, comments=[], issue_comments=[], events=peer_events,
                   origin={}, origin_at=None, issue=6619, pr_number=9, branch='b/peer', entry=peer_entry)
    assert registration['owner'] == 'peer-session' and registration['path'] == str(peer_checkout.resolve())
    assert cycle._claimant_history(**history) == []
    foreign_events = copy.deepcopy(peer_events)
    foreign_events[0]['payload']['session'] = 'foreign-session'
    with pytest.raises(cycle.CycleError, match='current claimant differs'):
        cycle._claimant_history(**{**history, 'events': foreign_events})

    ew.create_worker(layout, 'peer', issue=6619, branch='b/peer', next_action='review', runner=engine)
    ew.start_openhands_worker(layout, 'peer', runner=engine, http=server)
    old_head = entry['head_sha']
    peer_issue = {'number': 6619, 'state': 'open', 'title': 'Peer',
                  'body': data[4]['governing_issue']['body'], 'labels': [{'name': 'agent:in-progress'}]}
    peer_pr = {'number': 9, 'state': 'open', 'draft': False, 'title': 'Peer', 'labels': [],
               'body': 'Governing-Issue: #6619\nFixes #6619\n',
               'head': {'sha': old_head, 'ref': 'b/peer', 'repo': {'full_name': cycle.completion.REPOSITORY}},
               'base': {'sha': old_head, 'ref': 'main'}}
    original_pr, original_issue, original_refs = cycle.closure._pr, cycle.closure._issue, cycle.closure._closing_issue_references
    monkeypatch.setattr(cycle.closure, '_pr', lambda executor, cwd, repo, number:
                        peer_pr if number == 9 else original_pr(executor, cwd, repo, number))
    monkeypatch.setattr(cycle.closure, '_issue', lambda executor, cwd, repo, number:
                        peer_issue if number == 6619 else original_issue(executor, cwd, repo, number))
    monkeypatch.setattr(cycle.closure, '_closing_issue_references', lambda executor, cwd, repo, number:
                        [6619] if number == 9 else original_refs(executor, cwd, repo, number))

    def peer_fetch(path, timeout):
        if '/pulls?' in path:
            value = [{'number': 9}, {'number': 10}]
        elif '/pulls/9/reviews' in path:
            value = []
        elif path.endswith('/pulls/9'):
            value = peer_pr
        elif path.endswith('/issues/6619'):
            value = peer_issue
        else:
            return fetch(path, timeout)
        return 200, json.dumps(value).encode()

    result = cycle.advance(layout, [peer_entry, entry],
                           fetch=peer_fetch, http=http, codex_home=home)['results']
    assert result[0]['action'] == 'independent-review' and result[1]['action'] == 'wait', result
    assert cycle._mapping(layout, worker)['state'] == 'stopped_verified'
    assert cycle._find(layout, 10, identity)['candidate_repair']['held'] is True
    assert len([call for call in server.calls if call[0] == 'POST' and call[2] == '/conversations']) == 3


def test_verify_repair_unknown_author_post_retains_id_and_sol_high(tmp_path, capsys, monkeypatch):
    data, _, identity, server, _, _, advance, _, _ = verify_fixture(tmp_path, capsys, monkeypatch, fail=True, sol=True)
    assert advance()['action'] == 'candidate-verify-failed'
    server.lose_next_create = True
    server.create_not_applied = True
    first = advance()
    assert first['action'] == 'candidate-repair-author' and first['conversation_status'] == 'unknown', first
    second = advance()
    assert second['conversation_id'] == first['conversation_id'] and second['conversation_status'] == 'unknown', second
    posts = [c for c in server.calls if c[0] == 'POST' and c[2] == '/conversations']
    assert len(posts) == 2
    body = posts[-1][3]
    assert body['agent_settings'] == {'agent_kind': 'acp', 'acp_server': 'codex',
                                      'acp_model': 'gpt-6.1-sol', 'acp_effort': 'high'}
    assert cycle._find(data[0], 10, identity)['candidate_verification']['state'] == 'failed'
    assert cycle._mapping(data[0], first['worker'])['state'] == 'running'


def test_verify_repair_refuses_changed_stopped_verifier_source(tmp_path, capsys, monkeypatch):
    data, _, identity, server, _, _, advance, _, _ = verify_fixture(tmp_path, capsys, monkeypatch, fail=True)
    assert advance()['action'] == 'candidate-verify-failed'
    verify = cycle._find(data[0], 10, identity)['candidate_verification']
    changed = data[0].checkout(verify['worker']) / 'new.py'
    changed.write_text('preserve changed verifier source\n')
    held = advance()
    assert held['action'] == 'wait' and 'Verify source changed' in held['reason'], held
    assert 'candidate_repair' not in cycle._find(data[0], 10, identity)
    assert changed.read_text() == 'preserve changed verifier source\n'
    assert len([call for call in server.calls if call[0] == 'POST' and call[2] == '/conversations']) == 1


@pytest.mark.parametrize(('repaired', 'lost_push', 'explicit'),
                         [(False, False, False), (True, True, False), (False, False, True)])
def test_default_artifact_reaches_real_native_publisher(tmp_path, capsys, monkeypatch, repaired, lost_push, explicit):
    fixture = verify_fixture(tmp_path, capsys, monkeypatch, repaired=repaired)
    _publish_verified_fixture(tmp_path, monkeypatch, fixture, lost_push=lost_push, explicit=explicit)


def _publish_verified_fixture(tmp_path, monkeypatch, fixture, *, lost_push=False, explicit=False, verify_posts=1):
    import shutil
    from app.builderops import publication

    data, fetch, identity, _, home, http, advance, _, calls = fixture
    layout, _, publisher, _, original, entry, _, _, _ = data
    candidate = cycle._find(layout, 10, identity)['repair_candidate']
    base = entry['head_sha']
    repo = cycle.completion.REPOSITORY
    issue = {'number': 6617, 'state': 'open', 'title': 'Repair', 'body': original['governing_issue']['body'],
             'labels': [{'name': 'agent:in-progress'}]}
    fakebin = tmp_path / 'fake-bin'
    fakebin.mkdir()
    real_git = shutil.which('git')
    (fakebin / 'git').write_text(f'#!{sys.executable}\nimport os,sys\n'
        f'if sys.argv[1:] == ["remote", "get-url", "origin"]: print("https://github.com/{repo}.git"); sys.exit(0)\n'
        f'os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])\n')
    (fakebin / 'gh').write_text(f'#!{sys.executable}\nimport json,os,sys\n'
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
    _write_private_admissions(admission_path, [entry])
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
    assert len([call for call in calls if call[0] == 'POST']) == verify_posts


def test_installed_bash_service_records_actual_fixture_exit(tmp_path, monkeypatch):
    import asyncio
    import shlex
    import sys
    # OpenHands is an optional installed-runtime probe, as for the ACP profile test.
    pytest.importorskip('openhands', reason='optional installed-runtime integration; required separately in sandbox acceptance')
    from openhands.agent_server.bash_service import BashEventService
    from openhands.agent_server.models import ExecuteBashRequest

    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    monkeypatch.setenv('PYTEST_ADDOPTS', '')
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
