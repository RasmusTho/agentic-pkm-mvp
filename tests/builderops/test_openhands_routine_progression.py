"""Routine progression: real cycle, native authority, Git, lifecycle and persistence.

GitHub/dispatcher, container/engine and upstream HTTP are simulated external ports.
The synthetic nested-Verify port runs real pytest with the current trusted interpreter;
the copied verifier fixture is inspected by the real preflight, never executed from tmp.
These regressions do not establish live runtime, model or activation acceptance.
"""
import copy
import json
import subprocess
import os
import shutil
import stat
import sys
import venv
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_pr_cycle import _automatic_cycle_fixture
from tests.builderops.test_epic_workspace_engine_handoff import SyntheticEngine

REAL_INSPECT = ew.inspect_checkout
REAL_STOPPED = cycle._assert_stopped
REAL_LIVE = cycle._assert_live_container
REAL_NATIVE_PROOF = cycle.native_execution_proof
REAL_TEST_VENV = cycle._test_venv_source
REAL_VENV_MINOR = cycle._venv_python_minor
REAL_THREADS = cycle._assert_review_threads_clear


@pytest.fixture
def synthetic_noexec_tmp(tmp_path, monkeypatch):
    """Model exec denial under the owned test root; no mount/security policy change."""
    original_popen = subprocess.Popen
    denied = []

    def popen(args, *positional, **kwargs):
        executable = kwargs.get('executable') or args[0]
        if Path(executable).resolve().is_relative_to(tmp_path.resolve()):
            denied.append(str(executable))
            raise PermissionError(f'synthetic noexec test root: {executable}')
        return original_popen(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', popen)
    return denied


def _create_verifier_venv(verifier):
    # This security-owned fixture must satisfy the real preflight even under CI's
    # group-writable outer umask; restore that umask for the rest of the test.
    previous_umask = os.umask(0o077)
    try:
        venv.EnvBuilder(with_pip=False, system_site_packages=True, symlinks=False).create(verifier)
    finally:
        os.umask(previous_umask)
    # install_scripts copies source modes, overriding the restrictive umask.
    # Only harden fixture-owned regular entries; never chmod or traverse links
    # (venv may create lib64 as a symlink).
    def unreadable(error):
        raise error

    for root, dirs, files in os.walk(verifier, followlinks=False, onerror=unreadable):
        for name in ['.', *dirs, *files]:
            path = Path(root) / name
            mode = path.lstat().st_mode
            if stat.S_ISREG(mode) or stat.S_ISDIR(mode):
                path.chmod(stat.S_IMODE(mode) & ~0o022, follow_symlinks=False)


def test_verifier_fixture_corrects_copied_modes_under_group_writable_umask(
        tmp_path, monkeypatch, synthetic_noexec_tmp):
    layout = ew.Layout(tmp_path / 'workspaces', 6618)
    verifier = tmp_path / 'controller-test-venv'
    templates = tmp_path / 'templates'
    (templates / 'common').mkdir(parents=True)
    for name, mode in [('plain', 0o664), ('executable', 0o775)]:
        template = templates / 'common' / name
        template.write_text('#!/bin/sh\nexit 0\n')
        template.chmod(mode)
    interpreter = tmp_path / 'upstream-python'
    shutil.copyfile(sys.executable, interpreter)
    interpreter.chmod(0o775)
    inspected = []

    class CopiedModeBuilder(venv.EnvBuilder):
        def setup_python(self, context):
            context.executable = str(interpreter)
            super().setup_python(context)

        def setup_scripts(self, context):
            super().setup_scripts(context)
            self.install_scripts(context, str(templates))

        def post_setup(self, context):
            # Real install_scripts uses copymode: umask 0077 cannot make these safe.
            assert stat.S_IMODE((verifier / 'bin/plain').stat().st_mode) == 0o664
            assert stat.S_IMODE((verifier / 'bin/executable').stat().st_mode) == 0o775
            with pytest.raises(cycle.CycleError, match='test environment ownership or mode is unsafe'):
                REAL_TEST_VENV(layout, str(verifier))
            nested = verifier / 'nested'
            nested.mkdir()
            nested.chmod(0o775)
            verifier.chmod(0o775)
            (nested / 'data').write_text('fixture')
            (nested / 'data').chmod(0o664)
            inspected.append(True)

    monkeypatch.setattr(venv, 'EnvBuilder', CopiedModeBuilder)
    previous_umask = os.umask(0o002)
    try:
        _create_verifier_venv(verifier)
        assert inspected == [True]
        assert os.umask(0o002) == 0o002
        assert REAL_TEST_VENV(layout, str(verifier)) == verifier
        assert stat.S_IMODE((verifier / 'bin/plain').stat().st_mode) == 0o644
        assert stat.S_IMODE((verifier / 'bin/executable').stat().st_mode) == 0o755
        assert stat.S_IMODE((verifier / 'nested').stat().st_mode) == 0o755
        assert stat.S_IMODE((verifier / 'nested/data').stat().st_mode) == 0o644
        assert stat.S_IMODE((verifier / 'bin/python').stat().st_mode) == 0o755
        assert (verifier / 'bin/python').read_bytes() == interpreter.read_bytes()
        # Executable mode is preserved even where the mount forbids exec. This
        # explicit simulated refusal is not an interpreter/runtime acceptance test.
        with pytest.raises(PermissionError, match='synthetic noexec test root'):
            subprocess.run([str(verifier / 'bin/python'), '-c', 'pass'], check=True)
        assert synthetic_noexec_tmp == [str(verifier / 'bin/python')]
        assert stat.S_IMODE(interpreter.stat().st_mode) == 0o775
        assert stat.S_IMODE((templates / 'common/plain').stat().st_mode) == 0o664
        (verifier / 'bin/plain').chmod(0o664)
        with pytest.raises(cycle.CycleError, match='test environment ownership or mode is unsafe'):
            REAL_TEST_VENV(layout, str(verifier))
    finally:
        os.umask(previous_umask)


def test_verifier_fixture_does_not_follow_symlinks(tmp_path, monkeypatch):
    verifier = tmp_path / 'controller-test-venv'
    outside = tmp_path / 'outside'
    outside.mkdir()
    outside.chmod(0o775)
    (outside / 'data').write_text('untouched')
    (outside / 'data').chmod(0o664)
    targets = {'external-dir': outside, 'external-file': outside / 'data',
               'dangling': outside / 'absent'}

    class SymlinkBuilder(venv.EnvBuilder):
        def post_setup(self, context):
            for name, target in targets.items():
                (verifier / name).symlink_to(target)

    monkeypatch.setattr(venv, 'EnvBuilder', SymlinkBuilder)
    _create_verifier_venv(verifier)
    assert stat.S_IMODE(outside.stat().st_mode) == 0o775
    assert stat.S_IMODE((outside / 'data').stat().st_mode) == 0o664
    assert (outside / 'data').read_text() == 'untouched'
    for name, target in targets.items():
        assert (verifier / name).is_symlink()
        assert os.readlink(verifier / name) == str(target)
    layout = ew.Layout(tmp_path / 'workspaces', 6618)
    with pytest.raises(cycle.CycleError, match='test environment symlink escapes its boundary'):
        REAL_TEST_VENV(layout, str(verifier))
    for name in targets:
        (verifier / name).unlink()
    assert REAL_TEST_VENV(layout, str(verifier)) == verifier


def assembled(tmp_path, monkeypatch, *, nonclosing=False, verify_passes=True):
    f = _automatic_cycle_fixture(tmp_path, monkeypatch)
    layout, worker = f['layout'], 'reviewer'
    # Put the Verify target in the actual fixture commit, as on an admitted PR head.
    if not verify_passes:
        (f['worktree'] / 'tests/example.py').write_text('def test_example():\n    assert False\n')
    subprocess.run(['git', '-C', str(f['worktree']), 'add', 'tests/example.py'],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(f['worktree']), '-c', 'user.name=Fixture',
                    '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture Verify target'],
                   check=True, capture_output=True)
    f['head'] = subprocess.check_output(['git', '-C', str(f['worktree']), 'rev-parse', 'HEAD'], text=True).strip()
    f['live']['head']['sha'] = f['head']
    f['pr']['head_sha'] = f['head']
    f['entry']['head_sha'] = f['head']
    verifier = tmp_path / 'controller-test-venv'
    _create_verifier_venv(verifier)
    config = json.loads(f['config'].read_text())
    config['automatic_native']['test_venv'] = str(verifier)
    f['entry']['test_venv'] = str(verifier)
    f['config'].write_text(json.dumps(config))
    monkeypatch.setattr(cycle, '_test_venv_source', REAL_TEST_VENV)
    monkeypatch.setattr(cycle, '_venv_python_minor', REAL_VENV_MINOR)
    f.update(ci_calls=[], ci_exit=0)
    original_executor = cycle.SubprocessExecutor
    class Executor(original_executor):
        def run(self, argv, **kw):
            if 'graphql' in argv and any('reviewThreads' in arg for arg in argv):
                data = {'data': {'repository': {'pullRequest': {'reviewThreads': {
                    'nodes': [], 'pageInfo': {'hasNextPage': False}}}}}}
                return subprocess.CompletedProcess(argv, 0, json.dumps(data), '')
            return super().run(argv, **kw)
    monkeypatch.setattr(cycle, 'SubprocessExecutor', Executor)
    monkeypatch.setattr(cycle, '_assert_review_threads_clear', REAL_THREADS)
    checkout = layout.checkout(worker)
    checkout.rmdir()  # empty fixture directory, never previous unique work
    subprocess.run(['git', 'clone', '--no-hardlinks', '--branch', 'codex/example',
                    str(f['worktree']), str(checkout)], check=True, capture_output=True)
    subprocess.run(['git', 'clone', '--mirror', str(f['worktree']), str(layout.source)],
                   check=True, capture_output=True)
    layout.home(worker).mkdir(parents=True, exist_ok=True)
    engine = SyntheticEngine()
    verification_runs = []
    verification_results = []
    # Existing engine fixture's absent-object diagnostic is normalized at its external port.
    def runner(argv, **kw):
        if list(argv)[:3] == ['docker', 'image', 'inspect']:
            return subprocess.CompletedProcess(argv, 0, '[{"Id":"sha256:simulated-image"}]', '')
        if list(argv)[:2] == ['docker', 'exec']:
            if argv[-2:] == ['login', 'status']:
                value = 'Logged in using ChatGPT'
            elif argv[-2] == 'codex':
                value = json.dumps({'engine': 'codex', 'conversation_id': argv[-1],
                    'session_id': 'simulated-native', 'model': 'gpt-6.1-sol', 'effort': 'high',
                    'timestamp': '2026-11-16T10:00:00Z'})
            else:
                value = 'route-ok'
            return subprocess.CompletedProcess(argv, 0, value, '')
        if (list(argv)[:3] == ['docker', 'start', '--attach']
                and any('import pytest;' in arg for arg in engine.pending.get(argv[-1], []))):
            command = engine.pending[argv[-1]]
            targets = command[command.index('-c') + 2:]
            verification_runs.append(list(targets))
            # This external container port is explicitly synthetic, inside the
            # outer verifier. Run actual pytest with its trusted interpreter so
            # tmp need not be executable; never retry/fall back after exec failure.
            result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', *targets],
                cwd=checkout, capture_output=True, text=True, timeout=30,
                env={**os.environ, 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTEST_ADDOPTS': '',
                     'PYTHONDONTWRITEBYTECODE': '1'})
            verification_results.append(result)
            return result
        if list(argv)[:2] == ['docker', 'inspect'] and '--format' not in argv:
            cid = argv[-1]
            if cid in engine.ids.values() and 'reviewer' in engine.containers:
                return subprocess.CompletedProcess(argv, 0, json.dumps([{'Id': cid,
                    'Name': '/' + layout.container_name(worker), 'State': {'Running': True},
                    'Image': 'sha256:simulated-image',
                    'Config': {'Image': 'worker@sha256:' + 'f'*64, 'Env': [], 'Labels': {ew.LABEL_EPIC: str(layout.epic), ew.LABEL_WORKER: worker}}}]), '')
        value = engine(argv, **kw)
        if list(argv)[:2] == ['docker', 'inspect'] and value.returncode:
            return subprocess.CompletedProcess(argv, value.returncode, value.stdout, 'No such object')
        return value
    monkeypatch.setattr(cycle, '_worker_runner', runner)
    monkeypatch.setattr(cycle, 'subprocess', SimpleNamespace(run=runner, CompletedProcess=subprocess.CompletedProcess))
    original_command = cycle._command
    def external_command(argv, **kw):
        if argv[0].endswith('/await_pr_checks.sh'):
            f['ci_calls'].append(list(argv))
            return subprocess.CompletedProcess(argv, f['ci_exit'], 'simulated current GH CI observation', '')
        if argv[0] == 'docker':
            return runner(argv, capture_output=True, text=True, timeout=kw.get('timeout', 30))
        return original_command(argv, **kw)
    monkeypatch.setattr(cycle, '_command', external_command)
    def inspect(layout, worker, **kw):
        kw.setdefault('runner', runner)
        return REAL_INSPECT(layout, worker, **kw)
    monkeypatch.setattr(ew, 'inspect_checkout', inspect)
    monkeypatch.setattr(cycle, '_assert_stopped', REAL_STOPPED)
    monkeypatch.setattr(cycle, '_assert_live_container', REAL_LIVE)
    monkeypatch.setattr(cycle, 'native_execution_proof', REAL_NATIVE_PROOF)
    ew._record_worker(layout, 6618, state='created', container_id=None, execution_branch='codex/example')
    home = tmp_path / 'qualified-auth-free-codex-home'
    home.mkdir(mode=0o700)
    ew.start_openhands_worker(layout, worker, codex_home=home, image='worker@sha256:' + 'f'*64,
                             budget=ew.Budget('1.0', '1536m', 512), network='epicws',
                             runner=runner, http=f['server'])
    original_api = cycle.closure._api
    def api(executor, cwd, repo, method, endpoint):
        if endpoint.startswith('/pulls/10/commits'):
            return [{'commit': {'message': 'Bounded routine source correction'}}]
        return original_api(executor, cwd, repo, method, endpoint)
    monkeypatch.setattr(cycle.closure, '_api', api)
    if nonclosing:
        f['live']['body'] = f['live']['body'].replace('Fixes #6618', 'Issue-Lifecycle: non-closing')
        f['issue']['body'] = ('## Acceptance Criteria\n- [ ] Live acceptance remains required.\n'
            '  - Verify: runtime receipt: openhands_pr_completion_activation.v1\n')
        monkeypatch.setattr(cycle.closure, '_closing_issue_references', lambda *args: [])
        entry = {**f['entry'], 'head_sha': f['head'], 'engine': 'codex', 'model': 'gpt-6.1-sol',
                 'effort': 'high', 'verify_targets': [f['target']]}
        f['config'].write_text(json.dumps({'admissions': [entry]}))
    f['nonclosing'] = nonclosing
    monkeypatch.setattr(cycle, 'github_fetch', f['fetch'])
    f.update(engine=engine, runner=runner, home=home, verification_runs=verification_runs,
             verification_results=verification_results)
    return f


def stopped(f):
    ew.stop_worker(f['layout'], 'reviewer', reason='fixture verified idle stop', runner=f['runner'])


def tick(f):
    return cycle.advance(f['layout'], f['config'], fetch=f['fetch'], http=f['server'],
                         codex_home=f['home'])['results'][-1]


def test_stopped_reviewer_resumes_through_existing_lifecycle(tmp_path, monkeypatch):
    f = assembled(tmp_path, monkeypatch)
    stopped(f)
    before = cycle._mapping(f['layout'], 'reviewer')
    first = tick(f)
    assert first['action'] == 'independent-review', first
    after = cycle._mapping(f['layout'], 'reviewer')
    assert after['state'] == 'running' and after['container_id'] != before['container_id']
    assert after['takeover']['status'] == 'consumed'
    assert after['work_at_stop'] == before['work_at_stop']
    second = tick(f)
    assert second['action'] == 'reconcile', second
    assert len(f['engine'].runs()) == 2
    posts = [c for c in f['server'].calls if c[0] == 'POST']
    assert len(posts) == 1
    assert posts[0][3]['agent_settings'] == {'agent_kind': 'acp', 'acp_server': 'codex',
                                         'acp_model': 'gpt-6.1-sol', 'acp_effort': 'high'}


def test_reserved_review_retries_after_temporary_prelaunch_refusal(tmp_path, monkeypatch):
    f = assembled(tmp_path, monkeypatch)
    stopped(f)
    before = cycle._mapping(f['layout'], 'reviewer')
    busy = True

    def runner(argv, **kw):
        if (busy and list(argv)[:2] == ['docker', 'ps']
                and 'label=epic-workspace.codex-home=1' in argv):
            return subprocess.CompletedProcess(argv, 0, 'another-worker\n', '')
        return f['runner'](argv, **kw)

    monkeypatch.setattr(cycle, '_worker_runner', runner)
    launches = len(f['engine'].runs())
    first = tick(f)
    assert first['action'] == 'wait', first
    assert 'codex home is already mounted' in first['reason']
    state = cycle.epic_run_state.load_epic_run_state(f['layout'].run_id, root=f['layout'].run_state_dir)
    saved = [row for row in state['compact_receipts'] if row.get('kind') == 'pr_cycle'
             and row.get('number') == 10][0]
    operation = saved['review_operation']
    assert cycle._mapping(f['layout'], 'reviewer') == before
    assert len(f['engine'].runs()) == launches
    assert not [c for c in f['server'].calls if c[0] == 'POST']

    busy = False
    for _ in range(2):
        result = tick(f)
        assert result['action'] == 'reconcile', result
        assert result['operation_id'] == operation
    after = cycle._mapping(f['layout'], 'reviewer')
    assert after['state'] == 'running' and after['container_id'] != before['container_id']
    assert after['takeover']['status'] == 'consumed'
    assert after['work_at_stop'] == before['work_at_stop']
    assert after['conversation']['operation_id'] == operation
    assert len(f['engine'].runs()) == launches + 1
    posts = [c for c in f['server'].calls if c[0] == 'POST']
    assert len(posts) == 1
    assert posts[0][3]['agent_settings'] == {'agent_kind': 'acp', 'acp_server': 'codex',
                                         'acp_model': 'gpt-6.1-sol', 'acp_effort': 'high'}


def reviewed(f):
    first = tick(f)
    assert first['action'] == 'independent-review', first
    mapping = cycle._mapping(f['layout'], 'reviewer')
    cid = mapping['conversation']['id']
    saved = cycle._find(f['layout'], 10, first['identity'])
    criterion = cycle.closure._acceptance_criteria(f['issue']['body'], repo_root=f['worktree'])[0]['criterion_sha256']
    report = {'report_contract': cycle.REPORT_CONTRACT, 'identity': saved['identity'], 'head_sha': f['head'],
        'verdict': 'pass', 'findings': [], 'verify_targets': [f['target']], 'covered_sources': ['app/example.py'],
        'scope_assessment': {'acceptance': 'covered', 'verify_coverage': 'covered', 'limitations': [
            {'kind': kind, 'detail': 'Read-only reviewer limitation; controller retains actual obligations.'}
            for kind in ['evidence_not_rerun', 'ci_not_observed', 'simulated_boundary']]},
        'closing_assessments': {'6618': {'acceptance': 'covered', 'verify_coverage': 'covered', 'limitations': [],
            'criteria': {criterion: {'assessment': 'covered', 'rationale': 'Actual implementation and assertions inspected.'}}}},
        'owner_doc': {'outcome': 'no_change', 'inspected_paths': ['docs/development/DEV_WORKFLOW.md'],
                      'rationale': 'No changed owner contract in this fixture.'}}
    if f['nonclosing']:
        report['closing_assessments'] = {}
        report['scope_assessment']['limitations'].append({'kind': 'out_of_scope_followup',
            'detail': 'Open governor runtime acceptance is deliberately unfinished in this non-closing package.'})
    f['server'].conversations[cid].update(execution_status='finished',
        agent={'kind': 'ACPAgent', 'acp_server': 'codex', 'acp_model': 'gpt-6.1-sol', 'acp_effort': 'high'},
        current_model_id='gpt-6.1-sol', current_effort='high', available_efforts=[{'value': 'high'}],
        agent_state={'acp_session_id': 'simulated-native', 'acp_session_cwd': '/workspace'})
    f['server'].events = [{'kind': 'MessageEvent', 'source': 'agent'}]
    f['server'].final_responses[cid] = json.dumps(report)
    # Native metadata is an external engine port; core native authority remains real.
    monkeyproof = {'operation_id': saved['review_operation'], 'conversation_id': cid,
        'container_id': mapping['container_id'], 'engine': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'high',
        'auth': 'chatgpt', 'source': 'native-session-metadata', 'native_session_id': 'simulated-native',
        'timestamp': '2026-11-16T10:00:00Z'}
    return saved, report, monkeyproof


@pytest.mark.parametrize('nonclosing', [False, True])
@pytest.mark.parametrize('verify_passes', [True, False])
def test_informational_limits_progress_with_current_evidence(
        tmp_path, monkeypatch, nonclosing, verify_passes, synthetic_noexec_tmp):
    f = assembled(tmp_path, monkeypatch, nonclosing=nonclosing, verify_passes=verify_passes)
    saved, report, proof = reviewed(f)
    real_stop = ew.stop_worker
    monkeypatch.setattr(ew, 'stop_worker', lambda *args, **kw: real_stop(*args, **kw, runner=f['runner']))
    calls = []
    # Refuse GH merge at the external command port; it must only be attempted after real gates.
    old_command = cycle._command
    def command(argv, **kw):
        if argv[:3] == ['gh', 'pr', 'merge']:
            calls.append('merge')
            return subprocess.CompletedProcess(argv, 1, '', 'simulated GH refusal')
        return old_command(argv, **kw)
    monkeypatch.setattr(cycle, '_command', command)
    result = tick(f)
    fresh = cycle._find(f['layout'], 10, saved['identity'])
    assert fresh['review'] == report
    assert 'review_gate' in fresh, result
    assert fresh['review_gate']['outcome'] == 'pass', result
    assert f['verification_runs'] == [[f['target']]]
    assert not synthetic_noexec_tmp
    nested = f['verification_results'][0]
    assert nested.returncode == (0 if verify_passes else 1)
    assert ('1 passed' if verify_passes else '1 failed') in nested.stdout
    assert f['issue']['state'] == 'open'
    if not verify_passes:
        # Real failing pytest must survive the simulated port and block merge.
        assert 'AssertionError' in nested.stdout
        assert len(f['ci_calls']) == 1
        assert not calls and 'merge_intent' not in fresh and 'verification' not in fresh
        assert result['action'] == 'wait', result
        assert result['reason'] == 'routine disposition requires fresh actual CI and sandbox Verify evidence'
        return
    assert fresh['verification']['passed'] is True
    assert fresh['verification']['exit_code'] == nested.returncode
    assert len(f['ci_calls']) >= 2
    assert calls.count('merge') == 1, result
    assert fresh['review_disposition']['report_sha256'] == cycle._digest(report)
    assert len(fresh['review_disposition']['items']) == (4 if nonclosing else 3)
    entry = json.loads(f['config'].read_text())['admissions'][0]
    pr = cycle.observation._observe(cycle.observation._Reader(f['fetch'], cycle.time.monotonic), 10)
    pr.update(route='native', check_config={'verify_targets': entry['verify_targets'], 'test_venv': entry['test_venv']})
    pr['review_context'], pr['review_material'] = cycle._review_context(pr)
    cycle._add_transfer_review_context(f['layout'], entry, pr)
    # Existing per-item gate must reject changed report/item evidence against the actual run.
    for fault in ['item', 'report', 'head', 'ci', 'verification', 'original', 'explicit-disposition']:
        altered, changed_entry = copy.deepcopy(fresh), copy.deepcopy(entry)
        if fault == 'item':
            altered['review']['scope_assessment']['limitations'][0]['detail'] += ' changed'
        elif fault == 'report':
            altered['review']['scope_assessment']['acceptance'] += ' changed'
        elif fault == 'head':
            altered['review']['head_sha'] = '0' * 40
        elif fault == 'ci':
            altered['ci']['exit_code'] = 1
        elif fault == 'verification':
            altered['verification']['output_sha256'] = None
        elif fault == 'original':
            altered['report_reconciliations'] = [{'archived': {'review': {'findings': 'unknown'}}}]
        else:
            changed_entry['review_disposition'] = {**fresh['review_disposition'], 'report_sha256': '0'*64}
        with pytest.raises(cycle.CycleError):
            cycle._premerge(f['layout'], pr, changed_entry, altered)
    for field in ['body', 'head', 'owner']:
        old_live, old_task = copy.deepcopy(f['live']), copy.deepcopy(f['task'])
        if field == 'body':
            f['live']['body'] += '\nChanged contract'
        elif field == 'head':
            f['live']['head']['sha'] = '0'*40
        else:
            f['task']['claimed_by'] = 'foreign'
        with pytest.raises(cycle.CycleError):
            cycle._premerge(f['layout'], pr, entry, fresh)
        f['live'].clear(); f['live'].update(old_live)
        f['task'].clear(); f['task'].update(old_task)
    f['ci_exit'] = 1
    with pytest.raises(cycle.CycleError, match='CI'):
        cycle._premerge(f['layout'], pr, entry, fresh)


@pytest.mark.parametrize('fault', ['required', 'unknown', 'protected', 'runtime-closing'])
def test_protected_or_unknown_limits_remain_blocked(tmp_path, monkeypatch, fault):
    f = assembled(tmp_path, monkeypatch)
    saved, report, proof = reviewed(f)
    if fault in ('required', 'unknown'):
        report['scope_assessment']['limitations'].append({'kind': 'acceptance_gap' if fault == 'required' else 'unclassified',
                                                        'detail': 'required runtime missing'})
    elif fault == 'protected':
        report['verdict'] = 'findings'
        report['findings'] = [{'severity': 'P3', 'category': 'documentation', 'protected_class': 'false_green',
            'summary': 'protected classification', 'file': 'app/example.py', 'line': 1, 'failure_scenario': 'false acceptance'}]
    else:
        f['issue']['body'] += '\n- [ ] Actual runtime must pass.\n  - Verify: runtime receipt: required.runtime.v1\n'
    cid = proof['conversation_id']
    f['server'].final_responses[cid] = json.dumps(report)
    real_stop = ew.stop_worker
    monkeypatch.setattr(ew, 'stop_worker', lambda *args, **kw: real_stop(*args, **kw, runner=f['runner']))
    result = tick(f)
    assert result['action'] == ('independent-review' if fault == 'unknown' else 'wait'), result
    assert not f['verification_runs'] and not f['ci_calls']
    assert cycle._find(f['layout'], 10, saved['identity']).get('review_gate', {}).get('outcome') != 'pass'


@pytest.mark.parametrize('fault', ['running-foreign', 'starting', 'unknown', 'publication', 'auth-path',
                                  'auth-change', 'image', 'dirty', 'owner'])
def test_stopped_start_refusals_never_create_another_writer(tmp_path, monkeypatch, fault):
    f = assembled(tmp_path, monkeypatch)
    if fault != 'running-foreign':
        stopped(f)
    layout = f['layout']
    before = cycle._mapping(layout, 'reviewer')
    if fault == 'running-foreign':
        ew._record_worker(layout, 6618, conversation={'id': 'foreign', 'status': 'unknown'})
    elif fault in ('starting', 'unknown'):
        ew._record_worker(layout, 6618, state=fault)
    elif fault == 'publication':
        ew._record_worker(layout, 6618, publication_ops=[{'id': 'pending', 'kind': 'branch_push',
            'branch': 'codex/example', 'status': 'intended'}])
    elif fault == 'auth-path':
        ew._record_worker(layout, 6618, auth_paths=None)
    elif fault == 'auth-change':
        f['home'] = tmp_path / 'different-auth-home'
        f['home'].mkdir(mode=0o700)
    elif fault == 'image':
        ew._record_worker(layout, 6618, image='unsafe:latest')
    elif fault == 'dirty':
        (layout.checkout('reviewer') / 'partial.txt').write_text('preserve this partial work')
    else:
        f['task']['claimed_by'] = 'foreign'
    launches = len(f['engine'].runs())
    for _ in range(2):
        result = tick(f)
        assert result['action'] == 'wait', result
    assert len(f['engine'].runs()) == launches
    assert not [c for c in f['server'].calls if c[0] == 'POST']
    assert cycle._mapping(layout, 'reviewer')['container_id'] == before['container_id']


def test_lost_stopped_worker_create_preserves_unknown_effect(tmp_path, monkeypatch):
    f = assembled(tmp_path, monkeypatch)
    stopped(f)
    f['engine'].lose_container_create = True
    first = tick(f)
    mapping = cycle._mapping(f['layout'], 'reviewer')
    assert first['action'] == 'wait' and mapping['state'] == 'starting'
    assert len(f['engine'].runs()) == 2
    assert tick(f)['action'] == 'wait'
    assert len(f['engine'].runs()) == 2
    assert not [c for c in f['server'].calls if c[0] == 'POST']
