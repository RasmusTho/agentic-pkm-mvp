from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
from uuid import uuid4
from zipfile import ZipFile

import pytest
import yaml

from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
from app.ops.pg_acceptance import MINIMUM_SELECTED, identity
from scripts import postmerge_dev_test as driver

SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
ROOT = Path(__file__).resolve().parents[2]

HEAVY_PASSED = {'result': 'passed', 'failures': [], 'selected': 500, 'passed': 490, 'failed': 0,
                'skipped': 10, 'docker_skipped': 0}


@pytest.fixture(autouse=True)
def _no_live_heavy_transport(monkeypatch):
    # A committed TEST candidate triggers the heavy step on the next tick; keep
    # tests off the real SSH launcher and GitHub dispatch.
    sent = []
    monkeypatch.setattr(driver, 'native_heavy', lambda candidate: dict(HEAVY_PASSED))
    monkeypatch.setattr(driver, 'dispatch_verdict', lambda candidate, heavy: sent.append((candidate, heavy)))
    return sent


def _native_receipt(channel, candidate, result='committed'):
    operation_id = candidate.operation_id(channel)
    receipt = {'channel': channel, 'terminal_result': result, 'operation_id': operation_id}
    if result == 'committed':
        receipt['pg_acceptance'] = {**identity(candidate.sha, candidate.digest, channel, operation_id),
                                    'result': 'passed', 'selected': MINIMUM_SELECTED, 'passed': MINIMUM_SELECTED,
                                    'resource_tree': 'e' * 40, 'app_image_id': 'sha256:' + 'f' * 64,
                                    'report_hash': '0' * 64}
    return receipt


def _build():
    run = {'id': 123, 'run_attempt': 1, 'event': 'push', 'status': 'completed',
           'conclusion': 'success', 'head_branch': 'main', 'head_sha': SHA,
           'path': driver.BUILD_WORKFLOW, 'repository': {'full_name': driver.REPOSITORY},
           'head_repository': {'full_name': driver.REPOSITORY}}
    proof = {'contract': 'app-image-tts-engine-proof.v1', 'candidate_sha': SHA,
             'image': driver.IMAGE_REPOSITORY + ':' + SHA,
             'image_ref': driver.IMAGE_REPOSITORY + '@' + DIGEST, 'image_index_digest': DIGEST,
             'probe_scope': 'package_presence_cli_load_import_app_health',
             'platforms': [{'platform': p, 'platform_digest': DIGEST, 'probe_result': 'pass'}
                           for p in ('linux/amd64', 'linux/arm64')]}
    return run, proof


def _artifact(proof, name='app-image-tts-engine-proof.json'):
    content = io.BytesIO()
    with ZipFile(content, 'w') as archive:
        archive.writestr(name, json.dumps(proof))
    raw = content.getvalue()
    metadata = {'id': 456, 'name': 'app-image-tts-engine-proof-' + SHA, 'expired': False,
                'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'size_in_bytes': len(raw)}
    return metadata, raw


def test_source_build_admission_is_bound_to_main_push_and_exact_artifact():
    run, proof = _build()
    metadata, raw = _artifact(proof)
    candidate = driver.validate_artifact(run, metadata, raw)
    assert candidate == driver.Candidate(SHA, DIGEST, 123, 1, 456)
    for key, value in [('event', 'pull_request'), ('event', 'workflow_dispatch'),
                       ('conclusion', 'failure'), ('head_branch', 'feature'),
                       ('path', '.github/workflows/foreign.yml'), ('head_sha', 'bad'),
                       ('head_repository', {'full_name': 'foreign/repo'})]:
        with pytest.raises(driver.CandidateRefused):
            driver.validate_artifact({**run, key: value}, metadata, raw)
    for key, value in [('candidate_sha', 'c' * 40), ('image_index_digest', 'tag'),
                       ('image_ref', 'foreign/image@' + DIGEST), ('platforms', [])]:
        bad_metadata, bad_raw = _artifact({**proof, key: value})
        with pytest.raises(driver.CandidateRefused):
            driver.validate_artifact(run, bad_metadata, bad_raw)
    with pytest.raises(driver.CandidateRefused):
        driver.validate_artifact(run, metadata, raw + b'drift')
    unsafe_metadata, unsafe_raw = _artifact(proof, '../injected.py')
    with pytest.raises(driver.CandidateRefused):
        driver.validate_artifact(run, unsafe_metadata, unsafe_raw)


def test_rerun_artifact_is_bound_to_the_actual_successful_image_job(monkeypatch):
    run, proof = _build()
    run['run_attempt'] = 2
    old, old_raw = _artifact(proof)
    current, current_raw = _artifact({**proof, 'run_id': 123, 'run_attempt': 2})
    current.update(id=789, name=f'app-image-tts-engine-proof-{SHA}-attempt-2')
    jobs = [{'name': driver.BUILD_JOB, 'run_id': 123, 'run_attempt': attempt,
             'status': 'completed', 'conclusion': 'success'} for attempt in (1, 2)]
    responses = {
        f'repos/{driver.REPOSITORY}/actions/runs/123': json.dumps(run).encode(),
        f'repos/{driver.REPOSITORY}/actions/runs/123/jobs?filter=all&per_page=100':
            json.dumps({'total_count': 2, 'jobs': jobs}).encode(),
        f'repos/{driver.REPOSITORY}/actions/runs/123/artifacts?per_page=100':
            json.dumps({'total_count': 2, 'artifacts': [old, current]}).encode(),
        f'repos/{driver.REPOSITORY}/actions/artifacts/789/zip': current_raw,
        f'repos/{driver.REPOSITORY}/actions/artifacts/456/zip': old_raw,
    }
    monkeypatch.setattr(driver, '_github', lambda path: responses[path])
    assert driver.load_candidate(123) == driver.Candidate(SHA, DIGEST, 123, 2, 789)

    # A missing current image proof cannot silently fall back to prior output.
    responses[f'repos/{driver.REPOSITORY}/actions/runs/123/artifacts?per_page=100'] = json.dumps(
        {'total_count': 1, 'artifacts': [old]}).encode()
    with pytest.raises(driver.CandidateRefused, match='artifact_missing_or_ambiguous'):
        driver.load_candidate(123)

    # Rerunning only a different failed job reuses the authenticated successful
    # image job's first-attempt proof, without requiring another image build.
    responses[f'repos/{driver.REPOSITORY}/actions/runs/123/jobs?filter=all&per_page=100'] = json.dumps(
        {'total_count': 1, 'jobs': jobs[:1]}).encode()
    assert driver.load_candidate(123) == driver.Candidate(SHA, DIGEST, 123, 2, 456)


@pytest.mark.parametrize('field,value', [('run_id', 999), ('run_attempt', 1), ('run_attempt', True)])
def test_attempt_named_proof_rejects_mismatched_producer_identity(field, value):
    run, proof = _build()
    run['run_attempt'] = 2
    metadata, raw = _artifact({**proof, 'run_id': 123, 'run_attempt': 2, field: value})
    metadata['name'] = f'app-image-tts-engine-proof-{SHA}-attempt-2'
    with pytest.raises(driver.CandidateRefused, match='image_proof_refused'):
        driver.validate_artifact(run, metadata, raw)


def test_dev_failure_blocks_test_and_success_preserves_same_candidate():
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    calls, outcomes = [], []

    def deploy(channel, received):
        calls.append((channel, received))
        return _native_receipt(channel, received)

    assert driver.deliver(candidate, deploy=deploy, current_main=lambda: SHA, emit=outcomes.append) == 0
    assert calls == [('dev', candidate), ('test', candidate)]
    assert [o['result'] for o in outcomes] == ['started', 'passed', 'started', 'passed']
    calls.clear()
    outcomes.clear()

    def failure(channel, received):
        calls.append(channel)
        raise RuntimeError('secret-canary')

    assert driver.deliver(candidate, deploy=failure, current_main=lambda: SHA, emit=outcomes.append) == 78
    assert calls == ['dev']
    assert 'secret-canary' not in json.dumps(outcomes)
    calls.clear()
    assert driver.deliver(candidate, deploy=deploy, current_main=lambda: 'c' * 40, emit=outcomes.append) == 0
    assert not calls
    assert outcomes[-1]['result'] == 'superseded_before_deployment'


def test_native_digest_binding_and_manual_request_compatibility(tmp_path, monkeypatch):
    plan = DeployPlan('dev', SHA, ('db', 'api'), ('postgres-db', 'postgres-api'))
    assert set(plan.payload()) == {'channel', 'revision', 'services', 'consumers', 'ack_forward_only'}
    automatic = replace(plan, image_digest=DIGEST, automatic=True)
    automatic.validate()
    journal = DeployJournal(tmp_path / 'journal', 'dev')
    operation = str(uuid4())
    journal.bind_request(operation, automatic, False, create=True)
    journal.bind_request(operation, automatic, False)
    for changed in (replace(automatic, image_digest='sha256:' + 'c' * 64),
                    replace(automatic, automatic=False), plan):
        with pytest.raises(PostgresDeployError):
            journal.bind_request(operation, changed, False)
    for changed in (replace(automatic, channel='prod'), replace(automatic, ack_forward_only=True),
                    replace(automatic, image_digest=None), replace(automatic, image_digest='latest')):
        with pytest.raises(PostgresDeployError):
            changed.validate()
    from app.ops import postgres_deploy_linux as linux
    requests = []

    def ssh(_argv, **kwargs):
        requests.append(json.loads(kwargs['input']))
        return SimpleNamespace(returncode=0, stdout='{"ready":true,"empty":false}')

    monkeypatch.setattr(linux.subprocess, 'run', ssh)
    remote = linux.SshDeployRemote('ygg-dev')
    remote.prepare(operation, automatic, bootstrap=False)
    assert requests[-1]['plan']['image_digest'] == DIGEST
    assert requests[-1]['plan']['automatic'] is True
    remote.prepare(operation, plan, bootstrap=False)
    assert set(requests[-1]['plan']) == set(plan.payload())


def test_automatic_migration_guard_runs_before_native_effects(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    from app.release_channels import reversibility

    config = SimpleNamespace(root=tmp_path, channel='dev')
    effects = linux.LinuxEffects(config)
    plan = DeployPlan('dev', SHA, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=DIGEST, automatic=True)
    monkeypatch.setattr(effects, 'validate_plan', lambda _plan: None)
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _config: False)
    monkeypatch.setattr(linux, '_migration_baseline', lambda *_args, **_kwargs: '')
    monkeypatch.setattr(linux, '_git_bytes', lambda *_args: (
        b'app/alembic/versions/missing_marker.py\n' if 'ls-tree' in _args
        else b'revision = "missing_marker"\ndown_revision = None\n'))
    monkeypatch.setattr(linux, 'vm_selected_values', lambda *_args: pytest.fail('credential materialization'))
    with pytest.raises(reversibility.MigrationMarkerError):
        effects.preflight(plan)
    assert effects.password is None


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_automatic_nonprod_forward_only_preserves_migration_policy(tmp_path, channel):
    from tests.deploy.test_deploy_channel import _assert_nonprod_forward_only_migration_policy

    _assert_nonprod_forward_only_migration_policy(tmp_path, channel, automatic=True)


def test_automatic_native_guard_refuses_inherited_ack_before_credentials(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    config = SimpleNamespace(root=tmp_path, channel='dev')
    directory = tmp_path / 'config/deploy'
    directory.mkdir(parents=True)
    (directory / 'dev.migration-pending.env').write_text(
        f'FROM_SHA={SHA}\nTARGET_SHA={SHA}\nACK_FORWARD_ONLY=1\n')
    effects = linux.LinuxEffects(config)
    plan = DeployPlan('dev', SHA, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=DIGEST, automatic=True)
    monkeypatch.setattr(effects, 'validate_plan', lambda _plan: None)
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _config: False)
    monkeypatch.setattr(linux, 'vm_selected_values', lambda *_args: pytest.fail('credential materialization'))
    with pytest.raises(PostgresDeployError):
        effects.preflight(plan)
    assert effects.password is None


def test_workflow_is_serialized_and_secret_separated():
    workflow = yaml.load((ROOT / '.github/workflows/postmerge-dev-test.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'workflow_run'}
    assert workflow['on']['workflow_run'] == {'workflows': ['App Image Build'], 'types': ['completed'],
                                            'branches': ['main']}
    assert workflow['concurrency']['cancel-in-progress'] == 'false'
    job = workflow['jobs']['admit']
    assert "event == 'push'" in job['if'] and "conclusion == 'success'" in job['if']
    assert job['runs-on'] == 'ubuntu-latest'
    assert 'environment' not in job and 'secrets' not in json.dumps(workflow)
    assert job['steps'][0]['with']['persist-credentials'] == 'false'
    assert job['steps'][1]['env']['SOURCE_RUN_ID'] == '${{ github.event.workflow_run.id }}'
    assert '--admit-only' in job['steps'][1]['run']
    assert workflow['permissions'] == {'contents': 'read', 'actions': 'read'}


def test_native_child_keeps_github_token_outside_deployment(monkeypatch):
    calls = []
    monkeypatch.setenv('GH_TOKEN', 'secret-canary')
    monkeypatch.setenv('GITHUB_TOKEN', 'secret-canary')

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'operation_id': driver.Candidate(SHA, DIGEST, 123, 1, 456).operation_id('dev'),
            'channel': 'dev', 'kind': 'deploy',
            'stage': 'committed', 'terminal_result': 'committed',
            'pg_acceptance': _native_receipt('dev', driver.Candidate(SHA, DIGEST, 123, 1, 456))['pg_acceptance']}))

    monkeypatch.setattr(driver.subprocess, 'run', run)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    driver.native_deploy('dev', candidate)
    argv, options = calls[0]
    assert argv[-4:] == ['--existing-secrets-only', '--automatic', '--image-digest', DIGEST]
    assert 'GH_TOKEN' not in options['env'] and 'GITHUB_TOKEN' not in options['env']


@pytest.mark.parametrize('reason', ['embedding_probe_client_failed', 'embedding_probe_identity_mismatch',
    'embedding_probe_generation_failed', 'embedding_probe_vector_invalid', 'embedding_probe_cleanup_failed',
    'embedding_probe_failed', 'embedding_guard_refused', 'source_worker_timeout'])
@pytest.mark.parametrize('resume', [False, True])
def test_embedding_probe_subreason_survives_controller_receipt_and_checkpoint(tmp_path, monkeypatch, capsys, resume, reason):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    receipt = {**_native_receipt('dev', candidate, 'failed'), 'kind': 'deploy', 'stage': 'failed',
               'source_failure': reason}
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=78, stdout=json.dumps(receipt), stderr='private output'))
    assert driver.native_deploy('dev', candidate) == receipt
    path = tmp_path / 'postmerge-dev-test.json'
    if resume:
        driver._save_outcome(path, candidate, {
            'source_sha': SHA, 'image_digest': DIGEST, 'source_run_id': 123,
            'source_run_attempt': 1, 'artifact_id': 456, 'channel': 'dev',
            'result': 'pending', 'operation_id': candidate.operation_id('dev'),
        })
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate,
                       current_main=lambda: SHA) == 78
    checkpoint = json.loads(path.read_text())
    assert checkpoint['phase'] == 'failed'
    assert checkpoint['outcome']['source_failure'] == reason
    assert 'private output' not in capsys.readouterr().out
    driver._validate_checkpoint(checkpoint)
    checkpoint['outcome']['source_failure'] = 'private payload'
    with pytest.raises(driver.CandidateRefused):
        driver._validate_checkpoint(checkpoint)


def test_embedding_guard_refusal_survives_controller_receipt_and_checkpoint(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    receipt = {**_native_receipt('dev', candidate, 'failed'), 'kind': 'deploy', 'stage': 'failed',
               'source_failure': 'embedding_guard_refused'}
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=78, stdout=json.dumps(receipt), stderr='private output'))
    assert driver.native_deploy('dev', candidate) == receipt
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate,
                       current_main=lambda: SHA) == 78
    checkpoint = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert checkpoint['phase'] == 'failed'
    assert checkpoint['outcome']['source_failure'] == 'embedding_guard_refused'
    driver._validate_checkpoint(checkpoint)


@pytest.mark.parametrize('reason,terminal', [('private payload', 'failed'), (None, 'failed'),
                                          ('source_worker_timeout', 'committed')])
def test_native_source_failure_controller_rejects_untrusted_or_success_metadata(monkeypatch, reason, terminal):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    receipt = {**_native_receipt('dev', candidate, terminal), 'kind': 'deploy', 'stage': terminal,
               'source_failure': reason}
    monkeypatch.setattr(driver.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=0 if terminal == 'committed' else 78, stdout=json.dumps(receipt), stderr=''))
    with pytest.raises(driver.CandidateRefused):
        driver.native_deploy('dev', candidate)


def test_controller_checkpoint_deduplicates_and_resumes_same_candidate(tmp_path):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    calls = []

    def deploy(channel, received):
        calls.append((channel, received))
        return _native_receipt(channel, received)

    options = {'build': lambda: 123, 'load': lambda _run: candidate,
               'deploy': deploy, 'current_main': lambda: SHA}
    assert driver.poll(tmp_path, **options) == 0
    assert driver.poll(tmp_path, **options) == 0
    assert calls == [('dev', candidate), ('test', candidate)]
    checkpoint = tmp_path / 'postmerge-dev-test.json'
    stored = json.loads(checkpoint.read_text())
    assert stored.pop('heavy')['dispatch'] == 'sent'
    stored['channel'] = stored['outcome']['channel'] = 'dev'
    stored['outcome'].update(_native_receipt('dev', candidate))
    stored['outcome'].pop('terminal_result')
    driver._atomic_checkpoint(checkpoint, stored)
    calls.clear()
    # A newer main does not abandon a dev-verified chain on restart.
    assert driver.poll(tmp_path, build=lambda: pytest.fail('new build lookup'),
                       deploy=deploy, current_main=lambda: 'c' * 40) == 0
    assert calls == [('test', candidate)]


def test_controller_recovers_only_native_terminal_evidence(tmp_path):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    outcomes = []
    driver.deliver(candidate, deploy=lambda *_args: (_ for _ in ()).throw(RuntimeError()),
                   current_main=lambda: SHA, emit=outcomes.append)
    path = tmp_path / 'postmerge-dev-test.json'
    driver._save_outcome(path, candidate, outcomes[0])
    calls = []

    def reconcile(channel, received):
        calls.append((channel, received))
        return _native_receipt(channel, received)

    def deploy(channel, received):
        assert channel == 'test' and received == candidate
        return _native_receipt(channel, received)

    assert driver.poll(tmp_path, resume=reconcile, deploy=deploy) == 0
    assert calls == [('dev', candidate)]
    # An unreadable pending operation cannot start a fresh deployment.
    driver._save_outcome(path, candidate, outcomes[0])
    with pytest.raises(driver.CandidateRefused):
        driver.poll(tmp_path, resume=lambda *_args: (_ for _ in ()).throw(driver.CandidateRefused('pending')),
                    deploy=lambda *_args: pytest.fail('fresh activation'))


def test_controller_lock_and_atomic_checkpoint_survive_stale_temporary(tmp_path):
    tmp_path.chmod(0o700)
    with driver.checkpoint_lock(tmp_path):
        with pytest.raises(BlockingIOError):
            with driver.checkpoint_lock(tmp_path):
                pytest.fail('duplicate controller')
    path = tmp_path / 'postmerge-dev-test.json'
    path.with_suffix('.tmp').write_text('interrupted old writer')
    driver._atomic_checkpoint(path, {'result': 'safe'})
    assert json.loads(path.read_text()) == {'result': 'safe'}
    assert path.stat().st_mode & 0o777 == 0o600


def test_controller_launch_agent_uses_fixed_reviewed_tooling_without_secrets():
    from scripts.install_postmerge_controller import launch_agent
    config = launch_agent(Path('/tooling'), Path('/tooling/.venv/bin/python'),
                          Path('/opt/homebrew/bin/gh'), Path('/private/state'))
    assert config['ProgramArguments'] == ['/tooling/.venv/bin/python', '/tooling/scripts/postmerge_dev_test.py',
                                         '--latest', '--state-directory', '/private/state']
    assert config['StartInterval'] == 60 and config['RunAtLoad'] is True
    assert set(config['EnvironmentVariables']) == {'PATH'}
    assert 'prod' not in json.dumps(config) and 'TOKEN' not in json.dumps(config)


def _installer_repository(path):
    path.mkdir()
    def git(*args):
        return subprocess.run(['git', '-C', str(path), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    git('init', '--quiet', '-b', 'main')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    for name in ('app/__init__.py', 'app/ops/__init__.py',
                 'app/ops/postgres_deploy_host.py', 'app/ops/postgres_deploy_linux.py',
                 'scripts/postmerge_dev_test.py'):
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('')
    git('add', '.')
    git('commit', '--quiet', '-m', 'Reviewed fixture')
    return git


@pytest.mark.parametrize('origin', [
    'self', 'https://github.com/foreign/agentic-pkm-mvp.git',
    'https://dummy-credential@github.com/RasmusTho/agentic-pkm-mvp.git',
    'https://github.com/RasmusTho/agentic-pkm-mvp.git?source=foreign',
])
def test_installer_refuses_foreign_origin_before_fetch_or_import(tmp_path, monkeypatch, origin):
    from scripts import install_postmerge_controller as installer
    checkout = tmp_path / 'checkout'
    git = _installer_repository(checkout)
    git('remote', 'add', 'origin', str(checkout) if origin == 'self' else origin)
    git('update-ref', 'refs/remotes/origin/main', 'HEAD')
    run = subprocess.run
    def observed(command, **kwargs):
        assert 'fetch' not in command and '-c' not in command
        return run(command, **kwargs)
    monkeypatch.setattr(installer.subprocess, 'run', observed)
    with pytest.raises(ValueError, match='canonical reviewed repository'):
        installer.require_reviewed_checkout(checkout, Path(sys.executable).resolve())


@pytest.mark.parametrize('fault', ['push', 'multiple', 'rewrite', 'forged_tracking_head',
                                  'replacement', 'graft', 'assume_unchanged', 'skip_worktree', None])
def test_installer_binds_effective_repository_and_fetched_main(tmp_path, monkeypatch, fault):
    from scripts import install_postmerge_controller as installer
    reviewed = tmp_path / 'reviewed'
    _installer_repository(reviewed)
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'clone', '--quiet', str(reviewed), str(checkout)], check=True)
    def git(*args):
        subprocess.run(['git', '-C', str(checkout), *args], capture_output=True, check=True)
    canonical = 'https://github.com/RasmusTho/agentic-pkm-mvp.git'
    git('remote', 'set-url', 'origin', canonical)
    if fault == 'push':
        git('remote', 'set-url', '--push', 'origin', 'https://github.com/foreign/repo.git')
    elif fault == 'multiple':
        git('remote', 'set-url', '--add', 'origin', canonical)
    elif fault == 'rewrite':
        git('config', 'url.https://github.com/foreign/.insteadOf', 'https://github.com/RasmusTho/')
    elif fault in ('assume_unchanged', 'skip_worktree'):
        source = 'app/ops/postgres_deploy_host.py'
        (checkout / source).write_text("raise RuntimeError('unreviewed checkout code')\n")
        git('update-index', '--' + fault.replace('_', '-'), source)
    elif fault in ('forged_tracking_head', 'replacement', 'graft'):
        reviewed_head = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'],
                                       capture_output=True, text=True, check=True).stdout.strip()
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (checkout / 'foreign').write_text('not on canonical main')
        git('add', 'foreign')
        git('commit', '--quiet', '-m', 'Foreign head')
        if fault == 'forged_tracking_head':
            git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        elif fault == 'replacement':
            git('replace', '--graft', reviewed_head, 'HEAD')
        else:
            foreign_head = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'],
                                          capture_output=True, text=True, check=True).stdout.strip()
            (checkout / '.git/info/grafts').write_text(reviewed_head + ' ' + foreign_head + '\n')
    run = subprocess.run
    effects = []
    monkeypatch.setenv('GIT_DIR', str(reviewed / '.git'))
    def observed(command, **kwargs):
        if 'fetch' in command:
            effects.append('fetch')
            assert command[-4:] == ['--no-tags', '--no-recurse-submodules', 'origin', 'refs/heads/main']
            command = list(command)
            command[command.index('origin')] = str(reviewed)
        elif '-c' in command:
            effects.append('import')
        return run(command, **kwargs)
    monkeypatch.setattr(installer.subprocess, 'run', observed)
    if fault is None:
        installer.require_reviewed_checkout(checkout, Path(sys.executable).resolve())
        assert effects == ['fetch', 'import']
    else:
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            installer.require_reviewed_checkout(checkout, Path(sys.executable).resolve())
        assert effects == (['fetch'] if fault in ('forged_tracking_head', 'replacement', 'graft') else [])


@pytest.mark.parametrize('crash', ['before_native_call', 'after_remote_commit', 'after_host_finish'])
def test_controller_crash_reuses_exact_native_id_and_terminal_receipt(tmp_path, crash):
    from app.ops.host_secret_controller import HostSecretController
    from app.ops.postgres_deploy import deploy_from_host
    state = tmp_path / 'poll'
    state.mkdir(mode=0o700)
    controller = HostSecretController(tmp_path / 'host')
    admin = SimpleNamespace(controller=controller, check_selected=lambda *_args: [])
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    events = []
    lost = False

    class Remote:
        def __init__(self, channel):
            self.journal = DeployJournal(tmp_path / 'vm', channel)

        def prepare(self, operation_id, plan, *, bootstrap):
            self.journal.bind_request(operation_id, plan, bootstrap, create=True)
            self.journal.write(operation_id, 'prepared')
            events.append(('prepare', plan.channel, operation_id))
            return False

        def activate(self, operation_id, plan):
            nonlocal lost
            for stage in ('preflighted', 'materialized', 'authenticating', 'activating', 'committed'):
                self.journal.write(operation_id, stage,
                                   _native_receipt(plan.channel, candidate)['pg_acceptance'] if stage == 'committed' else None)
            events.append(('activate', plan.channel, operation_id))
            if crash == 'after_remote_commit' and plan.channel == 'dev' and not lost:
                lost = True
                raise RuntimeError('lost reply')
            return self.journal.read()

        def reconcile_failed(self, operation_id, plan):
            self.journal.bind_request(operation_id, plan, False)
            receipt = self.journal.read()
            assert receipt.operation_id == operation_id and receipt.terminal_result == 'committed'
            events.append(('read-terminal', plan.channel, operation_id))
            return receipt

    def deploy(channel, received):
        nonlocal lost
        if crash == 'before_native_call' and channel == 'dev' and not lost:
            lost = True
            raise RuntimeError('interrupted invocation')
        plan = DeployPlan(channel, received.sha, ('db', 'api'), ('postgres-db', 'postgres-api'),
                          image_digest=received.digest, automatic=True)
        receipt = deploy_from_host(admin, Remote(channel), plan, qualified=lambda: pytest.fail('bootstrap'),
                                   allow_bootstrap=False, operation_id=received.operation_id(channel))
        if crash == 'after_host_finish' and channel == 'dev' and not lost:
            lost = True
            raise RuntimeError('checkpoint gap')
        return receipt.payload()

    options = {'build': lambda: 123, 'load': lambda _run: candidate, 'deploy': deploy,
               'resume': deploy, 'current_main': lambda: SHA}
    assert driver.poll(state, **options) == 78
    assert json.loads((state / 'postmerge-dev-test.json').read_text())['phase'] == 'pending'
    assert driver.poll(state, **options) == 0
    assert driver.poll(state, **options) == 0
    assert [entry for entry in events if entry[0] == 'activate'] == [
        ('activate', 'dev', candidate.operation_id('dev')),
        ('activate', 'test', candidate.operation_id('test')),
    ]
    assert candidate.operation_id('dev') != candidate.operation_id('test')
    # The existing host history remains valid; no duplicate prepared/sent entries
    # are appended when a completed operation is read again.
    with controller._locked_journal() as descriptor:
        assert controller._pending(descriptor) is None


def test_native_completed_replay_refuses_changed_digest_and_foreign_pending(tmp_path):
    from app.ops.host_secret_controller import HostSecretAdmissionError, HostSecretController, TerminalEvidence
    from app.ops.postgres_deploy import deploy_from_host
    controller = HostSecretController(tmp_path / 'host')
    operation_id = driver.Candidate(SHA, DIGEST, 123, 1, 456).operation_id('dev')
    plan = DeployPlan('dev', SHA, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=DIGEST, automatic=True)
    journal = DeployJournal(tmp_path / 'vm', 'dev')
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'authenticating', 'activating', 'committed'):
        journal.write(operation_id, stage)
    with controller.deploy_operation('dev', allow_bootstrap=False, operation_id=operation_id) as (operation, resumed):
        assert not resumed
        operation.prepare_mutation()
        operation.finish(TerminalEvidence(operation_id, 'deploy', 'dev', 'committed', 'remote-terminal'))
    history = (controller.directory / 'operations.jsonl').read_bytes()
    with controller.deploy_operation('dev', allow_bootstrap=False, operation_id=operation_id) as (operation, resumed):
        assert resumed and operation.completed_result == 'committed'
        with pytest.raises(HostSecretAdmissionError):
            operation.prepare_mutation()
        with pytest.raises(HostSecretAdmissionError):
            operation.finish(TerminalEvidence(operation_id, 'deploy', 'dev', 'aborted', 'remote-terminal'))
        operation.finish(TerminalEvidence(operation_id, 'deploy', 'dev', 'committed', 'remote-terminal'))
    assert (controller.directory / 'operations.jsonl').read_bytes() == history

    class Remote:
        def reconcile_failed(self, identifier, received):
            journal.bind_request(identifier, received, False)
            return journal.read()

        def prepare(self, *_args, **_kwargs):
            pytest.fail('completed deployment sent again')

    admin = SimpleNamespace(controller=controller, check_selected=lambda *_args: pytest.fail('new secret read'))
    with pytest.raises(PostgresDeployError):
        deploy_from_host(admin, Remote(), replace(plan, image_digest='sha256:' + 'c' * 64),
                         qualified=lambda: pytest.fail('bootstrap'), allow_bootstrap=False, operation_id=operation_id)
    assert (controller.directory / 'operations.jsonl').read_bytes() == history
    with controller.deploy_operation('dev', allow_bootstrap=False) as (operation, _resumed):
        operation.prepare_mutation()
    with pytest.raises(HostSecretAdmissionError):
        with controller.deploy_operation('dev', allow_bootstrap=False, operation_id=operation_id):
            pytest.fail('foreign pending operation adopted')


def test_controller_known_failure_does_not_block_next_candidate(tmp_path):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    next_candidate = driver.Candidate('c' * 40, 'sha256:' + 'd' * 64, 124, 1, 457)
    calls = []

    def deploy(channel, received):
        calls.append((channel, received))
        return _native_receipt(channel, received, 'failed' if received == candidate else 'committed')

    options = {'build': lambda: 123, 'load': lambda _run: candidate, 'deploy': deploy, 'current_main': lambda: SHA}
    assert driver.poll(tmp_path, **options) == 78
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['phase'] == 'failed'
    assert driver.poll(tmp_path, resume=lambda *_args: pytest.fail('completed failure is pending'), **options) == 0
    assert driver.poll(tmp_path, build=lambda: 124, load=lambda _run: next_candidate,
                       deploy=deploy, current_main=lambda: next_candidate.sha) == 0
    assert calls == [('dev', candidate), ('dev', next_candidate), ('test', next_candidate)]


def test_vm_fetches_new_candidate_objects_without_checkout_or_credentials(tmp_path, monkeypatch):
    from app.ops import postgres_deploy_linux as linux
    upstream = tmp_path / 'upstream'
    vm = tmp_path / 'vm'

    def git(*arguments, cwd=None):
        return subprocess.check_output(['git', *arguments], cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip()

    git('init', str(upstream))
    (upstream / 'candidate').write_text('old')
    git('add', 'candidate', cwd=upstream)
    git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'baseline', cwd=upstream)
    git('clone', str(upstream), str(vm))
    baseline = git('rev-parse', 'HEAD', cwd=vm)
    (upstream / 'candidate').write_text('new')
    git('add', 'candidate', cwd=upstream)
    git('-c', 'user.name=fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'candidate', cwd=upstream)
    revision = git('rev-parse', 'HEAD', cwd=upstream)
    real_run = linux.subprocess.run
    fetches = []
    monkeypatch.setenv('BWS_ACCESS_TOKEN', 'secret-canary')
    monkeypatch.setenv('GH_TOKEN', 'secret-canary')

    def run(argv, **options):
        if 'fetch' in argv:
            assert argv[-2:] == ['https://github.com/RasmusTho/agentic-pkm-mvp.git', revision]
            assert 'BWS_ACCESS_TOKEN' not in options['env'] and 'GH_TOKEN' not in options['env']
            fetches.append(argv)
            argv = [*argv[:-2], str(upstream), revision]
        return real_run(argv, **options)

    monkeypatch.setattr(linux.subprocess, 'run', run)
    linux.ensure_candidate_object(SimpleNamespace(root=vm), revision)
    linux.ensure_candidate_object(SimpleNamespace(root=vm), revision)
    assert len(fetches) == 1
    assert git('rev-parse', 'HEAD', cwd=vm) == baseline
    assert git('show', revision + ':candidate', cwd=vm) == 'new'
    assert (vm / 'candidate').read_text() == 'old'


def test_controller_script_entrypoint_imports_without_pythonpath(tmp_path):
    script = ROOT / 'scripts/postmerge_dev_test.py'
    result = subprocess.run([sys.executable, '-I', '-S', str(script), '--help'], cwd=tmp_path,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert '--source-run' in result.stdout and '--latest' in result.stdout


def test_installer_script_entrypoint_imports_without_pythonpath(tmp_path):
    script = ROOT / 'scripts/install_postmerge_controller.py'
    code = '''
import pathlib, runpy, sys
sys.path[0] = str(pathlib.Path(sys.argv[1]).parent)
entry = runpy.run_path(sys.argv[1])
globals_ = entry['main'].__globals__
globals_['sys'].platform = 'darwin'
globals_['require_reviewed_checkout'] = lambda *args: None
globals_['shutil'].which = lambda name: '/usr/bin/gh'
globals_['Path'].home = staticmethod(lambda: pathlib.Path(sys.argv[2]))
raise SystemExit(entry['main'](['--checkout', '/reviewed/tooling', '--python', '/reviewed/python']))
'''
    result = subprocess.run([sys.executable, '-c', code, str(script), str(tmp_path)], cwd=tmp_path,
                            env={key: value for key, value in os.environ.items() if key != 'PYTHONPATH'},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _committed_test(tmp_path, candidate):
    tmp_path.chmod(0o700)
    options = {'build': lambda: 123, 'load': lambda _run: candidate,
               'deploy': lambda channel, received: _native_receipt(channel, received),
               'current_main': lambda: candidate.sha}
    assert driver.poll(tmp_path, **options) == 0
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert (stored['phase'], stored['channel']) == ('passed', 'test') and 'heavy' not in stored
    return options


def test_controller_dispatches_one_heavy_verdict_per_candidate(tmp_path):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    options = _committed_test(tmp_path, candidate)
    runs, sent = [], []

    def run(received):
        runs.append(received)
        return dict(HEAVY_PASSED, result='failed', failed=2, failures=['tests/deploy/test_a.py::test_x'])

    heavy = {'heavy': run, 'dispatch': lambda received, verdict: sent.append((received, dict(verdict)))}
    assert driver.poll(tmp_path, **options, **heavy) == 0
    assert runs == [candidate]
    assert [(c, v['result'], v['failures']) for c, v in sent] == [
        (candidate, 'failed', ['tests/deploy/test_a.py::test_x'])]
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert stored['heavy']['dispatch'] == 'sent'
    # Restart: the recorded dispatch is never repeated and no rerun starts.
    assert driver.poll(tmp_path, **options, **heavy) == 0
    assert len(runs) == 1 and len(sent) == 1


def test_controller_heavy_resume_and_dispatch_failure_never_stall(tmp_path):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    options = _committed_test(tmp_path, candidate)
    checkpoint = tmp_path / 'postmerge-dev-test.json'
    stored = json.loads(checkpoint.read_text())
    # A crash after the VM run but before dispatch resumes with the recorded
    # verdict instead of re-running the suite.
    stored['heavy'] = dict(HEAVY_PASSED)
    driver._atomic_checkpoint(checkpoint, stored)
    sent = []
    assert driver.poll(tmp_path, **options, heavy=lambda _c: pytest.fail('heavy rerun'),
                       dispatch=lambda c, v: sent.append(v['result'])) == 0
    assert sent == ['passed']
    # A failed dispatch is recorded once and the next candidate still deploys;
    # the workflow watchdog surfaces the missing verdict.
    stored = json.loads(checkpoint.read_text())
    del stored['heavy']
    driver._atomic_checkpoint(checkpoint, stored)

    def broken(_candidate, _verdict):
        raise driver.CandidateRefused('heavy_dispatch_failed')

    assert driver.poll(tmp_path, **options, dispatch=broken) == 78
    assert json.loads(checkpoint.read_text())['heavy']['dispatch'] == 'failed'
    next_candidate = driver.Candidate('c' * 40, 'sha256:' + 'd' * 64, 124, 1, 457)
    deployed = []
    assert driver.poll(tmp_path, build=lambda: 124, load=lambda _run: next_candidate,
                       deploy=lambda ch, c: deployed.append(ch) or _native_receipt(ch, c),
                       current_main=lambda: next_candidate.sha, dispatch=broken) == 0
    assert deployed == ['dev', 'test']


def test_controller_refuses_tampered_heavy_checkpoint(tmp_path):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    options = _committed_test(tmp_path, candidate)
    checkpoint = tmp_path / 'postmerge-dev-test.json'
    stored = json.loads(checkpoint.read_text())
    stored['heavy'] = dict(HEAVY_PASSED, failures=['bad\nline'])
    driver._atomic_checkpoint(checkpoint, stored)
    with pytest.raises(driver.CandidateRefused, match='checkpoint_refused'):
        driver.poll(tmp_path, **options)


def test_heavy_verdict_dispatch_payload_is_bounded(monkeypatch):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    monkeypatch.undo()
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')

    monkeypatch.setattr(driver.subprocess, 'run', run)
    driver.dispatch_verdict(candidate, dict(HEAVY_PASSED, result='failed', failed=1,
                                            failures=['tests/deploy/test_b.py::test_c[<lambda>@x]']
                                            + ['tests/deploy/test_a.py::test_' + 'x' * 190] * 19))
    argv, kwargs = calls[0]
    assert argv[:8] == ['gh', 'workflow', 'run', driver.HEAVY_WORKFLOW, '--repo', driver.REPOSITORY,
                        '--ref', 'main']
    fields = dict(argv[i + 1].split('=', 1) for i in range(8, len(argv), 2))
    assert set(fields) == {'sha', 'verdict', 'operation_id', 'counts', 'reason', 'failures'}
    assert fields['sha'] == SHA and fields['verdict'] == 'failed'
    assert fields['operation_id'] == candidate.operation_id('test')
    assert fields['counts'] == 'selected=500 passed=490 failed=1 skipped=10 docker_skipped=0'
    assert len(fields['failures']) <= 1000
    assert fields['failures'].startswith('tests/deploy/test_b.py::test_c[?lambda??x]')
    # Only the bounded verdict crosses; no deployment environment is forwarded.
    assert 'env' not in kwargs

    def ssh(argv, **kwargs):
        calls.append((argv, kwargs))
        receipt = {'profile_version': 'postmerge-heavy.v1', 'result': 'passed', 'source_sha': SHA,
                   'image_digest': DIGEST, 'channel': 'test', 'operation_id': candidate.operation_id('test'),
                   'targets': ['tests/deploy'], 'report_hash': '0' * 64, **{k: v for k, v in HEAVY_PASSED.items()
                                                                          if k != 'result'}}
        return SimpleNamespace(returncode=0, stdout='noise\n' + json.dumps(receipt) + '\n', stderr='')

    monkeypatch.setattr(driver.subprocess, 'run', ssh)
    monkeypatch.setenv('GH_TOKEN', 'not-forwarded')
    assert driver.native_heavy(candidate) == HEAVY_PASSED
    argv, kwargs = calls[-1]
    assert argv[-4] == '/usr/local/libexec/yggdrasil-bws-deploy' and 'ygg-test' in argv
    assert argv[-3:] == ['qualify-heavy', 'test', candidate.operation_id('test')]
    assert 'GH_TOKEN' not in kwargs['env']
    # A foreign or malformed receipt is a refused verdict, never a pass.
    monkeypatch.setattr(driver.subprocess, 'run', lambda argv, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps({'profile_version': 'postmerge-heavy.v1', 'result': 'passed',
                                         'source_sha': 'c' * 40}), stderr=''))
    assert driver.native_heavy(candidate)['result'] == 'refused'
