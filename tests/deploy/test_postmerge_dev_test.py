from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest
import yaml

from app.ops.postgres_deploy import DeployJournal, DeployPlan, PostgresDeployError
from scripts import postmerge_dev_test as driver

SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
ROOT = Path(__file__).resolve().parents[2]


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
                'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}
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


def test_dev_failure_blocks_test_and_success_preserves_same_candidate():
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    calls, outcomes = [], []

    def deploy(channel, received):
        calls.append((channel, received))
        return {'channel': channel, 'terminal_result': 'committed', 'operation_id': str(uuid4())}

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
    monkeypatch.setattr(linux, '_git_bytes', lambda *_args: b'')
    monkeypatch.setattr(reversibility, 'check_migration_snapshots',
                        lambda _snapshots: {'forward_only': ['irreversible.py']})
    monkeypatch.setattr(linux, 'vm_selected_values', lambda *_args: pytest.fail('credential materialization'))
    with pytest.raises(PostgresDeployError):
        effects.preflight(plan)
    assert effects.password is None


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
            'operation_id': str(uuid4()), 'channel': 'dev', 'kind': 'deploy',
            'stage': 'committed', 'terminal_result': 'committed'}))

    monkeypatch.setattr(driver.subprocess, 'run', run)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    driver.native_deploy('dev', candidate)
    argv, options = calls[0]
    assert argv[-4:] == ['--existing-secrets-only', '--automatic', '--image-digest', DIGEST]
    assert 'GH_TOKEN' not in options['env'] and 'GITHUB_TOKEN' not in options['env']


def test_controller_checkpoint_deduplicates_and_resumes_same_candidate(tmp_path):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    calls = []

    def deploy(channel, received):
        calls.append((channel, received))
        return {'channel': channel, 'terminal_result': 'committed', 'operation_id': str(uuid4())}

    options = {'build': lambda: 123, 'load': lambda _run: candidate,
               'deploy': deploy, 'current_main': lambda: SHA}
    assert driver.poll(tmp_path, **options) == 0
    assert driver.poll(tmp_path, **options) == 0
    assert calls == [('dev', candidate), ('test', candidate)]
    checkpoint = tmp_path / 'postmerge-dev-test.json'
    stored = json.loads(checkpoint.read_text())
    stored['channel'] = stored['outcome']['channel'] = 'dev'
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
        return {'channel': channel, 'terminal_result': 'committed', 'operation_id': str(uuid4())}

    def deploy(channel, received):
        assert channel == 'test' and received == candidate
        return {'channel': channel, 'terminal_result': 'committed', 'operation_id': str(uuid4())}

    assert driver.poll(tmp_path, reconcile=reconcile, deploy=deploy) == 0
    assert calls == [('dev', candidate)]
    # An unreadable pending operation cannot start a fresh deployment.
    driver._save_outcome(path, candidate, outcomes[0])
    with pytest.raises(driver.CandidateRefused):
        driver.poll(tmp_path, reconcile=lambda *_args: (_ for _ in ()).throw(driver.CandidateRefused('pending')),
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
