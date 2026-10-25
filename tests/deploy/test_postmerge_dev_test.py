from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
import plistlib
import shutil
import shlex
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
from scripts import postmerge_channel_bug as channel_bug

REAL_CHANNEL_DISPATCH = driver.dispatch_channel_verdict

SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
ROOT = Path(__file__).resolve().parents[2]

HEAVY_PASSED = {'result': 'passed', 'failures': [], 'selected': 500, 'passed': 490, 'failed': 0,
                'skipped': 10, 'docker_skipped': 0}


@pytest.fixture(autouse=True)
def _no_live_heavy_transport(monkeypatch):
    # A committed DEV candidate triggers the heavy step on the next tick; keep
    # tests off the real SSH launcher and GitHub dispatch.
    sent = []
    monkeypatch.setattr(driver, 'native_heavy', lambda candidate: dict(HEAVY_PASSED))
    monkeypatch.setattr(driver, 'dispatch_verdict', lambda candidate, heavy: sent.append((candidate, heavy)))
    monkeypatch.setattr(driver, 'dispatch_channel_verdict', lambda evidence: None)
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
    assert calls == [('dev', candidate)]
    assert [o['result'] for o in outcomes] == ['started', 'passed']
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
    assert 'heavy' not in stored
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


def _absence_proof(channel, candidate):
    return {
        'contract': 'postmerge-native-operation-absence.v1',
        'operation_id': candidate.operation_id(channel),
        'channel': channel,
        'candidate_sha': candidate.sha,
        'image_digest': candidate.digest,
        'host_operation_absent': True,
        'host_operation_retired': True,
        'native_operation_absent': True,
        'native_worker_absent': True,
        'native_lock_absent': True,
        'native_request_absent': True,
    }


def test_pre_mutation_refusal_with_exact_absence_retires_pending_checkpoint(tmp_path):
    tmp_path.chmod(0o700)
    stale = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    current = driver.Candidate('c' * 40, 'sha256:' + 'd' * 64, 124, 1, 457)
    path = tmp_path / 'postmerge-dev-test.json'
    driver._save_outcome(path, stale, {
        'source_sha': stale.sha, 'image_digest': stale.digest, 'source_run_id': stale.run_id,
        'source_run_attempt': stale.run_attempt, 'artifact_id': stale.artifact_id,
        'channel': 'dev', 'result': 'pending', 'operation_id': stale.operation_id('dev'),
    })
    calls = []

    def deploy(channel, candidate):
        calls.append((channel, candidate))
        return _native_receipt(channel, candidate)

    assert driver.poll(
        tmp_path,
        build=lambda: current.run_id,
        load=lambda _run: current,
        resume=lambda *_args: (_ for _ in ()).throw(
            driver.CandidateRefused('native_terminal_evidence_refused')
        ),
        absence=lambda channel, candidate: _absence_proof(channel, candidate),
        deploy=deploy,
        current_main=lambda: current.sha,
    ) == 0
    assert calls == [('dev', current)]
    checkpoint = json.loads(path.read_text())
    assert checkpoint['candidate'] == driver.asdict(current)
    assert checkpoint['phase'] == 'passed' and checkpoint['channel'] == 'dev'


def test_pre_mutation_refusal_preserves_current_main_candidate_for_retry(tmp_path):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    path = tmp_path / 'postmerge-dev-test.json'
    driver._save_outcome(path, candidate, {
        'source_sha': candidate.sha, 'image_digest': candidate.digest, 'source_run_id': candidate.run_id,
        'source_run_attempt': candidate.run_attempt, 'artifact_id': candidate.artifact_id,
        'channel': 'dev', 'result': 'pending', 'operation_id': candidate.operation_id('dev'),
    })

    with pytest.raises(driver.CandidateRefused, match='candidate_not_superseded'):
        driver.poll(
            tmp_path,
            resume=lambda *_args: (_ for _ in ()).throw(
                driver.CandidateRefused('native_terminal_evidence_refused')
            ),
            absence=lambda *_args: pytest.fail('current candidate was permanently fenced'),
            deploy=lambda *_args: pytest.fail('current pending candidate was bypassed'),
            current_main=lambda: candidate.sha,
        )
    assert json.loads(path.read_text())['phase'] == 'pending'


@pytest.mark.parametrize('field,value', [
    ('operation_id', str(uuid4())),
    ('candidate_sha', 'c' * 40),
    ('native_request_absent', False),
    ('native_lock_absent', False),
])
def test_absence_proof_requires_exact_checkpoint_binding_and_complete_evidence(tmp_path, field, value):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    path = tmp_path / 'postmerge-dev-test.json'
    driver._save_outcome(path, candidate, {
        'source_sha': candidate.sha, 'image_digest': candidate.digest, 'source_run_id': candidate.run_id,
        'source_run_attempt': candidate.run_attempt, 'artifact_id': candidate.artifact_id,
        'channel': 'dev', 'result': 'pending', 'operation_id': candidate.operation_id('dev'),
    })
    proof = _absence_proof('dev', candidate)
    proof[field] = value
    with pytest.raises(driver.CandidateRefused, match='native_absence_evidence_refused'):
        driver.poll(
            tmp_path,
            resume=lambda *_args: (_ for _ in ()).throw(
                driver.CandidateRefused('native_terminal_evidence_refused')
            ),
            absence=lambda *_args: proof,
            deploy=lambda *_args: pytest.fail('ambiguous absence advanced deployment'),
            current_main=lambda: 'b' * 40,
        )
    assert json.loads(path.read_text())['phase'] == 'pending'


@pytest.mark.parametrize('reason', ['pending', 'transport_failed', 'native_absence_evidence_refused'])
def test_absence_proof_preserves_admitted_and_unknown_operations(tmp_path, reason):
    tmp_path.chmod(0o700)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    path = tmp_path / 'postmerge-dev-test.json'
    driver._save_outcome(path, candidate, {
        'source_sha': candidate.sha, 'image_digest': candidate.digest, 'source_run_id': candidate.run_id,
        'source_run_attempt': candidate.run_attempt, 'artifact_id': candidate.artifact_id,
        'channel': 'dev', 'result': 'pending', 'operation_id': candidate.operation_id('dev'),
    })
    with pytest.raises(driver.CandidateRefused):
        driver.poll(
            tmp_path,
            resume=lambda *_args: (_ for _ in ()).throw(driver.CandidateRefused(reason)),
            absence=lambda *_args: pytest.fail('non-terminal refusal attempted absence'),
        )
    assert json.loads(path.read_text())['phase'] == 'pending'


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
                          Path('/opt/homebrew/bin/gh'), Path('/private/state'), SHA)
    assert config['ProgramArguments'] == ['/tooling/.venv/bin/python', '-I', '-S',
                                         '/tooling/scripts/postmerge_controller.py', '--tooling-sha', SHA, '--latest', '--state-directory', '/private/state']
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
    assert calls == [('dev', candidate), ('dev', next_candidate)]


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
globals_['require_reviewed_checkout'] = lambda *args: 'a' * 40
globals_['install_tooling'] = lambda *args: (pathlib.Path('/reviewed/tooling'), pathlib.Path('/reviewed/python'))
globals_['shutil'].which = lambda name: '/usr/bin/gh'
globals_['Path'].home = staticmethod(lambda: pathlib.Path(sys.argv[2]))
raise SystemExit(entry['main'](['--checkout', '/reviewed/tooling', '--python', '/reviewed/python']))
'''
    result = subprocess.run([sys.executable, '-c', code, str(script), str(tmp_path)], cwd=tmp_path,
                            env={key: value for key, value in os.environ.items() if key != 'PYTHONPATH'},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _committed_dev(tmp_path, candidate):
    tmp_path.chmod(0o700)
    options = {'build': lambda: 123, 'load': lambda _run: candidate,
               'deploy': lambda channel, received: _native_receipt(channel, received),
               'current_main': lambda: candidate.sha}
    assert driver.poll(tmp_path, **options) == 0
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert (stored['phase'], stored['channel']) == ('passed', 'dev') and 'heavy' not in stored
    return options



@pytest.mark.parametrize('verdict', ['passed', 'failed', 'refused'])
def test_test_promotion_requires_passing_dev_heavy_verdict(tmp_path, verdict):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    calls, signals, alerts = [], [], []
    tmp_path.chmod(0o700)

    def deploy(channel, received):
        assert received == candidate
        calls.append(channel)
        return _native_receipt(channel, received)

    def heavy(received):
        assert received == candidate
        assert calls == ['dev']
        calls.append('heavy')
        return ({'result': 'refused', 'reason': 'heavy_command_failed'} if verdict == 'refused'
                else dict(HEAVY_PASSED, result=verdict))

    options = {'build': lambda: candidate.run_id, 'load': lambda _: candidate,
               'current_main': lambda: SHA, 'deploy': deploy, 'heavy': heavy,
               'signal': lambda c, o: signals.append((c, o)), 'alert': alerts.append}
    assert driver.poll(tmp_path, **options) == 0
    assert calls == ['dev'] and not signals and not alerts
    assert driver.poll(tmp_path, **options) == (0 if verdict == 'passed' else 78)
    assert calls == (['dev', 'heavy', 'test'] if verdict == 'passed' else ['dev', 'heavy'])
    assert [(c, o['result']) for c, o in signals] == [(candidate, 'passed' if verdict == 'passed' else 'failed')]
    assert alerts[0]['gate'] == 'heavy_acceptance'
    driver.validate_channel_evidence(alerts[0], 'dev')
    history = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['last_green']
    assert history == ({'dev': SHA, 'test': SHA} if verdict == 'passed' else {})


@pytest.mark.parametrize('verdict', ['failed', 'refused'])
def test_red_dev_heavy_verdict_holds_candidate_and_later_builds_proceed(tmp_path, verdict):
    first = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    second = replace(first, sha='c' * 40, run_id=124)
    options = _committed_dev(tmp_path, first)
    runs, sent, deployed = [], [], []

    def heavy(candidate):
        runs.append(candidate)
        return ({'result': 'refused', 'reason': 'heavy_command_failed'} if verdict == 'refused'
                else dict(HEAVY_PASSED, result='failed', failed=1))

    options.update(heavy=heavy, dispatch=lambda c, v: sent.append((c, dict(v))))
    assert driver.poll(tmp_path, **options) == 78
    assert driver.poll(tmp_path, **options) == 0
    assert runs == [first] and len(sent) == 1
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['heavy']['held'] is True
    assert driver.poll(tmp_path, build=lambda: second.run_id, load=lambda _: second,
                       current_main=lambda: second.sha,
                       deploy=lambda ch, c: deployed.append((ch, c)) or _native_receipt(ch, c),
                       heavy=heavy, dispatch=lambda *_: pytest.fail('old verdict redispatched')) == 0
    assert deployed == [('dev', second)] and runs == [first] and len(sent) == 1


def test_terminal_dev_failure_dispatches_refused_once_including_resume(tmp_path):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    tmp_path.chmod(0o700)
    sent = []
    options = {'build': lambda: 123, 'load': lambda _: candidate, 'current_main': lambda: SHA,
               'deploy': lambda ch, c: _native_receipt(ch, c, 'failed'),
               'heavy': lambda _: pytest.fail('heavy after failed deploy'),
               'dispatch': lambda c, v: sent.append((c, dict(v)))}
    assert driver.poll(tmp_path, **options) == 78
    assert sent == [(candidate, {'result': 'refused', 'reason': 'dev_deploy_failed', 'dispatch': 'started'})]
    assert driver.poll(tmp_path, **options) == 0 and len(sent) == 1
    path = tmp_path / 'postmerge-dev-test.json'
    stored = json.loads(path.read_text())
    stored.pop('heavy')
    stored.pop('channel_bug')
    stored['phase'] = stored['outcome']['result'] = 'pending'
    driver._atomic_checkpoint(path, stored)
    assert driver.poll(tmp_path, **options, resume=lambda ch, c: _native_receipt(ch, c, 'failed')) == 78
    assert len(sent) == 2
    assert driver.poll(tmp_path, **options) == 0 and len(sent) == 2


class _ControllerCrash(BaseException):
    pass


def test_heavy_crash_before_result_holds_without_rerun(tmp_path):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    options = _committed_dev(tmp_path, candidate)
    path = tmp_path / 'postmerge-dev-test.json'

    def crash(_candidate):
        raise _ControllerCrash()

    with pytest.raises(_ControllerCrash):
        driver.poll(tmp_path, **options, heavy=crash)
    assert json.loads(path.read_text())['heavy'] == {'result': 'refused', 'reason': 'heavy_run_interrupted'}
    sent = []
    assert driver.poll(tmp_path, **options, heavy=lambda _: pytest.fail('uncertain run replayed'),
                       dispatch=lambda c, v: sent.append(dict(v))) == 78
    assert len(sent) == 1 and sent[0]['reason'] == 'heavy_run_interrupted'


@pytest.mark.parametrize('verdict', ['passed', 'failed'])
def test_heavy_crash_during_dispatch_does_not_redispatch_or_replay(tmp_path, verdict):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    options = _committed_dev(tmp_path, candidate)
    sent = []

    def crash(c, v):
        sent.append(dict(v))
        raise _ControllerCrash()

    with pytest.raises(_ControllerCrash):
        driver.poll(tmp_path, **options, heavy=lambda _: dict(HEAVY_PASSED, result=verdict), dispatch=crash)
    assert sent[0]['dispatch'] == 'started'
    assert driver.poll(tmp_path, **options, heavy=lambda _: pytest.fail('heavy rerun'),
                       dispatch=lambda *_: pytest.fail('uncertain verdict redispatched')) == (0 if verdict == 'passed' else 78)
    assert len(sent) == 1


def test_legacy_test_heavy_checkpoint_is_inert_and_later_dev_proceeds(tmp_path):
    old = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    later = replace(old, sha='c' * 40, run_id=124)
    tmp_path.chmod(0o700)
    path = tmp_path / 'postmerge-dev-test.json'
    outcome = _channel_evidence(old, channel='test', verdict='passed')['receipt']
    stored = driver._save_outcome(path, old, outcome)
    stored['heavy'] = dict(HEAVY_PASSED, dispatch='sent')
    driver._atomic_checkpoint(path, stored)
    deployed = []
    assert driver.poll(tmp_path, build=lambda: 124, load=lambda _: later,
                       current_main=lambda: later.sha,
                       deploy=lambda ch, c: deployed.append((ch, c)) or _native_receipt(ch, c),
                       heavy=lambda _: pytest.fail('legacy heavy replay'),
                       dispatch=lambda *_: pytest.fail('legacy verdict redispatch')) == 0
    assert deployed == [('dev', later)]


def test_controller_dispatches_one_heavy_verdict_per_candidate(tmp_path):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    options = _committed_dev(tmp_path, candidate)
    runs, sent = [], []

    def run(received):
        runs.append(received)
        return dict(HEAVY_PASSED, result='failed', failed=2, failures=['tests/deploy/test_a.py::test_x'])

    heavy = {'heavy': run, 'dispatch': lambda received, verdict: sent.append((received, dict(verdict)))}
    assert driver.poll(tmp_path, **options, **heavy) == 78
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
    options = _committed_dev(tmp_path, candidate)
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
    del stored['heavy']
    driver._atomic_checkpoint(checkpoint, stored)

    def broken(_candidate, _verdict):
        raise driver.CandidateRefused('heavy_dispatch_failed')

    assert driver.poll(tmp_path, **options, heavy=lambda _: dict(HEAVY_PASSED, result='failed'), dispatch=broken) == 78
    assert json.loads(checkpoint.read_text())['heavy']['dispatch'] == 'failed'
    next_candidate = driver.Candidate('c' * 40, 'sha256:' + 'd' * 64, 124, 1, 457)
    deployed = []
    assert driver.poll(tmp_path, build=lambda: 124, load=lambda _run: next_candidate,
                       deploy=lambda ch, c: deployed.append(ch) or _native_receipt(ch, c),
                       current_main=lambda: next_candidate.sha, dispatch=broken) == 0
    assert deployed == ['dev']


def test_controller_refuses_tampered_heavy_checkpoint(tmp_path):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    options = _committed_dev(tmp_path, candidate)
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
    assert fields['operation_id'] == candidate.operation_id('dev')
    assert fields['counts'] == 'selected=500 passed=490 failed=1 skipped=10 docker_skipped=0'
    assert len(fields['failures']) <= 1000
    assert fields['failures'].startswith('tests/deploy/test_b.py::test_c[?lambda??x]')
    # Only the bounded verdict crosses; no deployment environment is forwarded.
    assert 'env' not in kwargs

    def ssh(argv, **kwargs):
        calls.append((argv, kwargs))
        receipt = {'profile_version': 'postmerge-heavy.v1', 'result': 'passed', 'source_sha': SHA,
                   'image_digest': DIGEST, 'channel': 'dev', 'operation_id': candidate.operation_id('dev'),
                   'targets': ['tests/deploy'], 'report_hash': '0' * 64, **{k: v for k, v in HEAVY_PASSED.items()
                                                                          if k != 'result'}}
        return SimpleNamespace(returncode=0, stdout='noise\n' + json.dumps(receipt) + '\n', stderr='')

    monkeypatch.setattr(driver.subprocess, 'run', ssh)
    monkeypatch.setenv('GH_TOKEN', 'not-forwarded')
    assert driver.native_heavy(candidate) == HEAVY_PASSED
    argv, kwargs = calls[-1]
    assert argv[-4] == '/usr/local/libexec/yggdrasil-bws-deploy' and 'ygg-dev' in argv
    assert argv[-3:] == ['qualify-heavy', 'dev', candidate.operation_id('dev')]
    assert 'GH_TOKEN' not in kwargs['env']
    # A foreign or malformed receipt is a refused verdict, never a pass.
    monkeypatch.setattr(driver.subprocess, 'run', lambda argv, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps({'profile_version': 'postmerge-heavy.v1', 'result': 'passed',
                                         'source_sha': 'c' * 40}), stderr=''))
    assert driver.native_heavy(candidate)['result'] == 'refused'


def test_heavy_verdict_dispatch_refuses_after_three_failed_attempts(monkeypatch):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    monkeypatch.undo()
    calls = []
    sleeps = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=1, stdout=b'', stderr=b'')

    monkeypatch.setattr(driver.subprocess, 'run', run)
    monkeypatch.setattr(driver.time, 'sleep', lambda duration: sleeps.append(duration))
    heavy = dict(HEAVY_PASSED, result='failed', failed=1,
                 failures=['tests/deploy/test_sample.py::test_rejected_verdict'])

    with pytest.raises(driver.CandidateRefused, match='heavy_dispatch_failed'):
        driver.dispatch_verdict(candidate, heavy)

    assert len(calls) == 3
    assert sleeps == [20, 20]
    assert all(argv == calls[0][0] for argv, _kwargs in calls)
    assert all(kwargs == {'capture_output': True, 'timeout': 60, 'check': False} for _argv, kwargs in calls)
    assert calls[0][0][:8] == ['gh', 'workflow', 'run', driver.HEAVY_WORKFLOW, '--repo', driver.REPOSITORY,
                                '--ref', 'main']


class _ChannelGithub:
    """In-memory transport only; tests execute the real workflow reconciler."""
    bot = {'login': 'github-actions[bot]', 'type': 'Bot'}

    def __init__(self):
        self.issues = []
        self.comments = {}
        self.effects = []
        self.runs = []
        self.candidates = []
        self.deliveries = []
        self.reads = []
        self.refusals = []
        self.latest_runs = {}
        self.attempts = {}
        self.workflow_attempts = {}

    def add(self, candidate):
        self.candidates.append(candidate)
        return candidate

    def api(self, method, path, data=None):
        prefix = f'repos/{driver.REPOSITORY}'
        if method != 'GET':
            self.effects.append((method, path, data))
        else:
            self.reads.append(path)
        if path.startswith(prefix + '/compare/'):
            base, head = path.split('/compare/')[1].split('...')
            shas = [c.sha for c in self.candidates]
            a, b = shas.index(base), len(shas) - 1 if head == 'main' else shas.index(head)
            return {'status': 'identical' if a == b else 'ahead' if b > a else 'behind'}
        if path.startswith(prefix + '/actions/workflows/'):
            rows = [r for r in self.runs if r['conclusion'] == 'success'] if 'status=success' in path else self.runs
            return {'workflow_runs': rows}
        if path.startswith(prefix + '/actions/runs/'):
            parts = path.split('/actions/runs/')[1].split('/')
            if len(parts) == 3 and int(parts[0]) >= 1000:
                prior = self.workflow_attempts[(int(parts[0]), int(parts[2]))]
                if isinstance(prior, Exception):
                    raise prior
                return prior
            candidate = next(c for c in self.candidates if c.run_id == int(parts[0]))
            run, _ = _build()
            run = {**run, 'id': candidate.run_id, 'run_attempt': candidate.run_attempt, 'head_sha': candidate.sha,
                   'created_at': '2026-10-19T00:00:00Z'}
            if len(parts) == 1:
                return {**run, **self.latest_runs.get(candidate.run_id, {})}
            assert parts[1] == 'attempts'
            key = (candidate.run_id, int(parts[2]))
            assert len(parts) == 3
            return {**run, **self.attempts.get(key, {})}
        if path.startswith(prefix + '/issues?'):
            return self.issues
        if path == prefix + '/issues' and method == 'POST':
            issue = {**data, 'number': len(self.issues) + 1, 'state': 'open', 'user': self.bot,
                     'labels': [{'name': name} for name in data['labels']]}
            self.issues.append(issue)
            self.comments[issue['number']] = []
            return issue
        number = int(path.split('/issues/')[1].split('/')[0])
        if '/comments' in path:
            if method == 'POST':
                self.comments[number].append({'user': self.bot, **data})
                return self.comments[number][-1]
            return self.comments[number]
        if method == 'PATCH':
            self.issues[number - 1].update(data)
            if 'labels' in data:
                self.issues[number - 1]['labels'] = [{'name': name} for name in data['labels']]
            return self.issues[number - 1]
        pytest.fail(f'unexpected API: {method} {path}')

    def reconcile(self, evidence):
        return channel_bug.reconcile(evidence, channel=evidence['channel'], event='workflow_dispatch',
                                     ref='refs/heads/main', repository=driver.REPOSITORY, run_id=900,
                                     api=self.api)

    def transport(self, argv, **kwargs):
        assert argv[:3] == ['gh', 'workflow', 'run']
        assert argv[3:8] == ['postmerge-channel-bug.yml', '--repo', driver.REPOSITORY, '--ref', 'main']
        assert kwargs == {'capture_output': True, 'timeout': 60, 'check': False}
        fields = dict(argv[index + 1].split('=', 1) for index, arg in enumerate(argv) if arg == '-f')
        evidence = json.loads(fields['evidence'])
        assert fields['channel'] == evidence['channel']
        self.deliveries.append(evidence)
        try:
            self.reconcile(evidence)
        except channel_bug.AlertRefused as error:
            self.refusals.append(str(error))
            raise
        candidate = evidence['candidate']
        self.runs.append({'id': 1000 + len(self.runs), 'run_attempt': 1, 'status': 'completed',
                          'conclusion': 'success', 'head_sha': candidate['sha'], 'head_branch': 'main',
                          'event': 'workflow_dispatch', 'path': '.github/workflows/postmerge-channel-bug.yml',
                          'display_title': f"channel-bug/{evidence['channel']}/{evidence['verdict']}/"
                                           f"{candidate['sha']}/{candidate['run_id']}/{candidate['run_attempt']}/"
                                           f"{evidence['receipt_fingerprint']}"})
        return SimpleNamespace(returncode=0)


@pytest.fixture
def channel_github(monkeypatch):
    github = _ChannelGithub()
    monkeypatch.setattr(driver, 'dispatch_channel_verdict', REAL_CHANNEL_DISPATCH)
    monkeypatch.setattr(driver.subprocess, 'run', github.transport)
    return github


def _poll_channel(tmp_path, candidate, *, red=None, source_failure=None, complete=True, **kwargs):
    tmp_path.chmod(0o700)

    def deploy(channel, received):
        receipt = _native_receipt(channel, received, 'failed' if channel == red else 'committed')
        if channel == red and source_failure:
            receipt['source_failure'] = source_failure
        return receipt

    options = {'build': lambda: candidate.run_id, 'load': lambda _: candidate,
               'current_main': lambda: candidate.sha, 'deploy': deploy, **kwargs}
    status = driver.poll(tmp_path, **options)
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    # Consumer tests normally drive both real controller ticks. State-machine
    # tests opt out so they can assert the provisional native DEV state itself.
    if (complete and status == 0 and stored.get('candidate') == asdict(candidate)
        and (stored.get('phase'), stored.get('channel')) == ('passed', 'dev') and 'heavy' not in stored):
        status = driver.poll(tmp_path, **options)
    return status


def test_red_dev_candidate_files_bug_and_next_candidate_proceeds(tmp_path, channel_github):
    github = channel_github
    good = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    first = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    second = github.add(driver.Candidate('c' * 40, DIGEST, 124, 1, 457))
    assert _poll_channel(tmp_path, good) == 0
    assert _poll_channel(tmp_path, good) == 0  # Complete the existing heavy step.
    assert _poll_channel(tmp_path, first, red='dev', source_failure='embedding_probe_client_failed') == 78
    issue = github.issues[0]
    body = issue['body']
    assert len(github.issues) == 1 and issue['state'] == 'open'
    assert f'{good.sha}...{first.sha}' in body
    assert first.sha in body and first.operation_id('dev') in body
    assert 'source_projection' in body and 'embedding_probe_client_failed' in body
    assert '/actions/runs/900' in body
    assert _poll_channel(tmp_path, first, red='dev') == 0  # No candidate replay or duplicate alert.
    assert _poll_channel(tmp_path, second, red='dev') == 78
    assert len(github.issues) == 1 and len(github.comments[1]) == 1
    assert f'{good.sha}...{second.sha}' in github.comments[1][0]['body']
    assert [e['candidate']['sha'] for e in github.deliveries if e['verdict'] == 'failed'] == [first.sha, second.sha]
    # Re-running a successful Actions job does not duplicate the terminal comment.
    github.reconcile(github.deliveries[-1])
    assert len(github.comments[1]) == 1


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_green_candidate_closes_channel_bug(tmp_path, channel_github, channel):
    github = channel_github
    red = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    green = github.add(driver.Candidate('c' * 40, DIGEST, 124, 1, 457))
    assert _poll_channel(tmp_path, red, red=channel) == 78
    issue = github.issues[0]
    issue['labels'] += [{'name': 'agent:in-progress'}, {'name': 'action:retry'}, {'name': 'area:deploy'}]
    assert _poll_channel(tmp_path, green) == 0
    assert issue['state'] == 'closed' and issue['state_reason'] == 'completed'
    assert len(github.comments[1]) == 1
    assert green.sha in github.comments[1][0]['body'] and '**passed**' in github.comments[1][0]['body']
    assert [row['name'] for row in issue['labels']] == ['type:bug', 'prio:high', 'area:deploy']
    history = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['last_green']
    assert history == {'dev': green.sha, 'test': green.sha}




def test_heavy_verdict_reaches_trusted_channel_consumer_without_premature_green(tmp_path, channel_github):
    github = channel_github
    good = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    red = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    later = github.add(driver.Candidate('c' * 40, DIGEST, 124, 1, 457))
    assert _poll_channel(tmp_path, good, complete=False) == 0
    assert not github.deliveries
    assert _poll_channel(tmp_path, good) == 0
    assert _poll_channel(tmp_path, red, complete=False) == 0
    assert not [e for e in github.deliveries if e['candidate']['sha'] == red.sha]
    assert _poll_channel(tmp_path, red, heavy=lambda _: dict(HEAVY_PASSED, result='failed', failed=1)) == 78
    issue = github.issues[0]
    assert issue['state'] == 'open' and 'heavy_acceptance' in issue['body']
    assert f'{good.sha}...{red.sha}' in issue['body']
    red_events = [e for e in github.deliveries if e['candidate']['sha'] == red.sha]
    assert len(red_events) == 1 and red_events[0]['verdict'] == 'failed'
    assert driver.validate_channel_evidence(red_events[0], 'dev') == red
    history = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['last_green']
    assert history == {'dev': good.sha, 'test': good.sha}
    assert _poll_channel(tmp_path, red) == 0 and len(github.deliveries) == 3
    assert _poll_channel(tmp_path, later, complete=False) == 0
    assert issue['state'] == 'open'
    assert _poll_channel(tmp_path, later) == 0
    assert issue['state'] == 'closed' and not github.refusals
    # Trusted Actions consumes the successful admitted build, exact receipt,
    # candidate ancestry, and immutable terminal fingerprint before Issue writes.
    assert any(f'/actions/runs/{red.run_id}/attempts/{red.run_attempt}' in p for p in github.reads)


@pytest.mark.parametrize('mutation', ['foreign_pg', 'wrong_verdict', 'wrong_channel', 'empty_pass', 'red_pass'])
def test_heavy_channel_consumer_refuses_mismatched_or_invalid_verdict_before_effect(mutation):
    github = _ChannelGithub()
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    evidence = _channel_evidence(candidate, verdict='passed')
    evidence['gate'] = 'heavy_acceptance'
    evidence['receipt']['heavy_acceptance'] = dict(HEAVY_PASSED)
    if mutation == 'foreign_pg':
        evidence['receipt']['pg_acceptance']['source_sha'] = 'c' * 40
    elif mutation == 'wrong_verdict':
        evidence['receipt']['heavy_acceptance']['result'] = 'failed'
    elif mutation == 'wrong_channel':
        evidence['channel'] = evidence['receipt']['channel'] = 'test'
        evidence['receipt']['operation_id'] = candidate.operation_id('test')
    elif mutation == 'empty_pass':
        evidence['receipt']['heavy_acceptance']['selected'] = 0
    else:
        evidence['receipt']['heavy_acceptance']['failed'] = 1
    evidence['receipt_fingerprint'] = driver.channel_verdict_fingerprint(evidence)
    with pytest.raises(channel_bug.AlertRefused, match='channel_evidence_refused'):
        github.reconcile(evidence)
    assert not github.effects


def test_channel_bug_dispatch_failure_and_restart_do_not_replay_or_stall(tmp_path, monkeypatch):
    first = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    second = replace(first, sha='c' * 40, run_id=124)
    reports = []

    def broken(evidence):
        reports.append(evidence)
        raise RuntimeError('secret-canary')

    monkeypatch.setattr(driver, 'dispatch_channel_verdict', broken)
    assert _poll_channel(tmp_path, first, red='dev') == 78
    path = tmp_path / 'postmerge-dev-test.json'
    assert json.loads(path.read_text())['channel_bug']['dispatch'] == 'failed'
    assert _poll_channel(tmp_path, first, red='dev') == 0
    assert len(reports) == 1
    assert _poll_channel(tmp_path, second) == 0
    assert len(reports) == 3
    assert 'secret-canary' not in path.read_text()


def _channel_evidence(candidate, channel='dev', verdict='failed', last_good=None):
    receipt = {'source_sha': candidate.sha, 'image_digest': candidate.digest,
               'source_run_id': candidate.run_id, 'source_run_attempt': candidate.run_attempt,
               'artifact_id': candidate.artifact_id, 'result': verdict, 'channel': channel,
               'operation_id': candidate.operation_id(channel)}
    if verdict == 'passed':
        receipt['pg_acceptance'] = _native_receipt(channel, candidate)['pg_acceptance']
    evidence = {'candidate': asdict(candidate), 'channel': channel, 'verdict': verdict,
                'gate': 'native_deploy', 'last_good_sha': last_good, 'receipt': receipt}
    evidence['receipt_fingerprint'] = driver.channel_verdict_fingerprint(evidence)
    return evidence


@pytest.mark.parametrize('late_verdict,new_verdict', [('passed', 'failed'), ('failed', 'passed')])
def test_channel_bug_rejects_delayed_verdicts(late_verdict, new_verdict):
    github = _ChannelGithub()
    initial = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    old = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    new = github.add(driver.Candidate('c' * 40, DIGEST, 124, 1, 457))
    github.reconcile(_channel_evidence(initial))
    github.reconcile(_channel_evidence(new, verdict=new_verdict))
    before = len(github.effects)
    assert github.reconcile(_channel_evidence(old, verdict=late_verdict)) == 'stale'
    assert len(github.effects) == before
    assert github.issues[0]['state'] == ('closed' if new_verdict == 'passed' else 'open')


def test_delayed_first_red_after_green_without_bug_is_ignored():
    github = _ChannelGithub()
    old = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    new = github.add(driver.Candidate('c' * 40, DIGEST, 124, 1, 457))
    github.runs = [{'id': 901, 'run_attempt': 1, 'status': 'completed', 'head_sha': new.sha,
                    'conclusion': 'success', 'head_branch': 'main',
                    'event': 'workflow_dispatch', 'path': '.github/workflows/postmerge-channel-bug.yml',
                    'display_title': f'channel-bug/dev/passed/{new.sha}/124/1/'
                                     + _channel_evidence(new, verdict='passed')['receipt_fingerprint']}]
    assert github.reconcile(_channel_evidence(old)) == 'stale'
    assert not github.effects


def test_channel_bug_only_mutates_owned_channel_and_recovers_partial_close():
    github = _ChannelGithub()
    red = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    green = github.add(driver.Candidate('c' * 40, DIGEST, 124, 1, 457))
    github.reconcile(_channel_evidence(red, channel='test'))
    foreign = {**github.issues[0], 'number': 2, 'user': {'login': 'human', 'type': 'User'},
               'body': channel_bug._issue_body(_channel_evidence(red), 'receipt')}
    github.issues.append(foreign)
    github.reconcile(_channel_evidence(red))
    assert len(github.issues) == 3
    green_event = _channel_evidence(green, verdict='passed')
    # A persisted green comment followed by a lost close response is resumed
    # without duplicating the comment or touching the other channel/human issue.
    github.comments[3].append({'user': github.bot, 'body': channel_bug._evidence_body(green_event, 'receipt')})
    github.reconcile(green_event)
    assert [row['state'] for row in github.issues] == ['open', 'open', 'closed']
    assert len(github.comments[3]) == 1


@pytest.mark.parametrize('fault', ['foreign_ref', 'foreign_repo', 'wrong_channel', 'wrong_operation',
                                  'untrusted_reason', 'nonmain_sha', 'unknown_read', 'duplicate_owned'])
def test_channel_bug_authority_failures_have_no_writes(fault):
    github = _ChannelGithub()
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    evidence = _channel_evidence(candidate)
    options = {'channel': 'dev', 'event': 'workflow_dispatch', 'ref': 'refs/heads/main',
               'repository': driver.REPOSITORY, 'run_id': 900, 'api': github.api}
    if fault == 'foreign_ref':
        options['ref'] = 'refs/heads/feature'
    elif fault == 'foreign_repo':
        options['repository'] = 'foreign/repo'
    elif fault == 'wrong_channel':
        evidence['channel'] = 'test'
    elif fault == 'wrong_operation':
        evidence['receipt']['operation_id'] = candidate.operation_id('test')
    elif fault == 'untrusted_reason':
        evidence['receipt']['source_failure'] = 'private-secret'
    elif fault == 'nonmain_sha':
        options['api'] = lambda method, path, data=None: ({'status': 'diverged'} if '/compare/' in path
                                                         else github.api(method, path, data))
    elif fault == 'unknown_read':
        options['api'] = lambda *args: (_ for _ in ()).throw(RuntimeError('private-secret'))
    elif fault == 'duplicate_owned':
        github.reconcile(evidence)
        github.issues.append(dict(github.issues[0]))
        github.effects.clear()
    with pytest.raises((channel_bug.AlertRefused, RuntimeError)):
        channel_bug.reconcile(evidence, **options)
    assert not github.effects


def test_channel_bug_workflow_keeps_writes_on_trusted_main():
    workflow = yaml.safe_load((ROOT / '.github/workflows/postmerge-channel-bug.yml').read_text())
    assert set(workflow.get('on', workflow.get(True))) == {'workflow_dispatch'}
    assert workflow['concurrency'] == {'group': 'postmerge-channel-verdict',
                                        'cancel-in-progress': False, 'queue': 'max'}
    assert workflow['run-name'].endswith('/${{ fromJSON(inputs.evidence).receipt_fingerprint }}')
    job = workflow['jobs']['reconcile']
    assert "github.ref == 'refs/heads/main'" in job['if']
    assert "github.repository == 'RasmusTho/agentic-pkm-mvp'" in job['if']
    assert job['permissions'] == {'contents': 'read', 'actions': 'read', 'issues': 'write'}
    assert job['runs-on'] == 'ubuntu-latest'
    assert job['steps'][0]['with'] == {'persist-credentials': False}
    step = job['steps'][1]
    assert step['run'] == 'python3 scripts/postmerge_channel_bug.py --channel "$CHANNEL" --evidence "$EVIDENCE"'
    assert '${{' not in step['run']


def test_channel_bug_crash_after_dispatch_intent_does_not_replay(tmp_path, monkeypatch):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)

    class Crash(BaseException):
        pass

    monkeypatch.setattr(driver, 'dispatch_channel_verdict', lambda evidence: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        _poll_channel(tmp_path, candidate, red='dev')
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert stored['phase'] == 'failed' and stored['channel_bug']['dispatch'] == 'started'
    monkeypatch.setattr(driver, 'dispatch_channel_verdict', lambda _: pytest.fail('ambiguous dispatch replay'))
    assert _poll_channel(tmp_path, candidate, red='dev') == 0
    next_candidate = replace(candidate, sha='c' * 40, run_id=124)
    monkeypatch.setattr(driver, 'dispatch_channel_verdict', lambda _: None)
    assert _poll_channel(tmp_path, next_candidate) == 0


def test_channel_bug_resumes_legacy_terminal_checkpoint_with_exact_receipt(tmp_path, channel_github):
    github = channel_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    tmp_path.chmod(0o700)
    pending = _channel_evidence(candidate)['receipt']
    pending['result'] = 'pending'
    driver._save_outcome(tmp_path / 'postmerge-dev-test.json', candidate, pending)
    assert driver.poll(tmp_path, resume=lambda ch, c: _native_receipt(ch, c, 'failed'),
                       deploy=lambda *_: pytest.fail('terminal replay')) == 78
    assert github.deliveries[0]['receipt']['operation_id'] == candidate.operation_id('dev')
    assert len(github.issues) == 1


def test_channel_bug_reopens_same_issue_after_recovery():
    github = _ChannelGithub()
    red = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    green = github.add(driver.Candidate('c' * 40, DIGEST, 124, 1, 457))
    later = github.add(driver.Candidate('d' * 40, DIGEST, 125, 1, 458))
    github.reconcile(_channel_evidence(red))
    github.reconcile(_channel_evidence(green, verdict='passed'))
    github.reconcile(_channel_evidence(later, last_good=green.sha))
    assert len(github.issues) == 1 and github.issues[0]['state'] == 'open'
    assert len(github.comments[1]) == 2
    assert f'{green.sha}...{later.sha}' in github.comments[1][-1]['body']


@pytest.mark.parametrize('field,value', [('last_green', {'prod': SHA}),
                                       ('last_green', {'dev': 'private'}),
                                       ('channel_bug', {'dispatch': 'sent', 'last_good_sha': 'private'})])
def test_channel_bug_rejects_malformed_checkpoint_before_effect(tmp_path, field, value):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    tmp_path.chmod(0o700)
    path = tmp_path / 'postmerge-dev-test.json'
    stored = driver._save_outcome(path, candidate, _channel_evidence(candidate)['receipt'])
    stored[field] = value
    driver._atomic_checkpoint(path, stored)
    with pytest.raises(driver.CandidateRefused, match='checkpoint_refused'):
        driver.poll(tmp_path, build=lambda: pytest.fail('admission before checkpoint validation'),
                    alert=lambda _: pytest.fail('write before validation'))


def test_channel_bug_pending_has_no_issue_write(tmp_path, channel_github):
    candidate = channel_github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    tmp_path.chmod(0o700)
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate, current_main=lambda: SHA,
                       deploy=lambda *_: (_ for _ in ()).throw(RuntimeError('private'))) == 78
    assert not channel_github.deliveries and not channel_github.effects


def test_channel_bug_conflicting_terminal_identity_is_refused():
    github = _ChannelGithub()
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.reconcile(_channel_evidence(candidate))
    count = len(github.effects)
    for changed in (replace(candidate, digest='sha256:' + 'c' * 64), replace(candidate, artifact_id=789)):
        with pytest.raises(channel_bug.AlertRefused, match='conflicting_candidate_identity'):
            github.reconcile(_channel_evidence(changed))
    with pytest.raises(channel_bug.AlertRefused, match='conflicting_terminal_verdict'):
        github.reconcile(_channel_evidence(candidate, verdict='passed'))
    assert len(github.effects) == count


def test_channel_bug_cli_hides_api_and_payload_failures(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['postmerge_channel_bug.py', '--channel', 'dev', '--evidence', 'private-secret'])
    assert channel_bug.main() == 1
    assert capsys.readouterr().out == '{"channel_bug": "refused"}\n'


def test_channel_bug_script_entrypoint_is_dependency_free(tmp_path):
    result = subprocess.run([sys.executable, '-S', str(ROOT / 'scripts/postmerge_channel_bug.py'), '--help'],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--evidence' in result.stdout


@pytest.mark.parametrize('conflict', ['verdict', 'digest', 'artifact', 'receipt'])
def test_channel_bug_initial_green_refuses_conflicting_terminal_replay(tmp_path, channel_github, conflict):
    # R1-F1: persist a real first-green workflow receipt with no rolling Issue.
    github = channel_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_channel(tmp_path, candidate) == 0
    assert not github.issues
    changed = (replace(candidate, digest='sha256:' + 'c' * 64) if conflict == 'digest' else
               replace(candidate, artifact_id=789) if conflict == 'artifact' else candidate)
    evidence = _channel_evidence(changed, channel='test', verdict='failed' if conflict == 'verdict' else 'passed')
    if conflict == 'receipt':
        evidence['receipt']['pg_acceptance']['report_hash'] = '9' * 64
    driver._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {
        'candidate': asdict(changed), 'channel': 'test', 'phase': evidence['verdict'], 'outcome': evidence['receipt'],
    })
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: changed,
                       deploy=lambda *_: pytest.fail('terminal deployment replay')) == 0
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert stored['channel_bug']['dispatch'] == 'failed'
    assert github.refusals[-1] == 'conflicting_terminal_verdict'
    assert not github.effects and not github.issues


def test_channel_bug_initial_green_identical_replay_has_no_issue_effect(tmp_path, channel_github):
    github = channel_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_channel(tmp_path, candidate) == 0
    evidence = _channel_evidence(candidate, channel='test', verdict='passed')
    driver._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {
        'candidate': asdict(candidate), 'channel': 'test', 'phase': 'passed', 'outcome': evidence['receipt'],
    })
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate,
                       deploy=lambda *_: pytest.fail('terminal deployment replay')) == 0
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['channel_bug']['dispatch'] == 'sent'
    assert not github.effects


@pytest.mark.parametrize('verdict', ['failed', 'passed'])
@pytest.mark.parametrize('latest', [('in_progress', None), ('completed', 'failure')])
def test_channel_bug_exact_build_attempt_survives_later_rerun(tmp_path, channel_github, verdict, latest):
    # R1-F2: a retained successful workflow attempt survives mutable latest metadata.
    github = channel_github
    if verdict == 'passed':
        previous = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
        assert _poll_channel(tmp_path, previous, red='dev') == 78
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.latest_runs[123] = {'run_attempt': 2, 'status': latest[0], 'conclusion': latest[1]}
    assert _poll_channel(tmp_path, candidate, red='dev' if verdict == 'failed' else None) == (78 if verdict == 'failed' else 0)
    assert github.issues[0]['state'] == ('open' if verdict == 'failed' else 'closed')
    prefix = f'repos/{driver.REPOSITORY}/actions/runs/123'
    assert prefix + '/attempts/1' in github.reads
    assert prefix not in github.reads


@pytest.mark.parametrize('verdict', ['failed', 'passed'])
@pytest.mark.parametrize('latest', [('in_progress', None), ('completed', 'failure')])
def test_channel_bug_real_loader_reuses_earlier_image_attempt(tmp_path, channel_github, monkeypatch, verdict, latest):
    # R1-F2 / R2: only network and native effects are fake. Production loader ->
    # poll -> outbound argv -> receiver must agree on admitted workflow attempt 2,
    # while the loader authenticates the retained image/artifact from attempt 1.
    github = channel_github
    if verdict == 'passed':
        previous = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
        assert _poll_channel(tmp_path, previous, red='dev') == 78
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 2, 456))
    run, proof = _build()
    run['run_attempt'] = 2
    metadata, archive = _artifact({**proof, 'run_id': 123, 'run_attempt': 1})
    metadata['name'] = f'app-image-tts-engine-proof-{SHA}-attempt-1'
    image_job = {'name': driver.BUILD_JOB, 'run_id': 123, 'run_attempt': 1,
                 'head_sha': SHA, 'status': 'completed', 'conclusion': 'success'}
    prefix = f'repos/{driver.REPOSITORY}'
    responses = {
        prefix + '/actions/runs/123': json.dumps(run).encode(),
        prefix + '/actions/runs/123/jobs?filter=all&per_page=100':
            json.dumps({'total_count': 1, 'jobs': [image_job]}).encode(),
        prefix + '/actions/runs/123/artifacts?per_page=100':
            json.dumps({'total_count': 1, 'artifacts': [metadata]}).encode(),
        prefix + '/actions/artifacts/456/zip': archive,
    }
    producer_reads = []

    def read(path):
        producer_reads.append(path)
        return responses[path]

    monkeypatch.setattr(driver, '_github', read)
    # The receiver runs after dispatch; a newer source attempt can already be
    # running/failed without invalidating the admitted successful attempt 2.
    github.latest_runs[123] = {'run_attempt': 3, 'status': latest[0], 'conclusion': latest[1]}
    tmp_path.chmod(0o700)
    assert driver.poll(tmp_path, build=lambda: 123, current_main=lambda: SHA,
                       deploy=lambda ch, c: _native_receipt(ch, c, 'failed' if verdict == 'failed' and ch == 'dev'
                                                            else 'committed')) == (78 if verdict == 'failed' else 0)
    if verdict == 'passed':
        assert driver.poll(tmp_path, build=lambda: 123, current_main=lambda: SHA,
                           deploy=lambda ch, c: _native_receipt(ch, c)) == 0
    evidence = next(row for row in github.deliveries if row['candidate']['run_id'] == 123 and row['channel'] == 'dev')
    assert evidence['candidate'] == asdict(candidate)
    assert evidence['receipt']['operation_id'] == candidate.operation_id('dev')
    assert evidence['receipt']['source_run_attempt'] == 2 and evidence['receipt']['artifact_id'] == 456
    assert set(producer_reads) == set(responses)
    assert prefix + '/actions/runs/123/attempts/2' in github.reads
    assert prefix + '/actions/runs/123' not in github.reads
    assert not github.refusals
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['channel_bug']['dispatch'] == 'sent'
    assert github.issues[0]['state'] == ('open' if verdict == 'failed' else 'closed')


@pytest.mark.parametrize('fault', ['wrong_attempt', 'failed_attempt', 'pending_attempt'])
def test_channel_bug_refuses_unproved_admitted_workflow_attempt(tmp_path, channel_github, fault):
    github = channel_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.attempts[(123, 1)] = ({'run_attempt': 2} if fault == 'wrong_attempt' else
                               {'conclusion': 'failure'} if fault == 'failed_attempt' else
                               {'status': 'in_progress', 'conclusion': None})
    assert _poll_channel(tmp_path, candidate, red='dev') == 78
    assert not github.effects and github.refusals == ['candidate_build_refused']
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['channel_bug']['dispatch'] == 'failed'


@pytest.mark.parametrize('late', ['same', 'older'])
@pytest.mark.parametrize('latest', [('completed', 'failure'), ('in_progress', None)])
def test_channel_bug_first_green_survives_reporting_workflow_reruns(tmp_path, channel_github, late, latest):
    # R1-F1 / R2: an accepted first green leaves no Issue. Later reporting-job
    # failures must not erase that acceptance and allow a false red Issue.
    github = channel_github
    old = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_channel(tmp_path, candidate) == 0
    reporting = next(row for row in github.runs if row['display_title'].startswith('channel-bug/test/'))
    github.workflow_attempts[(reporting['id'], 1)] = dict(reporting)
    github.workflow_attempts[(reporting['id'], 2)] = {**reporting, 'run_attempt': 2, 'conclusion': 'failure'}
    reporting.update(run_attempt=3, status=latest[0], conclusion=latest[1])
    delayed = candidate if late == 'same' else old
    receipt = _channel_evidence(delayed, channel='test')['receipt']
    driver._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {
        'candidate': asdict(delayed), 'channel': 'test', 'phase': 'failed', 'outcome': receipt,
    })
    assert driver.poll(tmp_path, build=lambda: delayed.run_id, load=lambda _: delayed,
                       deploy=lambda *_: pytest.fail('terminal deployment replay')) == 0
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert stored['channel_bug']['dispatch'] == ('failed' if late == 'same' else 'sent')
    assert github.refusals == (['conflicting_terminal_verdict'] if late == 'same' else [])
    assert not github.effects and not github.issues
    assert f"repos/{driver.REPOSITORY}/actions/runs/{reporting['id']}/attempts/1" in github.reads
    assert f"repos/{driver.REPOSITORY}/actions/runs/{reporting['id']}/attempts/2" in github.reads
    assert not any('status=success' in path for path in github.reads)


@pytest.mark.parametrize('fault', ['unreadable', 'wrong_identity', 'missing_conclusion', 'incomplete'])
def test_channel_bug_unproved_reporting_history_refuses_mutation(tmp_path, channel_github, fault):
    github = channel_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_channel(tmp_path, candidate) == 0
    reporting = next(row for row in github.runs if row['display_title'].startswith('channel-bug/test/'))
    prior = dict(reporting)
    if fault == 'wrong_identity':
        prior['display_title'] = 'foreign workflow input'
    elif fault == 'missing_conclusion':
        prior.pop('conclusion')
    github.workflow_attempts[(reporting['id'], 1)] = RuntimeError('unreadable') if fault == 'unreadable' else prior
    reporting.update(run_attempt=101 if fault == 'incomplete' else 2, conclusion='failure')
    receipt = _channel_evidence(candidate, channel='test')['receipt']
    driver._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {
        'candidate': asdict(candidate), 'channel': 'test', 'phase': 'failed', 'outcome': receipt,
    })
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate,
                       deploy=lambda *_: pytest.fail('terminal deployment replay')) == 0
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['channel_bug']['dispatch'] == 'failed'
    assert not github.effects and not github.issues


def test_channel_bug_failed_reporting_attempts_do_not_claim_acceptance(tmp_path, channel_github):
    github = channel_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_channel(tmp_path, candidate) == 0
    reporting = next(row for row in github.runs if row['display_title'].startswith('channel-bug/test/'))
    # Simulate a different report that never reached acceptance on any attempt.
    reporting['conclusion'] = 'failure'
    github.workflow_attempts[(reporting['id'], 1)] = dict(reporting)
    reporting['run_attempt'] = 2
    receipt = _channel_evidence(candidate, channel='test')['receipt']
    driver._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {
        'candidate': asdict(candidate), 'channel': 'test', 'phase': 'failed', 'outcome': receipt,
    })
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate,
                       deploy=lambda *_: pytest.fail('terminal deployment replay')) == 0
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['channel_bug']['dispatch'] == 'sent'
    assert not github.refusals
    assert len(github.issues) == 1 and github.issues[0]['state'] == 'open'


@pytest.mark.parametrize('field', ['diagnostic', 'reason', 'failure_reference', 'operation_id'])
def test_channel_bug_private_retained_fields_never_cross_dispatch(tmp_path, channel_github, capsys, field):
    # R1-F3: use the real controller outbound function, not a validating callback.
    github = channel_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    tmp_path.chmod(0o700)
    outcome = _channel_evidence(candidate)['receipt']
    outcome[field] = 'review-private-canary-only'
    driver._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {
        'candidate': asdict(candidate), 'channel': 'dev', 'phase': 'failed', 'outcome': outcome,
    })
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate,
                       deploy=lambda *_: pytest.fail('terminal deployment replay')) == 0
    assert not github.deliveries and not github.effects
    assert 'review-private-canary-only' not in capsys.readouterr().out
    assert json.loads((tmp_path / 'postmerge-dev-test.json').read_text())['channel_bug']['dispatch'] == 'failed'
    later = github.add(replace(candidate, sha='c' * 40, run_id=124))
    assert _poll_channel(tmp_path, later) == 0
    assert github.deliveries
    assert 'review-private-canary-only' not in json.dumps(github.deliveries)


@pytest.fixture
def installed_controller_pin(tmp_path, monkeypatch):
    """Real archive/runtime/install/LaunchAgent producers, with only host I/O isolated."""
    from scripts import install_postmerge_controller as installer
    from scripts import postmerge_controller as bootstrap
    checkout = tmp_path / 'reviewed'
    checkout.mkdir()
    for name in ('app/ops', 'app/config'):
        shutil.copytree(ROOT / name, checkout / name, ignore=shutil.ignore_patterns('__pycache__'))
    (checkout / 'app/__init__.py').write_bytes((ROOT / 'app/__init__.py').read_bytes())
    (checkout / 'scripts').mkdir()
    shutil.copy2(ROOT / 'requirements-bws-deploy.txt', checkout / 'requirements-bws-deploy.txt')
    for name in ('__init__.py', 'postmerge_controller.py', 'postmerge_dev_test.py', 'select_pr_tests.py'):
        shutil.copy2(ROOT / 'scripts' / name, checkout / 'scripts' / name)
    def git(*args):
        return subprocess.run(['git', '-C', str(checkout), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    git('init', '--quiet', '-b', 'main')
    git('config', 'user.name', 'Fixture')
    git('config', 'user.email', 'fixture@example.invalid')
    git('add', '.')
    git('commit', '--quiet', '-m', 'Reviewed real controller closure')
    sha = git('rev-parse', 'HEAD')
    # Supply a real qualified source environment, including user-installed
    # packages in this test process, then prove its removal cannot affect the pin.
    source_runtime = checkout / '.bootstrap'
    subprocess.run([sys.executable, '-I', '-S', '-m', 'venv', '--without-pip', '--copies', str(source_runtime)],
                   capture_output=True, check=True)
    source_python = source_runtime / 'bin/python'
    library = subprocess.run([str(source_python), '-I', '-c',
                              'import sysconfig; print(sysconfig.get_path("purelib"))'],
                             capture_output=True, text=True, check=True).stdout.strip()
    Path(library).rmdir()
    bootstrap.copy_runtime_dependencies(Path(library))
    gh = tmp_path / 'gh'
    signals = tmp_path / 'signals.json'
    gh.write_text('#!/bin/sh\nif [ "$1" = api ]; then\n'
                  + "printf '%s\\n' '{\"object\":{\"sha\":\"" + SHA + "\"}}'\n"
                  + 'else\nfor arg do case "$arg" in payload=*) printf "%s" "${arg#payload=}" > "'
                  + str(signals) + '";; esac; done\nfi\n')
    gh.chmod(0o700)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ.get('PATH', ''))
    home = tmp_path / 'home'
    monkeypatch.setattr(installer.Path, 'home', staticmethod(lambda: home))
    monkeypatch.setattr(installer.sys, 'platform', 'darwin')
    # Canonical provenance/fetch admission has its own real-git negative matrix;
    # this fixture begins at that admitted boundary and runs every producer after it.
    monkeypatch.setattr(installer, 'require_reviewed_checkout', lambda *_: sha)
    assert installer.main(['--checkout', str(checkout), '--python', str(source_python)]) == 0
    state = home / '.local/state/yggdrasil/secret-controller/postmerge'
    config = plistlib.loads((home / 'Library/LaunchAgents' / (installer.LABEL + '.plist')).read_bytes())
    return SimpleNamespace(checkout=checkout, source=state / 'tooling' / sha / 'source',
                           state=state, config=config, sha=sha, signals=signals, gh=gh, source_python=source_python, source_library=Path(library))


def test_controller_runs_from_pinned_tooling(installed_controller_pin, tmp_path):
    pin = installed_controller_pin
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    marker = tmp_path / 'candidate-imported'
    for package in ('app', 'scripts'):
        path = candidate / package / '__init__.py'
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"from pathlib import Path; Path({str(marker)!r}).touch(); raise RuntimeError('candidate')")
    (candidate / 'sitecustomize.py').write_text(f"from pathlib import Path; Path({str(marker)!r}).touch()")
    # The original checkout can advance or become unusable after installation.
    shutil.rmtree(pin.checkout)
    env = {**os.environ, 'PYTHONPATH': str(candidate), 'PYTHONHOME': str(candidate)}
    command = pin.config['ProgramArguments']
    result = subprocess.run([*command, '--self-check'], cwd=candidate, env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'result': 'startup_self_check_passed', 'tooling_sha': pin.sha}
    assert pin.config['WorkingDirectory'] == str(pin.source)
    evidence = json.loads((pin.source.parent / 'pin.json').read_text())
    assert evidence['dependencies'] == {'bitwarden-sdk': '2.1.0', 'python-dateutil': '2.9.0.post0', 'six': '1.17.0'}
    assert len(evidence['dependency_files_sha256']) == 64
    assert not marker.exists() and not pin.signals.exists()
    # Exercise the actual child import producer from the installed runtime.
    # --help traverses the real native host imports without deployment effects.
    native = """import sys, subprocess
sys.path.insert(0, sys.argv[1])
from scripts.postmerge_dev_test import _native_host_command
raise SystemExit(subprocess.run([*_native_host_command(), '--help']).returncode)
"""
    child = subprocess.run([command[0], '-I', '-S', '-c', native, str(pin.source)],
                           cwd=candidate, env=env, capture_output=True, text=True, check=False)
    assert child.returncode == 0, child.stderr
    assert '--existing-secrets-only' in child.stdout and not marker.exists()
    factory = """import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.dont_write_bytecode = True
sys.path[:0] = [str(root), str(root.parent / 'vendor')]
from app.ops.bws_secret_reader import _sdk_client
client = _sdk_client()
assert type(client).__module__ == 'bitwarden_sdk.bitwarden_client'
print('real_sdk_factory_passed')
"""
    lazy = subprocess.run([command[0], '-I', '-S', '-c', factory, str(pin.source)],
                          cwd=candidate, env=env, capture_output=True, text=True, check=False)
    assert lazy.returncode == 0, lazy.stderr
    assert lazy.stdout.strip() == 'real_sdk_factory_passed' and not marker.exists()


@pytest.mark.parametrize('fault', ['controller_import', 'host_import', 'lazy_import', 'pin_missing', 'python_identity',
                                  'transport_down', 'sdk_missing', 'sdk_native_missing', 'dependency_version',
                                  'sdk_dependency_missing', 'sdk_hash_changed'])
def test_controller_self_check_fails_loud(installed_controller_pin, monkeypatch, fault):
    from scripts import dev_delivery_liveness as liveness
    pin = installed_controller_pin
    if fault in {'controller_import', 'host_import', 'lazy_import', 'transport_down'}:
        module = {'controller_import': 'scripts/postmerge_dev_test.py',
                  'host_import': 'app/ops/postgres_deploy_host.py',
                  'lazy_import': 'app/ops/native_source_bootstrap.py',
                  'transport_down': 'scripts/postmerge_dev_test.py'}[fault]
        (pin.source / module).write_text("raise ModuleNotFoundError('private input must not leak')\n")
    elif fault in {'sdk_missing', 'sdk_native_missing', 'dependency_version', 'sdk_dependency_missing', 'sdk_hash_changed'}:
        from scripts import postmerge_controller as bootstrap
        vendor = pin.source.parent / 'vendor'
        if fault == 'sdk_missing':
            shutil.rmtree(vendor / 'bitwarden_sdk')
        elif fault == 'sdk_dependency_missing':
            shutil.rmtree(vendor / 'dateutil')
        elif fault == 'sdk_native_missing':
            for native in (vendor / 'bitwarden_py').glob('*.so'):
                native.unlink()
        elif fault == 'sdk_hash_changed':
            entry = vendor / 'bitwarden_sdk/bitwarden_client.py'
            entry.write_bytes(b'#' + entry.read_bytes()[1:])
        else:
            entry = next(vendor.glob('bitwarden_sdk-*.dist-info/METADATA'))
            entry.write_text(entry.read_text().replace('Version: 2.1.0', 'Version: 0.0.0'))
        # Model an incomplete producer that sealed its own incomplete bytes:
        # metadata/import/factory preflight must still refuse, beyond the hash.
        entry = pin.source.parent / 'pin.json'
        data = json.loads(entry.read_text())
        if fault != 'sdk_hash_changed':
            data['dependency_files_sha256'] = bootstrap.dependency_fingerprint(vendor)
        entry.write_text(json.dumps(data))
    elif fault == 'pin_missing':
        (pin.source.parent / 'pin.json').unlink()
    else:
        path = pin.source.parent / 'pin.json'
        data = json.loads(path.read_text())
        data['python_version'] = 'wrong runtime'
        path.write_text(json.dumps(data))
    if fault == 'transport_down':
        pin.gh.write_text('#!/bin/sh\nexit 1\n')
    checkpoint = pin.state / 'postmerge-dev-test.json'
    before_checkpoint = checkpoint.read_bytes()
    result = subprocess.run(pin.config['ProgramArguments'], cwd=pin.source,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 78
    assert json.loads(result.stdout) == {'result': 'startup_self_check_failed',
                                       'liveness_signal': 'failed' if fault == 'transport_down' else 'sent'}
    assert 'private input' not in result.stdout + result.stderr
    assert checkpoint.read_bytes() == before_checkpoint
    if fault == 'transport_down':
        assert not pin.signals.exists()
        assert not liveness.evaluate(None, heartbeat_statuses=[], verdict_statuses=[],
                                     now=datetime.now(timezone.utc)).ok
        return
    payload = json.loads(pin.signals.read_text())
    assert payload['sha'] == SHA and payload['startup'] == 'failed'
    # Consume the real bootstrap's payload through the actual main-only status
    # admission and liveness evaluator, including a prior fresh DEV verdict.
    writes = []
    monkeypatch.setattr(liveness.subprocess, 'run', lambda command, **_: writes.append(command))
    now = datetime.fromisoformat(payload['observed_at']) + timedelta(seconds=1)
    def admit(received, at=now):
        writes.clear()
        liveness.record_signal('heartbeat', json.dumps(received), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                               api=lambda _: {'status': 'identical'}, now=at)
        fields = dict(item.split('=', 1) for item in writes[0] if '=' in item)
        return {key: fields[key] for key in ('state', 'context', 'description')}
    status = admit(payload)
    assert status['state'] == 'failure' and status['description'].endswith(';startup=self_check_failed')
    build = liveness.AdmittedBuild(SHA, now - timedelta(hours=1), 123)
    verdict = {'state': 'success', 'context': liveness.VERDICT_CONTEXT,
               'description': 'observed_at=' + (now - timedelta(minutes=2)).isoformat()}
    produced = []
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, received: produced.append(received))
    observation = {'sequence': payload['after_sequence'], 'observed_at': (now - timedelta(minutes=1)).isoformat()}
    driver.publish_heartbeat(SHA, None, observation)
    prior = admit(produced[-1])
    pause = {'issue': 6224, 'engaged_at': (now - timedelta(minutes=1)).isoformat(),
             'expires_at': (now + timedelta(minutes=5)).isoformat()}
    driver.publish_heartbeat(SHA, pause, observation)
    paused = admit(produced[-1])
    recovery_at = now + timedelta(minutes=6)
    driver.publish_heartbeat(SHA, None, {'sequence': observation['sequence'] + 1, 'observed_at': recovery_at.isoformat()})
    recovered = admit(produced[-1], at=recovery_at)
    newer_main = 'b' * 40
    def check_history(history, at=now):
        def api(endpoint):
            if '/actions/workflows/' in endpoint:
                return {'workflow_runs': []}
            if '/statuses?' in endpoint:
                return [] if f'/commits/{newer_main}/' in endpoint else history
            if '/git/commits/' in endpoint:
                return {'sha': newer_main, 'parents': [{'sha': SHA}]}
            pytest.fail('unexpected liveness read: ' + endpoint)
        return liveness.check(driver.REPOSITORY, newer_main, api=api, now=at)
    # Real startup refusal overrides prior real sequenced activity/pause and a
    # fresh verdict, including after main advances without another host tick.
    for previous in (prior, paused):
        history = [previous, status]
        checked = liveness.evaluate(build, heartbeat_statuses=history, verdict_statuses=[verdict], now=now)
        assert not checked.ok and checked.reason == 'startup_self_check_failed'
        assert check_history(history).reason == 'startup_self_check_failed'
    later_verdict = {**verdict, 'description': 'observed_at=' + now.isoformat()}
    assert not liveness.evaluate(build, heartbeat_statuses=[paused, status],
                                 verdict_statuses=[later_verdict], now=now).ok
    # Later real activity recovers; replaying the older failure cannot undo it.
    assert check_history([prior, status, recovered, status], at=recovery_at).ok
    assert liveness.evaluate(build, heartbeat_statuses=[paused, status, recovered],
                             verdict_statuses=[verdict], now=recovery_at).ok


@pytest.mark.parametrize('stage', ['runtime', 'dependencies', 'dependency_version', 'dependency_files', 'dependency_hash'])
def test_installer_partial_pin_does_not_replace_active_launch_or_checkpoint(installed_controller_pin, monkeypatch, stage):
    from scripts import install_postmerge_controller as installer
    pin = installed_controller_pin
    # Use the actual existing LaunchAgent path rather than manufacturing a
    # replacement producer. A failed staged runtime leaves it byte-identical.
    plist = next(pin.state.parents[4].glob('Library/LaunchAgents/*.plist'))
    before = plist.read_bytes()
    checkpoint = pin.state / 'postmerge-dev-test.json'
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    assert driver.poll(pin.state, build=lambda: 123, load=lambda _: candidate,
                       current_main=lambda: SHA, deploy=lambda *_: {'terminal_result': 'unknown'}) == 78
    pending = json.loads(checkpoint.read_text())
    pending['last_green'] = {'dev': 'd' * 40}
    driver._atomic_checkpoint(checkpoint, pending)
    before_checkpoint = checkpoint.read_bytes()
    sha = 'c' * 40
    monkeypatch.setattr(installer, 'require_reviewed_checkout', lambda *_: sha)
    if stage == 'dependencies':
        shutil.rmtree(next(pin.source_library.glob('bitwarden_sdk-*.dist-info')))
    elif stage == 'dependency_version':
        entry = next(pin.source_library.glob('bitwarden_sdk-*.dist-info/METADATA'))
        entry.write_text(entry.read_text().replace('Version: 2.1.0', 'Version: 0.0.0'))
    elif stage == 'dependency_files':
        for native in (pin.source_library / 'bitwarden_py').glob('*.so'):
            native.unlink()
    elif stage == 'dependency_hash':
        entry = pin.source_library / 'bitwarden_sdk/bitwarden_client.py'
        entry.write_bytes(b'#' + entry.read_bytes()[1:])
    run = subprocess.run
    def fail_runtime(command, **kwargs):
        if stage == 'runtime' and 'venv' in command:
            raise subprocess.CalledProcessError(1, command)
        if 'archive' in command:
            command = [pin.sha if part == sha else part for part in command]
        return run(command, **kwargs)
    monkeypatch.setattr(installer.subprocess, 'run', fail_runtime)
    assert installer.main(['--checkout', str(pin.checkout), '--python', str(pin.source_python)]) == 78
    assert plist.read_bytes() == before
    assert checkpoint.read_bytes() == before_checkpoint
    assert not (pin.state / 'tooling' / sha).exists()
    assert not list((pin.state / 'tooling').glob('.install-*'))
    retained = run([*pin.config['ProgramArguments'], '--self-check'], capture_output=True, text=True)
    assert retained.returncode == 0, retained.stdout + retained.stderr


@pytest.mark.parametrize('value', ['passed', 'unknown', True, None])
def test_startup_signal_refuses_non_failure_values(monkeypatch, value):
    from scripts import dev_delivery_liveness as liveness
    payload = {'protocol': driver.LIVENESS_PROTOCOL, 'sha': SHA,
               'observed_at': datetime.now(timezone.utc).isoformat(), 'startup': value, 'after_sequence': 0}
    monkeypatch.setattr(liveness.subprocess, 'run', lambda *_a, **_k: pytest.fail('refused signal wrote a status'))
    with pytest.raises(liveness.LivenessRefused, match='signal_startup_refused'):
        liveness.record_signal('heartbeat', json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999')


def test_native_host_command_preserves_interpreter_alias(tmp_path, monkeypatch):
    interpreter = tmp_path / 'runtime' / 'bin' / 'python3'
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    assert str(interpreter.resolve()) != str(interpreter)
    monkeypatch.setattr(driver.sys, 'executable', str(interpreter))
    command = driver._native_host_command()
    assert command[0] == str(interpreter)
    assert command[1:4] == ['-I', '-S', '-c']
    assert command[5] == str(ROOT)


def test_native_absence_child_uses_same_isolated_tooling_command(monkeypatch):
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    proof = _absence_proof('dev', candidate)
    calls = []
    monkeypatch.setenv('GH_TOKEN', 'secret-canary')
    monkeypatch.setenv('GITHUB_TOKEN', 'secret-canary')
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(proof))
    monkeypatch.setattr(driver.subprocess, 'run', run)
    assert driver.native_absence('dev', candidate) == proof
    command, options = calls[0]
    assert command[:6] == driver._native_host_command()
    assert command[1:4] == ['-I', '-S', '-c']
    assert command[-1] == '--prove-never-admitted'
    assert 'GH_TOKEN' not in options['env'] and 'GITHUB_TOKEN' not in options['env']


@pytest.mark.parametrize('options', [
    [], ['--issue', '6224'], ['--until', '2099-01-01T00:00:00Z'],
    ['--issue', '0', '--until', '2099-01-01T00:00:00Z'],
    ['--issue', '6224', '--until', 'invalid'],
    ['--issue', '6224', '--until', '2099-01-01T00:00:00'],
    ['--issue', '6224', '--until', '2000-01-01T00:00:00Z'],
])
def test_kill_switch_requires_issue_and_expiry(tmp_path, monkeypatch, options):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(driver, '_github', lambda *_: pytest.fail('pause must not add host API permissions'))
    assert driver.main(['--pause', '--state-directory', str(tmp_path), *options]) == 78
    assert not (tmp_path / 'postmerge-dev-test.json').exists()


def test_kill_switch_pauses_until_expiry(tmp_path, monkeypatch, capsys):
    tmp_path.chmod(0o700)
    now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    until = now + timedelta(minutes=5)
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    monkeypatch.setattr(driver, '_github', lambda *_: pytest.fail('pause requires no additional API scope'))
    assert driver.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                        '--until', until.isoformat()]) == 0
    path = tmp_path / 'postmerge-dev-test.json'
    stored = json.loads(path.read_text())
    assert stored['pause'] == {'issue': 6224, 'engaged_at': now.isoformat(), 'expires_at': until.isoformat()}
    assert path.stat().st_mode & 0o777 == 0o600
    signals = []
    unexpected = lambda *_: pytest.fail('paused controller reached candidate or native work')
    # A later process reads the retained checkpoint, including at the last instant before expiry.
    for instant in (now, until - timedelta(microseconds=1)):
        monkeypatch.setattr(driver, '_utc_now', lambda: instant)
        assert driver.poll(tmp_path, build=unexpected, load=unexpected, deploy=unexpected,
                           resume=unexpected, absence=unexpected, heavy=unexpected,
                           current_main=lambda: SHA, heartbeat=lambda sha, pause, observation: signals.append((sha, pause))) == 0
    assert signals == [(SHA, stored['pause']), (SHA, stored['pause'])]
    assert 'paused (#6224, until 2026-10-19T10:05:00+00:00)' in capsys.readouterr().out
    updated = json.loads(path.read_text())
    assert updated['pause'] == stored['pause']
    assert updated['observation']['sequence'] == stored['observation']['sequence'] + 2
    # Exercise the real producer and trusted Actions writer, then the public
    # checker. Only HTTP/process transport is doubled, never pause semantics.
    from scripts import dev_delivery_liveness as liveness
    payloads = []
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, payload: payloads.append((kind, payload)))
    driver.publish_heartbeat(SHA, stored['pause'], updated['observation'])
    writes = []
    def status_transport(command, **kwargs):
        writes.append(dict(arg.split('=', 1) for arg in command if '=' in arg))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(liveness.subprocess, 'run', status_transport)
    liveness.record_signal(payloads[0][0], json.dumps(payloads[0][1]), repo=driver.REPOSITORY,
                           event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                           triggering_actor='RasmusTho',
                           run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                           api=lambda _: {'status': 'identical'}, now=instant)
    assert writes[0]['state'] == 'failure'
    statuses = [writes[0], {'context': liveness.VERDICT_CONTEXT, 'state': 'success',
                           'description': 'observed_at=' + instant.isoformat()}]
    run, _ = _build()
    run['completed_at'] = run['created_at'] = (now - timedelta(hours=1)).isoformat()
    def public_api(path):
        return {'workflow_runs': [run]} if '/workflows/' in path else statuses
    observed = liveness.check(driver.REPOSITORY, SHA, api=public_api, now=instant)
    assert not observed.ok and observed.reason == 'paused'
    assert observed.description == 'paused (#6224, until 2026-10-19T10:05:00+00:00)'
    # A replay/late write cannot extend the retained expiry or hide behind a fresh verdict.
    statuses[0]['updated_at'] = (until + timedelta(hours=1)).isoformat()
    assert liveness.check(driver.REPOSITORY, SHA, api=public_api, now=until).ok
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    deployments = []
    def deploy(channel, received):
        deployments.append((channel, received))
        return _native_receipt(channel, received)
    monkeypatch.setattr(driver, '_utc_now', lambda: until)
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate, deploy=deploy,
                       current_main=lambda: SHA, heartbeat=lambda sha, pause, observation: signals.append((sha, pause))) == 0
    assert deployments == [('dev', candidate)]
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate, deploy=deploy,
                       current_main=lambda: SHA) == 0
    assert deployments == [('dev', candidate), ('test', candidate)]
    assert signals[-1] == (SHA, None)
    assert json.loads(path.read_text())['pause'] == stored['pause']


def test_kill_switch_preserves_pending_operation_and_resumes_after_expiry(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    assert driver.poll(tmp_path, build=lambda: 123, load=lambda _: candidate,
                       current_main=lambda: SHA, deploy=lambda *_: {'terminal_result': 'unknown'}) == 78
    path = tmp_path / 'postmerge-dev-test.json'
    pending = json.loads(path.read_text())
    now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    until = now + timedelta(minutes=5)
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    assert driver.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                        '--until', until.isoformat()]) == 0
    assert {k: v for k, v in json.loads(path.read_text()).items() if k not in {'pause', 'observation'}} == {
        k: v for k, v in pending.items() if k != 'observation'}
    unexpected = lambda *_: pytest.fail('pause must cover recovery and deployment')
    assert driver.poll(tmp_path, build=unexpected, deploy=unexpected, resume=unexpected) == 0
    monkeypatch.setattr(driver, '_utc_now', lambda: until)
    resumed = []
    def resume(channel, received):
        resumed.append((channel, received))
        return _native_receipt(channel, received)
    assert driver.poll(tmp_path, resume=resume, deploy=resume, build=unexpected) == 0
    assert resumed == [('dev', candidate), ('test', candidate)]


@pytest.mark.parametrize('change', [
    {'issue': 0}, {'issue': True}, {'expires_at': 'invalid'},
    {'expires_at': '2026-10-19T10:05:00'}, {'extra': 'unrecognized'},
    {'engaged_at': '2026-10-19T10:06:00+00:00'},
])
def test_kill_switch_malformed_checkpoint_refuses_before_effect(tmp_path, monkeypatch, change):
    tmp_path.chmod(0o700)
    pause = {'issue': 6224, 'engaged_at': '2026-10-19T10:00:00+00:00',
             'expires_at': '2026-10-19T10:05:00+00:00'}
    driver._atomic_checkpoint(tmp_path / 'postmerge-dev-test.json', {'pause': {**pause, **change},
        'observation': {'sequence': 1, 'observed_at': pause['engaged_at']}})
    unexpected = lambda *_: pytest.fail('invalid pause reached external work')
    with pytest.raises(driver.CandidateRefused, match='checkpoint_refused'):
        driver.poll(tmp_path, build=unexpected, deploy=unexpected, heartbeat=unexpected)


def test_kill_switch_failed_persistence_preserves_checkpoint(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    options = ['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
               '--until', (now + timedelta(minutes=5)).isoformat()]
    assert driver.main(options) == 0
    path = tmp_path / 'postmerge-dev-test.json'
    before = path.read_bytes()
    original = driver.os.replace
    monkeypatch.setattr(driver.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('unavailable')))
    assert driver.main([*options[:-1], (now + timedelta(minutes=10)).isoformat()]) == 78
    assert path.read_bytes() == before
    monkeypatch.setattr(driver.os, 'replace', original)
    assert driver.main([*options[:-1], (now + timedelta(minutes=10)).isoformat()]) == 0
    assert json.loads(path.read_text())['pause']['expires_at'] == (now + timedelta(minutes=10)).isoformat()


def test_kill_switch_cannot_be_bypassed_by_manual_source_run(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(driver, 'load_candidate', lambda *_: pytest.fail('uncheckpointed deployment'))
    assert driver.main(['--source-run', '123']) == 78
    assert driver.main(['--latest', '--issue', '6224', '--until', '2099-01-01T00:00:00Z',
                        '--state-directory', str(tmp_path)]) == 78



def test_kill_switch_manual_entrypoint_honors_pause_and_read_only_admission(tmp_path, monkeypatch, capsys):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(driver, '_github', lambda _: json.dumps({'sha': SHA}).encode())
    monkeypatch.setattr(driver, 'publish_heartbeat', lambda *_: None, raising=False)
    now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    assert driver.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                        '--until', (now + timedelta(minutes=5)).isoformat()]) == 0
    monkeypatch.setattr(driver, 'load_candidate', lambda *_: pytest.fail('paused manual deployment'))
    assert driver.main(['--source-run', '123', '--state-directory', str(tmp_path)]) == 0
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    monkeypatch.setattr(driver, 'load_candidate', lambda _: candidate)
    assert driver.main(['--source-run', '123', '--admit-only']) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1]) == asdict(candidate)


def test_kill_switch_locked_checkpoint_refuses_without_replacing_state(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    with driver.checkpoint_lock(tmp_path):
        assert driver.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                            '--until', (now + timedelta(minutes=5)).isoformat()]) == 78
    assert not (tmp_path / 'postmerge-dev-test.json').exists()



def test_kill_switch_clock_regression_refuses_before_effect(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    now = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    assert driver.main(['--pause', '--state-directory', str(tmp_path), '--issue', '6224',
                        '--until', (now + timedelta(minutes=5)).isoformat()]) == 0
    monkeypatch.setattr(driver, '_utc_now', lambda: now - timedelta(seconds=1))
    unexpected = lambda *_: pytest.fail('regressed clock reached external work')
    with pytest.raises(driver.CandidateRefused, match='controller_clock_regressed'):
        driver.poll(tmp_path, build=unexpected, heartbeat=unexpected)


def test_installer_initializes_observation_and_refuses_lost_checkpoint(installed_controller_pin, monkeypatch):
    from scripts import install_postmerge_controller as installer
    pin = installed_controller_pin
    path = pin.state / 'postmerge-dev-test.json'
    checkpoint = json.loads(path.read_text())
    assert checkpoint['observation']['sequence'] == 1
    driver._validate_checkpoint(checkpoint)
    assert path.stat().st_mode & 0o777 == 0o600
    plist = next(pin.state.parents[4].glob('Library/LaunchAgents/*.plist'))
    before = plist.read_bytes()
    path.unlink()
    monkeypatch.setattr(installer.subprocess, 'run', lambda *_args, **_kwargs: pytest.fail('lost checkpoint reached pin preparation or host effect'))
    options = ['--checkout', str(pin.checkout), '--python', str(pin.source_python), '--enable']
    assert installer.main(options) == 78
    assert not path.exists() and plist.read_bytes() == before


@pytest.mark.parametrize('legacy', [False, True])
def test_pinned_tooling_update_preserves_authoritative_pending_state(installed_controller_pin, monkeypatch, legacy):
    from scripts import install_postmerge_controller as installer
    pin = installed_controller_pin
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    assert driver.poll(pin.state, build=lambda: 123, load=lambda _: candidate,
                       current_main=lambda: SHA, deploy=lambda *_: {'terminal_result': 'unknown'}) == 78
    path = pin.state / 'postmerge-dev-test.json'
    pending = json.loads(path.read_text())
    pending['last_green'] = {'dev': 'd' * 40}
    if legacy:
        pending.pop('observation')
    driver._atomic_checkpoint(path, pending)
    before = path.read_bytes()
    lock_inode = (pin.state / 'postmerge-dev-test.lock').stat().st_ino
    # A real second reviewed source commit exercises pin replacement, rather
    # than only reusing the first installed directory.
    (pin.checkout / 'reviewed-update.txt').write_text('Reviewed tooling update fixture\n')
    subprocess.run(['git', '-C', str(pin.checkout), 'add', 'reviewed-update.txt'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(pin.checkout), 'commit', '--quiet', '-m', 'Reviewed tooling update'],
                   check=True, capture_output=True)
    sha = subprocess.run(['git', '-C', str(pin.checkout), 'rev-parse', 'HEAD'],
                         check=True, capture_output=True, text=True).stdout.strip()
    monkeypatch.setattr(installer, 'require_reviewed_checkout', lambda *_: sha)
    assert installer.main(['--checkout', str(pin.checkout), '--python', str(pin.source_python)]) == 0
    assert path.read_bytes() == before
    assert (pin.state / 'postmerge-dev-test.lock').stat().st_ino == lock_inode
    assert (pin.state / 'tooling' / sha / 'pin.json').is_file()
    assert pending['candidate'] == asdict(candidate)


@pytest.mark.parametrize('activity', [{'sequence': 1}, {'pause': {}}])
def test_startup_diagnostic_cannot_borrow_activity_order(monkeypatch, activity):
    from scripts import dev_delivery_liveness as liveness
    payload = {'protocol': driver.LIVENESS_PROTOCOL, 'sha': SHA,
               'observed_at': datetime.now(timezone.utc).isoformat(), 'startup': 'failed', 'after_sequence': 0, **activity}
    with pytest.raises(liveness.LivenessRefused, match='signal_startup_refused'):
        liveness.record_signal('heartbeat', json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999')


@pytest.mark.parametrize('checkpoint_clock_ahead', [False, True])
def test_startup_diagnostic_discovers_ancestor_pause_before_fresh_verdict(
    installed_controller_pin, monkeypatch, checkpoint_clock_ahead,
):
    from scripts import dev_delivery_liveness as liveness
    pin = installed_controller_pin
    pause_at = datetime.now(timezone.utc) + timedelta(seconds=30 if checkpoint_clock_ahead else 0)
    until = pause_at + timedelta(minutes=10)
    monkeypatch.setattr(driver, '_utc_now', lambda: pause_at)
    produced = []
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, payload: produced.append((kind, payload)))
    assert driver.main(['--pause', '--state-directory', str(pin.state), '--issue', '6224',
                        '--until', until.isoformat()]) == 0
    unexpected = lambda *_: pytest.fail('active pause reached native or candidate work')
    assert driver.poll(pin.state, build=unexpected, deploy=unexpected, resume=unexpected,
                       current_main=lambda: SHA, heartbeat=driver.publish_heartbeat) == 0
    pause_payload = produced[-1][1]
    newer_main, newest_main = 'c' * 40, 'd' * 40
    pin.gh.write_text(pin.gh.read_text().replace(SHA, newer_main))
    controller_file = pin.source / 'scripts/postmerge_dev_test.py'
    original = controller_file.read_bytes()
    controller_file.write_text("raise ModuleNotFoundError('refused tooling fixture')\n")
    failed = subprocess.run(pin.config['ProgramArguments'], cwd=pin.source,
                            capture_output=True, text=True, check=False)
    assert failed.returncode == 78 and json.loads(failed.stdout)['liveness_signal'] == 'sent'
    startup_payload = json.loads(pin.signals.read_text())
    assert startup_payload['sha'] == newer_main
    startup_at = datetime.fromisoformat(startup_payload['observed_at'])
    assert startup_payload['after_sequence'] == pause_payload['sequence']
    assert startup_at >= pause_at
    verdict_at = startup_at + timedelta(seconds=1)
    now = max(pause_at, startup_at) + timedelta(seconds=2)
    writes = []
    run = subprocess.run
    monkeypatch.setattr(liveness.subprocess, 'run', lambda command, **_: writes.append(command))
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    monkeypatch.setattr(driver, 'load_candidate', lambda _: candidate)
    def admit(kind, payload, at):
        writes.clear()
        liveness.record_signal(kind, json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                               api=lambda _: {'status': 'identical'}, now=at)
        assert writes[0][2] == f'repos/{driver.REPOSITORY}/statuses/{payload["sha"]}'
        fields = dict(item.split('=', 1) for item in writes[0] if '=' in item)
        return {key: fields[key] for key in ('state', 'context', 'description')}
    paused = admit('heartbeat', pause_payload, now)
    startup = admit('heartbeat', startup_payload, now)
    class VerdictClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return verdict_at
    monkeypatch.setattr(driver, 'datetime', VerdictClock)
    driver.publish_dev_verdict(candidate, {'result': 'passed', 'channel': 'dev',
                                          'operation_id': candidate.operation_id('dev')})
    verdict = admit(*produced[-1], now)
    statuses = {SHA: [paused, verdict], newer_main: [startup], newest_main: []}
    parents = {newest_main: newer_main, newer_main: SHA, SHA: None}
    reads = []
    admitted_run = {**_build()[0], 'created_at': (pause_at - timedelta(hours=2)).isoformat(),
                    'completed_at': (pause_at - timedelta(hours=1)).isoformat()}
    def api(endpoint):
        reads.append(endpoint)
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': [admitted_run]}
        if '/statuses?' in endpoint:
            sha = endpoint.split('/commits/', 1)[1].split('/', 1)[0]
            page = int(endpoint.rsplit('page=', 1)[1])
            if sha == newer_main and page == 1:
                # A queued replay burst cannot establish completeness or hide
                # the ancestor. Equal write timestamps retain source freshness.
                return [{**startup, 'created_at': now.isoformat()} for _ in range(100)]
            if sha == newer_main and page == 2:
                return [{**startup, 'created_at': (now - timedelta(seconds=1)).isoformat()}]
            return statuses.get(sha, [])
        if '/git/commits/' in endpoint:
            sha = endpoint.rsplit('/', 1)[1]
            return {'sha': sha, 'parents': [{'sha': parents[sha]}] if parents[sha] else []}
        pytest.fail('unexpected liveness read: ' + endpoint)
    checked = liveness.check(driver.REPOSITORY, newest_main, api=api, now=now)
    assert not checked.ok
    assert checked.reason == 'startup_self_check_failed'
    assert any(endpoint.endswith('/git/commits/' + newer_main) for endpoint in reads)
    assert any(f'/commits/{newer_main}/statuses?per_page=100&page=2' in endpoint for endpoint in reads)
    # Repair the actual pin, then let the real poller allocate a later normal
    # observation after expiry. No admitted build or native operation follows.
    controller_file.write_bytes(original)
    healthy = run([*pin.config['ProgramArguments'], '--self-check'], cwd=pin.source,
                  capture_output=True, text=True, check=False)
    assert healthy.returncode == 0, healthy.stdout + healthy.stderr
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    assert driver.poll(pin.state, build=unexpected, current_main=lambda: newest_main,
                       heartbeat=driver.publish_heartbeat) == 0
    later_pause = admit(*produced[-1], now)
    statuses[newest_main] = [later_pause]
    assert liveness.check(driver.REPOSITORY, newest_main, api=api, now=now).reason == 'paused'
    # Preserve the existing pause-expiry semantics without requiring a new tick.
    assert liveness.check(driver.REPOSITORY, newest_main, api=api, now=until).ok
    monkeypatch.setattr(driver, '_utc_now', lambda: until)
    def no_build():
        raise driver.CandidateRefused('latest_build_not_ready')
    with pytest.raises(driver.CandidateRefused, match='latest_build_not_ready'):
        driver.poll(pin.state, build=no_build, deploy=unexpected, resume=unexpected,
                    current_main=lambda: newest_main, heartbeat=driver.publish_heartbeat)
    normal_kind, normal_payload = produced[-1]
    assert normal_payload['sha'] == newest_main and 'pause' not in normal_payload
    normal = admit(normal_kind, normal_payload, until)
    statuses[newest_main] = [normal]
    # An old startup replay remains on its actual older commit; the genuine
    # newer normal tick retires that diagnostic and the expired ancestor pause.
    assert liveness.check(driver.REPOSITORY, newest_main, api=api, now=until).ok


@pytest.mark.parametrize('pause_position', [99, 100])
def test_diagnostic_only_ancestry_preserves_exact_fail_closed_bound(pause_position):
    from scripts import dev_delivery_liveness as liveness
    now = datetime(2026, 10, 19, 18, tzinfo=timezone.utc)
    commits = [f'{number + 1:040x}' for number in range(102)]
    startup = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'failure',
               'description': f'observed_at={(now - timedelta(minutes=1)).isoformat()};after_sequence=9;startup=self_check_failed'}
    paused = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'failure',
              'description': f'observed_at={(now - timedelta(minutes=2)).isoformat()};seq=9;paused_issue=6224;until={(now + timedelta(hours=1)).isoformat()}'}
    visited = []
    def api(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': []}
        if '/statuses?' in endpoint:
            sha = endpoint.split('/commits/', 1)[1].split('/', 1)[0]
            visited.append(sha)
            return [paused if commits.index(sha) == pause_position else startup]
        sha = endpoint.rsplit('/', 1)[1]
        index = commits.index(sha)
        return {'sha': sha, 'parents': [{'sha': commits[index + 1]}]}
    if pause_position == 99:
        result = liveness.check(driver.REPOSITORY, commits[0], api=api, now=now)
        assert not result.ok and result.reason == 'startup_self_check_failed'
    else:
        with pytest.raises(liveness.LivenessRefused, match='heartbeat_ancestry_incomplete'):
            liveness.check(driver.REPOSITORY, commits[0], api=api, now=now)
    assert len(visited) == liveness.MAX_HEARTBEAT_COMMITS


@pytest.mark.parametrize('fault', ['timestamp', 'state', 'borrowed_sequence'])
def test_diagnostic_only_history_refuses_malformed_signal_before_ancestry(fault):
    from scripts import dev_delivery_liveness as liveness
    now = datetime(2026, 10, 19, 18, tzinfo=timezone.utc)
    description = f'observed_at={now.isoformat()};after_sequence=0;startup=self_check_failed'
    status = {'context': liveness.HEARTBEAT_CONTEXT, 'state': 'failure', 'description': description}
    if fault == 'timestamp':
        status['description'] = 'observed_at=invalid;after_sequence=0;startup=self_check_failed'
    elif fault == 'state':
        status['state'] = 'success'
    else:
        status['description'] = description.replace(';startup=', ';seq=1;startup=')
    def api(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': []}
        if '/statuses?' in endpoint:
            return [status]
        pytest.fail('malformed diagnostic reached ancestry lookup')
    with pytest.raises(liveness.LivenessRefused):
        liveness.check(driver.REPOSITORY, SHA, api=api, now=now)


@pytest.mark.parametrize('separate_commits', [False, True])
def test_startup_frontier_survives_clock_lag_and_fresh_verdicts(
    installed_controller_pin, monkeypatch, separate_commits,
):
    from scripts import dev_delivery_liveness as liveness
    pin = installed_controller_pin
    # Real poll allocation can precede a clock correction and a future-refused
    # signal. Startup must snapshot both persisted fields without changing them.
    floor = datetime.now(timezone.utc) + timedelta(minutes=4)
    monkeypatch.setattr(driver, '_utc_now', lambda: floor)
    produced = []
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, payload: produced.append((kind, payload)))
    def no_build():
        raise driver.CandidateRefused('latest_build_not_ready')
    with pytest.raises(driver.CandidateRefused, match='latest_build_not_ready'):
        driver.poll(pin.state, build=no_build, current_main=lambda: SHA, heartbeat=driver.publish_heartbeat)
    normal_payload = produced[-1][1]
    path = pin.state / 'postmerge-dev-test.json'
    before, inode = path.read_bytes(), path.stat().st_ino
    lock_inode = (pin.state / 'postmerge-dev-test.lock').stat().st_ino
    failed_sha, current_sha = ('b' * 40, 'c' * 40) if separate_commits else (SHA, SHA)
    pin.gh.write_text(pin.gh.read_text().replace(SHA, failed_sha))
    controller_file = pin.source / 'scripts/postmerge_dev_test.py'
    original = controller_file.read_bytes()
    controller_file.write_text("raise ModuleNotFoundError('private fixture input')\n")
    run = subprocess.run
    result = run(pin.config['ProgramArguments'], cwd=pin.source, capture_output=True, text=True)
    assert result.returncode == 78 and json.loads(result.stdout)['liveness_signal'] == 'sent'
    failure_payload = json.loads(pin.signals.read_text())
    assert path.read_bytes() == before and path.stat().st_ino == inode
    assert (pin.state / 'postmerge-dev-test.lock').stat().st_ino == lock_inode
    writes = []
    monkeypatch.setattr(liveness.subprocess, 'run', lambda command, **_: writes.append(command))
    def admit(kind, payload, at):
        writes.clear()
        liveness.record_signal(kind, json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                               api=lambda _: {'status': 'identical'}, now=at)
        fields = dict(item.split('=', 1) for item in writes[0] if '=' in item)
        return {**{key: fields[key] for key in ('state', 'context', 'description')}, 'created_at': at.isoformat()}
    with pytest.raises(liveness.LivenessRefused, match='signal_observation_stale_or_future'):
        admit('heartbeat', normal_payload, floor - timedelta(minutes=4))
    assert writes == []
    startup = admit('heartbeat', failure_payload, floor + timedelta(seconds=1))
    normal = admit('heartbeat', normal_payload, floor + timedelta(seconds=3))
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    monkeypatch.setattr(driver, 'load_candidate', lambda _: candidate)
    build = {**_build()[0], 'created_at': (floor - timedelta(hours=2)).isoformat(),
             'completed_at': (floor - timedelta(hours=1)).isoformat()}
    verdicts = []
    reads = []
    recovery_status = None
    def api(endpoint):
        reads.append(endpoint)
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': [build]}
        if '/statuses?' in endpoint:
            sha = endpoint.split('/commits/', 1)[1].split('/', 1)[0]
            if sha == current_sha and recovery_status is not None:
                return [recovery_status, *([] if separate_commits else [startup]), *verdicts]
            if sha == SHA:
                return [normal, *(verdicts or []), *([] if separate_commits else [startup])]
            return [startup] if sha == failed_sha else []
        if '/git/commits/' in endpoint:
            sha = endpoint.rsplit('/', 1)[1]
            return {'sha': sha, 'parents': [{'sha': failed_sha if sha == current_sha else SHA}]}
        pytest.fail('unexpected liveness read: ' + endpoint)
    now = floor + timedelta(seconds=4)
    for verdict_at in (None, floor, floor + timedelta(seconds=3)):
        if verdict_at is not None:
            class VerdictClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return verdict_at
            monkeypatch.setattr(driver, 'datetime', VerdictClock)
            driver.publish_dev_verdict(candidate, {'result': 'passed', 'channel': 'dev',
                                                  'operation_id': candidate.operation_id('dev')})
            verdicts[:] = [admit(*produced[-1], now)]
        checked = liveness.check(driver.REPOSITORY, current_sha, api=api, now=now)
        assert not checked.ok and checked.reason == 'startup_self_check_failed'
    assert failure_payload['after_sequence'] == normal_payload['sequence']
    assert datetime.fromisoformat(failure_payload['observed_at']) >= floor
    # The floor is never lowered merely to pass the existing writer window.
    with pytest.raises(liveness.LivenessRefused, match='signal_observation_stale_or_future'):
        admit('heartbeat', failure_payload, floor - timedelta(seconds=1))
    assert writes == []
    if separate_commits:
        assert any(endpoint.endswith('/git/commits/' + failed_sha) for endpoint in reads)
    # Repair, allocate a genuine later observation at the same source time,
    # then retain/replay the older failure after recovery on current main.
    controller_file.write_bytes(original)
    healthy = run([*pin.config['ProgramArguments'], '--self-check'], cwd=pin.source,
                  capture_output=True, text=True)
    assert healthy.returncode == 0, healthy.stdout + healthy.stderr
    with pytest.raises(driver.CandidateRefused, match='latest_build_not_ready'):
        driver.poll(pin.state, build=no_build, current_main=lambda: current_sha, heartbeat=driver.publish_heartbeat)
    recovered_payload = produced[-1][1]
    recovered = admit('heartbeat', recovered_payload, now)
    assert recovered_payload['sha'] == current_sha
    assert recovered_payload['sequence'] > failure_payload['after_sequence']
    assert recovered_payload['observed_at'] == failure_payload['observed_at']
    recovery_status = recovered
    assert liveness.check(driver.REPOSITORY, current_sha, api=api, now=now).ok


def _record_frontier_heartbeat(monkeypatch, payload, at):
    from scripts import dev_delivery_liveness as liveness
    writes = []
    with monkeypatch.context() as isolated:
        isolated.setattr(liveness.subprocess, 'run', lambda command, **_: writes.append(command))
        liveness.record_signal('heartbeat', json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                               api=lambda _: {'status': 'identical'}, now=at)
    fields = dict(item.split('=', 1) for item in writes[0] if '=' in item)
    return {**{key: fields[key] for key in ('state', 'context', 'description')}, 'created_at': at.isoformat()}


@pytest.mark.parametrize('frontier', [None, -1, True, 1.5, '1', 10**18])
def test_startup_frontier_wire_refuses_before_external_read(monkeypatch, frontier):
    from scripts import dev_delivery_liveness as liveness
    now = datetime.now(timezone.utc)
    payload = {'protocol': driver.LIVENESS_PROTOCOL, 'sha': SHA,
               'observed_at': now.isoformat(), 'startup': 'failed'}
    if frontier is not None:
        payload['after_sequence'] = frontier
    unexpected = lambda *_a, **_k: pytest.fail('invalid frontier reached GitHub')
    monkeypatch.setattr(liveness.subprocess, 'run', unexpected)
    with pytest.raises(liveness.LivenessRefused, match='signal_startup_refused'):
        liveness.record_signal('heartbeat', json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                               api=unexpected, now=now)
    payload.pop('startup')
    payload['after_sequence'] = 0
    with pytest.raises(liveness.LivenessRefused, match='signal_protocol_refused'):
        liveness.record_signal('heartbeat', json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                               api=unexpected, now=now)


@pytest.mark.parametrize('legacy', [False, True])
def test_startup_snapshot_preserves_pending_state_and_causal_recovery(tmp_path, monkeypatch, legacy):
    from scripts import dev_delivery_liveness as liveness
    from scripts import postmerge_controller as bootstrap
    assert driver.CandidateRefused is bootstrap.CandidateRefused
    now = datetime.now(timezone.utc)
    candidate = driver.Candidate(SHA, DIGEST, 123, 1, 456)
    with driver.checkpoint_lock(tmp_path):
        pass
    path = tmp_path / 'postmerge-dev-test.json'
    outcome = {'source_sha': SHA, 'image_digest': DIGEST, 'source_run_id': 123,
               'source_run_attempt': 1, 'artifact_id': 456, 'result': 'pending',
               'channel': 'dev', 'operation_id': candidate.operation_id('dev')}
    driver._save_outcome(path, candidate, outcome, last_green={'dev': 'd' * 40},
                         observation=None if legacy else {'sequence': 7, 'observed_at': now.isoformat()})
    before, inode = path.read_bytes(), path.stat().st_ino
    lock = tmp_path / 'postmerge-dev-test.lock'
    lock_inode = lock.stat().st_ino
    captured = []
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now + timedelta(minutes=1)
    monkeypatch.setattr(bootstrap, 'datetime', Clock)
    def transport(command, **_):
        if command[1] == 'api':
            return SimpleNamespace(stdout=json.dumps({'object': {'sha': SHA}}))
        captured.append(json.loads(next(arg[8:] for arg in command if arg.startswith('payload='))))
        return SimpleNamespace()
    monkeypatch.setattr(bootstrap.subprocess, 'run', transport)
    bootstrap.report_startup_failure(tmp_path)
    failure = captured[-1]
    assert failure['after_sequence'] == (0 if legacy else 7)
    assert path.read_bytes() == before and path.stat().st_ino == inode and lock.stat().st_ino == lock_inode
    at = now + timedelta(minutes=2)
    failed = _record_frontier_heartbeat(monkeypatch, failure, at)
    legacy_normal = _record_frontier_heartbeat(monkeypatch, {
        'protocol': driver.LIVENESS_PROTOCOL, 'sha': SHA, 'observed_at': at.isoformat()}, at)
    def check(history):
        return liveness.check(driver.REPOSITORY, SHA, api=lambda endpoint: (
            {'workflow_runs': []} if '/actions/workflows/' in endpoint else history), now=at)
    assert check([legacy_normal, failed]).reason == 'startup_self_check_failed'
    # A real poll adopts legacy state and reuses the native operation identity.
    # It emits a later heartbeat before the unchanged pending native result.
    emitted = []
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, payload: emitted.append(payload))
    with pytest.raises(driver.CandidateRefused, match='native_terminal_evidence_refused'):
        driver.poll(tmp_path, resume=lambda channel, item: {'terminal_result': 'unknown'},
                    current_main=lambda: SHA, heartbeat=driver.publish_heartbeat)
    recovered = _record_frontier_heartbeat(monkeypatch, emitted[-1], at)
    assert emitted[-1]['sequence'] > failure['after_sequence']
    assert datetime.fromisoformat(emitted[-1]['observed_at']) < datetime.fromisoformat(failure['observed_at'])
    assert check([failed, recovered, failed]).ok
    retained = json.loads(path.read_text())
    assert retained['candidate'] == asdict(candidate) and retained['last_green'] == {'dev': 'd' * 40}
    assert retained['outcome']['operation_id'] == outcome['operation_id']
    bootstrap.report_startup_failure(tmp_path)
    next_failed = _record_frontier_heartbeat(monkeypatch, captured[-1], at)
    assert captured[-1]['after_sequence'] == emitted[-1]['sequence']
    assert check([failed, recovered, next_failed]).reason == 'startup_self_check_failed'


@pytest.mark.parametrize('fault', ['ref_failure', 'dispatch_failure', 'lost_reply', 'writer_after_snapshot'])
def test_startup_snapshot_crash_and_lock_linearization(tmp_path, monkeypatch, fault):
    from scripts import dev_delivery_liveness as liveness
    from scripts import postmerge_controller as bootstrap
    now = datetime.now(timezone.utc)
    with driver.checkpoint_lock(tmp_path):
        pass
    path = tmp_path / 'postmerge-dev-test.json'
    driver._atomic_checkpoint(path, {'observation': {'sequence': 4, 'observed_at': now.isoformat()}})
    before, inode = path.read_bytes(), path.stat().st_ino
    lock_inode = (tmp_path / 'postmerge-dev-test.lock').stat().st_ino
    emitted, captured = [], []
    current_main = 'b' * 40
    monkeypatch.setattr(driver, '_utc_now', lambda: now)
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, payload: emitted.append(payload))
    def no_build():
        raise driver.CandidateRefused('latest_build_not_ready')
    def transport(command, **_):
        if command[1] == 'api':
            if fault == 'ref_failure':
                raise subprocess.TimeoutExpired(command, 60)
            if fault == 'writer_after_snapshot':
                # Deterministic writer-after-snapshot interleaving. The real
                # lock must have been released before the first transport call.
                with pytest.raises(driver.CandidateRefused, match='latest_build_not_ready'):
                    driver.poll(tmp_path, build=no_build, current_main=lambda: current_main, heartbeat=driver.publish_heartbeat)
            return SimpleNamespace(stdout=json.dumps({'object': {'sha': current_main}}))
        captured.append(json.loads(next(arg[8:] for arg in command if arg.startswith('payload='))))
        if fault in {'dispatch_failure', 'lost_reply'}:
            raise subprocess.TimeoutExpired(command, 60)
        return SimpleNamespace()
    monkeypatch.setattr(bootstrap.subprocess, 'run', transport)
    if fault == 'writer_after_snapshot':
        bootstrap.report_startup_failure(tmp_path)
        assert captured[-1]['after_sequence'] == 4 and emitted[-1]['sequence'] == 5
        assert captured[-1]['sha'] == emitted[-1]['sha'] == current_main
        at = datetime.now(timezone.utc) + timedelta(seconds=1)
        failed = _record_frontier_heartbeat(monkeypatch, captured[-1], at)
        recovered = _record_frontier_heartbeat(monkeypatch, emitted[-1], at)
        checked = liveness.check(driver.REPOSITORY, current_main, api=lambda endpoint: (
            {'workflow_runs': []} if '/actions/workflows/' in endpoint else [failed, recovered, failed]), now=at)
        assert checked.ok
    else:
        with pytest.raises(subprocess.TimeoutExpired):
            bootstrap.report_startup_failure(tmp_path)
        assert path.read_bytes() == before and path.stat().st_ino == inode
    assert (tmp_path / 'postmerge-dev-test.lock').stat().st_ino == lock_inode


def test_installed_startup_refuses_bad_state_without_creating_authority(installed_controller_pin):
    pin = installed_controller_pin
    path, lock = pin.state / 'postmerge-dev-test.json', pin.state / 'postmerge-dev-test.lock'
    checkpoint, checkpoint_inode = path.read_bytes(), path.stat().st_ino
    lock_inode = lock.stat().st_ino
    # Pure checks run while the parent installer lock is held, even with no
    # checkpoint. They must neither snapshot state nor dispatch a report.
    saved = pin.state / 'checkpoint-saved'
    with driver.checkpoint_lock(pin.state):
        path.rename(saved)
        checked = subprocess.run([*pin.config['ProgramArguments'], '--self-check'],
                                 capture_output=True, text=True)
        saved.rename(path)
    assert checked.returncode == 0 and not pin.signals.exists()
    controller = pin.source / 'scripts/postmerge_dev_test.py'
    controller.write_text("raise ModuleNotFoundError('private state must not leak')\n")
    calls = pin.state / 'gh-calls'
    pin.gh.write_text(pin.gh.read_text().replace('#!/bin/sh\n', '#!/bin/sh\nprintf call >> "' + str(calls) + '"\n'))
    for fault in ('missing_directory', 'missing_lock', 'missing_checkpoint', 'directory_mode', 'lock_mode', 'checkpoint_mode',
                  'checkpoint_symlink', 'checkpoint_hardlink', 'checkpoint_type', 'json', 'object',
                  'size', 'null_observation', 'bool_sequence', 'overflow_sequence', 'invalid_time', 'busy'):
        extra = pin.state / 'extra-link'
        saved_lock = pin.state / 'lock-saved'
        if fault == 'missing_lock':
            lock.rename(saved_lock)
        elif fault in {'missing_checkpoint', 'checkpoint_symlink', 'checkpoint_type'}:
            path.rename(saved)
            if fault == 'checkpoint_symlink':
                path.symlink_to(saved)
            elif fault == 'checkpoint_type':
                path.mkdir()
        elif fault == 'checkpoint_hardlink':
            os.link(path, extra)
        elif fault == 'directory_mode':
            pin.state.chmod(0o755)
        elif fault == 'lock_mode':
            lock.chmod(0o644)
        elif fault == 'checkpoint_mode':
            path.chmod(0o644)
        elif fault in {'json', 'object', 'size'}:
            path.write_text({'json': '{private', 'object': '[]', 'size': ' ' * 65537}[fault])
        elif fault in {'null_observation', 'bool_sequence', 'overflow_sequence', 'invalid_time'}:
            data = json.loads(checkpoint)
            data['observation'] = None if fault == 'null_observation' else {
                'sequence': True if fault == 'bool_sequence' else 10**18 if fault == 'overflow_sequence' else 1,
                'observed_at': 'private invalid time' if fault == 'invalid_time' else data['observation']['observed_at']}
            path.write_text(json.dumps(data))
        if fault == 'busy':
            with driver.checkpoint_lock(pin.state):
                failed = subprocess.run(pin.config['ProgramArguments'], capture_output=True, text=True)
        else:
            command = pin.config['ProgramArguments']
            if fault == 'missing_directory':
                command = [*command, '--state-directory', str(pin.state / 'absent-state')]
            failed = subprocess.run(command, capture_output=True, text=True)
        assert failed.returncode == 78 and json.loads(failed.stdout)['liveness_signal'] == 'failed', fault
        assert not calls.exists() and not pin.signals.exists(), fault
        assert 'private' not in failed.stdout + failed.stderr, fault
        if fault == 'missing_lock':
            assert not lock.exists()
            saved_lock.rename(lock)
        elif fault in {'missing_checkpoint', 'checkpoint_symlink', 'checkpoint_type'}:
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
            assert not path.exists()
            saved.rename(path)
        else:
            extra.unlink(missing_ok=True)
            pin.state.chmod(0o700)
            lock.chmod(0o600)
            path.chmod(0o600)
            path.write_bytes(checkpoint)
        assert path.read_bytes() == checkpoint and path.stat().st_ino == checkpoint_inode, fault
        assert lock.stat().st_ino == lock_inode, fault


def test_startup_timestamp_floor_preserves_queued_failure_pagination(tmp_path, monkeypatch):
    from scripts import dev_delivery_liveness as liveness
    from scripts import postmerge_controller as bootstrap
    floor = datetime(2026, 10, 19, 17, 58, tzinfo=timezone.utc)
    emitted = []
    monkeypatch.setattr(driver, '_utc_now', lambda: floor)
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, payload: emitted.append(payload))
    def no_build():
        raise driver.CandidateRefused('latest_build_not_ready')
    with pytest.raises(driver.CandidateRefused, match='latest_build_not_ready'):
        driver.poll(tmp_path, build=no_build, current_main=lambda: SHA, heartbeat=driver.publish_heartbeat)
    normal_payload = emitted[-1]
    # A host-ahead normal signal initially refuses. Its unchanged owner rerun
    # can be admitted later, so its source time alone is not an arrival clock.
    with pytest.raises(liveness.LivenessRefused, match='signal_observation_stale_or_future'):
        _record_frontier_heartbeat(monkeypatch, normal_payload, floor - timedelta(minutes=4))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return floor - timedelta(minutes=3)
    monkeypatch.setattr(bootstrap, 'datetime', Clock)
    captured = []
    def transport(command, **_):
        if command[1] == 'api':
            return SimpleNamespace(stdout=json.dumps({'object': {'sha': SHA}}))
        captured.append(json.loads(next(arg[8:] for arg in command if arg.startswith('payload='))))
        return SimpleNamespace()
    monkeypatch.setattr(bootstrap.subprocess, 'run', transport)
    bootstrap.report_startup_failure(tmp_path)
    failure_payload = captured[-1]
    assert failure_payload['observed_at'] == floor.isoformat()
    with pytest.raises(liveness.LivenessRefused, match='signal_observation_stale_or_future'):
        _record_frontier_heartbeat(monkeypatch, failure_payload, floor - timedelta(minutes=2))
    normal = _record_frontier_heartbeat(monkeypatch, normal_payload, floor + timedelta(minutes=3))
    failed = _record_frontier_heartbeat(monkeypatch, failure_payload, floor + timedelta(minutes=1))
    pages = {1: [normal] + [{'context': 'unrelated', 'created_at': (floor + timedelta(minutes=2)).isoformat()}] * 99,
             2: [failed]}
    reads = []
    def api(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': []}
        page = int(endpoint.rsplit('page=', 1)[1])
        reads.append(page)
        return pages[page]
    checked = liveness.check(driver.REPOSITORY, SHA, api=api, now=floor + timedelta(minutes=4))
    assert not checked.ok and checked.reason == 'startup_self_check_failed'
    assert reads == [1, 2]


@pytest.mark.parametrize('include_activity', [False, True])
@pytest.mark.parametrize('later_pause', [False, True])
def test_startup_diagnostic_is_not_a_pagination_clock_witness(tmp_path, monkeypatch, include_activity, later_pause):
    from scripts import dev_delivery_liveness as liveness
    from scripts import postmerge_controller as bootstrap
    floor = datetime(2026, 10, 19, 18, tzinfo=timezone.utc)
    emitted, captured = [], []
    monkeypatch.setattr(driver, '_utc_now', lambda: floor)
    monkeypatch.setattr(driver, '_dispatch_liveness_signal', lambda kind, payload: emitted.append(payload))
    def no_build():
        raise driver.CandidateRefused('latest_build_not_ready')
    with pytest.raises(driver.CandidateRefused, match='latest_build_not_ready'):
        driver.poll(tmp_path, build=no_build, current_main=lambda: SHA, heartbeat=driver.publish_heartbeat)
    older = _record_frontier_heartbeat(monkeypatch, emitted[-1], floor + timedelta(minutes=2))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return floor + timedelta(minutes=30)
    monkeypatch.setattr(bootstrap, 'datetime', Clock)
    def transport(command, **_):
        if command[1] == 'api':
            return SimpleNamespace(stdout=json.dumps({'object': {'sha': SHA}}))
        captured.append(json.loads(next(arg[8:] for arg in command if arg.startswith('payload='))))
        return SimpleNamespace()
    monkeypatch.setattr(bootstrap.subprocess, 'run', transport)
    bootstrap.report_startup_failure(tmp_path)
    failed = _record_frontier_heartbeat(monkeypatch, captured[-1], floor + timedelta(minutes=31))
    if later_pause:
        driver.engage_pause(tmp_path, 6224, (floor + timedelta(hours=1)).isoformat())
        assert driver.poll(tmp_path, build=no_build, current_main=lambda: SHA, heartbeat=driver.publish_heartbeat) == 0
    else:
        with pytest.raises(driver.CandidateRefused, match='latest_build_not_ready'):
            driver.poll(tmp_path, build=no_build, current_main=lambda: SHA, heartbeat=driver.publish_heartbeat)
    later = _record_frontier_heartbeat(monkeypatch, emitted[-1], floor + timedelta(minutes=1))
    noise = {'context': 'unrelated', 'created_at': (floor + timedelta(minutes=2)).isoformat()}
    pages = {1: [failed] + [noise] * (98 if include_activity else 99) + ([older] if include_activity else []),
             2: [later]}
    reads = []
    def api(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': []}
        page = int(endpoint.rsplit('page=', 1)[1])
        reads.append(page)
        return pages[page]
    checked = liveness.check(driver.REPOSITORY, SHA, api=api, now=floor + timedelta(minutes=40))
    assert checked.reason == ('paused' if later_pause else 'no_admitted_build')
    assert checked.ok is not later_pause and reads == [1, 2]


@pytest.mark.parametrize('last_page_size', [99, 100])
def test_startup_only_status_history_preserves_exact_page_bound(monkeypatch, last_page_size):
    from scripts import dev_delivery_liveness as liveness
    now = datetime.now(timezone.utc)
    failed = _record_frontier_heartbeat(monkeypatch, {
        'protocol': driver.LIVENESS_PROTOCOL, 'sha': SHA, 'observed_at': now.isoformat(),
        'startup': 'failed', 'after_sequence': 7}, now)
    pages = []
    def api(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': []}
        if '/git/commits/' in endpoint:
            return {'sha': SHA, 'parents': []}
        page = int(endpoint.rsplit('page=', 1)[1])
        pages.append(page)
        return [failed] * (last_page_size if page == 20 else 100)
    if last_page_size == 100:
        with pytest.raises(liveness.LivenessRefused, match='statuses_incomplete'):
            liveness.check(driver.REPOSITORY, SHA, api=api, now=now)
    else:
        checked = liveness.check(driver.REPOSITORY, SHA, api=api, now=now)
        assert not checked.ok and checked.reason == 'startup_self_check_failed'
    assert pages == list(range(1, 21))


@pytest.mark.parametrize('marker', ['-1', '01', 'true', '1000000000000000000', ''])
def test_startup_description_refuses_malformed_frontier_before_ancestry(monkeypatch, marker):
    from scripts import dev_delivery_liveness as liveness
    now = datetime.now(timezone.utc)
    status = _record_frontier_heartbeat(monkeypatch, {
        'protocol': driver.LIVENESS_PROTOCOL, 'sha': SHA, 'observed_at': now.isoformat(),
        'startup': 'failed', 'after_sequence': 0}, now)
    status['description'] = status['description'].replace('after_sequence=0', 'after_sequence=' + marker)
    def api(endpoint):
        if '/actions/workflows/' in endpoint:
            return {'workflow_runs': []}
        if '/statuses?' in endpoint:
            return [status]
        pytest.fail('malformed frontier reached ancestry')
    with pytest.raises(liveness.LivenessRefused, match='heartbeat_observation_refused'):
        liveness.check(driver.REPOSITORY, SHA, api=api, now=now)


def test_healthy_installed_bootstrap_forwards_authoritative_state(installed_controller_pin):
    pin = installed_controller_pin
    path = pin.state / 'postmerge-dev-test.json'
    before = json.loads(path.read_text())
    # Actual gh transport returns no successful candidate; actual poll still
    # persists and publishes its next normal observation, with no native work.
    pin.gh.write_text(pin.gh.read_text().replace('if [ "$1" = api ]; then\n',
        'if [ "$1" = api ]; then\ncase "$2" in *actions/workflows*) printf \'%s\\n\' \'{"workflow_runs":[]}\'; exit 0;; '
        '*commits/main*) printf \'%s\\n\' \'{"sha":"' + SHA + '"}\'; exit 0;; esac\n'))
    result = subprocess.run(pin.config['ProgramArguments'], cwd=pin.source,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    after = json.loads(path.read_text())
    payload = json.loads(pin.signals.read_text())
    assert payload['sequence'] == after['observation']['sequence'] == before['observation']['sequence'] + 1
    assert 'after_sequence' not in payload and 'startup' not in payload


class _RefGithub(_ChannelGithub):
    """Fake GitHub transport; real producer argv, CLI consumers and loaders."""

    def __init__(self, monkeypatch, directory):
        super().__init__()
        self.monkeypatch, self.directory = monkeypatch, directory
        self.refs, self.uploads, self.archives, self.own_runs = {}, {}, {}, {}
        self.own_attempts = {}
        self.queue_only, self.pending, self.next_run_id = False, [], 1000
        self.ref_results = []
        self.fail_after_write = False
        self.before_write = None
        self.artifact_fault = None
        self.image_attempts = {}

    def _run(self, run_id=900, candidate=None):
        sha = self.candidates[-1].sha if candidate is None else candidate.sha
        return {'id': run_id, 'run_attempt': 1, 'event': 'workflow_dispatch', 'head_branch': 'main',
                'head_sha': sha, 'path': '.github/workflows/postmerge-channel-bug.yml',
                'repository': {'full_name': driver.REPOSITORY},
                'head_repository': {'full_name': driver.REPOSITORY}, 'actor': {'login': 'RasmusTho'},
                'status': 'in_progress', 'conclusion': None}

    def _image(self, candidate):
        _, proof = _build()
        attempt = self.image_attempts.get(candidate.run_id, candidate.run_attempt)
        proof.update(candidate_sha=candidate.sha, image=driver.IMAGE_REPOSITORY + ':' + candidate.sha,
                     image_ref=driver.IMAGE_REPOSITORY + '@' + candidate.digest,
                     image_index_digest=candidate.digest, run_id=candidate.run_id, run_attempt=attempt)
        metadata, raw = _artifact(proof)
        metadata.update(id=candidate.artifact_id,
                        name=f'app-image-tts-engine-proof-{candidate.sha}-attempt-{attempt}')
        if self.artifact_fault == 'digest':
            metadata['digest'] = 'sha256:' + '0' * 64
        self.archives[candidate.artifact_id] = raw
        return metadata

    def api(self, method, path, data=None):
        prefix = f'repos/{driver.REPOSITORY}'
        if '/git/matching-refs/heads/' in path:
            self.reads.append(path)
            channel = path.rsplit('/', 1)[-1]
            return ([{'ref': 'refs/heads/' + channel, 'object': {'type': 'commit', 'sha': self.refs[channel]}}]
                    if channel in self.refs else [])
        if '/git/refs' in path:
            if self.before_write is not None:
                callback, self.before_write = self.before_write, None
                callback()
            channel = data['ref'].rsplit('/', 1)[-1] if method == 'POST' else path.rsplit('/', 1)[-1]
            assert channel in {'dev', 'test'}
            if method == 'POST':
                if channel in self.refs:
                    raise channel_bug.AlertRefused('github_request_failed')
            else:
                assert data['force'] is False
                if self.api('GET', prefix + f'/compare/{self.refs[channel]}...{data["sha"]}')['status'] != 'ahead':
                    raise channel_bug.AlertRefused('github_request_failed')
            self.effects.append((method, path, data))
            self.refs[channel] = data['sha']
            if self.fail_after_write:
                self.fail_after_write = False
                raise channel_bug.AlertRefused('github_request_failed')
            return {'ref': 'refs/heads/' + channel, 'object': {'type': 'commit', 'sha': data['sha']}}
        if path == prefix + '/issues?state=open&creator=RasmusTho&per_page=100&page=1':
            self.reads.append(path)
            return [row for row in self.issues if row.get('state') == 'open'
                    and row.get('user', {}).get('login') == 'RasmusTho']
        if path.startswith(prefix + '/issues/') and '/comments' not in path and method == 'GET':
            self.reads.append(path)
            return next(row for row in self.issues if row['number'] == int(path.rsplit('/', 1)[-1]))
        if '/actions/runs/' in path:
            parts = path.split('/actions/runs/')[1].split('/')
            run_id = int(parts[0])
            if parts[1:] == ['artifacts?per_page=100']:
                self.reads.append(path)
                rows = self.uploads.get(run_id)
                if rows is None:
                    candidate = next(c for c in self.candidates if c.run_id == run_id)
                    rows = [self._image(candidate)]
                return {'total_count': len(rows), 'artifacts': rows}
            if parts[1:] == ['jobs?filter=all&per_page=100']:
                self.reads.append(path)
                candidate = next(c for c in self.candidates if c.run_id == run_id)
                attempt = self.image_attempts.get(run_id, candidate.run_attempt)
                jobs = [{'name': driver.BUILD_JOB, 'run_id': run_id, 'run_attempt': attempt,
                         'status': 'completed', 'conclusion': 'success'}]
                # A later failed build must not invalidate a retained successful attempt.
                jobs.append({**jobs[0], 'run_attempt': candidate.run_attempt + 1, 'conclusion': 'failure'})
                return {'total_count': len(jobs), 'jobs': jobs}
            if run_id == 900 or run_id in self.own_runs:
                self.reads.append(path)
                if len(parts) == 3:
                    prior = self.own_attempts.get((run_id, int(parts[2])))
                    if prior is not None:
                        return prior
                return self.own_runs.get(run_id, self._run())
        return super().api(method, path, data)

    def archive(self, path):
        self.reads.append(path)
        return self.archives[int(path.split('/artifacts/')[1].split('/')[0])]

    def advance(self, evidence, **overrides):
        options = {'channel': evidence['channel'], 'event': 'workflow_dispatch', 'ref': 'refs/heads/main',
                   'repository': driver.REPOSITORY, 'actor': 'RasmusTho', 'run_id': 900, 'run_attempt': 1,
                   'workflow_sha': self.candidates[-1].sha, 'api': self.api, 'archive': self.archive}
        return channel_bug.advance_channel_ref(evidence, **{**options, **overrides})

    def transport(self, argv, **kwargs):
        assert argv[:8] == ['gh', 'workflow', 'run', 'postmerge-channel-bug.yml', '--repo',
                            driver.REPOSITORY, '--ref', 'main']
        fields = dict(argv[i + 1].split('=', 1) for i, arg in enumerate(argv) if arg == '-f')
        self.deliveries.append(json.loads(fields['evidence']))
        run_id = self.next_run_id
        self.next_run_id += 1
        if self.queue_only:
            self.pending.append((fields, run_id))
        else:
            self.consume(fields, run_id)
        # Dispatch acceptance precedes asynchronous Actions consumption.
        return SimpleNamespace(returncode=0)

    def consume(self, fields, run_id, attempt=1):
        evidence = json.loads(fields['evidence'])
        row = self._run(run_id)
        row['run_attempt'] = attempt
        row['display_title'] = (f"channel-bug/{evidence['channel']}/{evidence['verdict']}/"
                                f"{evidence['candidate']['sha']}/{evidence['candidate']['run_id']}/"
                                f"{evidence['candidate']['run_attempt']}/{evidence['receipt_fingerprint']}")
        self.own_runs[run_id] = row
        workflow = yaml.safe_load((ROOT / '.github/workflows/postmerge-channel-bug.yml').read_text())
        job = workflow['jobs']['record-channel-ref']
        run_directory = self.directory / f'run-{run_id}-{attempt}'
        run_directory.mkdir()
        receipt_file = run_directory / job['steps'][2]['with']['path']

        def arguments(command):
            tokens = shlex.split(command)
            assert tokens[:2] == ['python3', 'scripts/postmerge_channel_bug.py']
            return [token.replace('$CHANNEL', fields['channel']).replace('$EVIDENCE', fields['evidence'])
                    for token in tokens[1:]]

        with self.monkeypatch.context() as patch:
            patch.setattr(channel_bug, '_api', self.api)
            patch.setattr(channel_bug, '_github', self.archive)
            for key, value in {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
                               'GITHUB_REPOSITORY': driver.REPOSITORY, 'GITHUB_RUN_ID': str(run_id),
                               'GITHUB_RUN_ATTEMPT': str(attempt), 'GITHUB_SHA': row['head_sha'], 'GITHUB_ACTOR': 'RasmusTho'}.items():
                patch.setenv(key, value)
            patch.chdir(run_directory)
            patch.setattr(sys, 'argv', arguments(workflow['jobs']['reconcile']['steps'][1]['run']))
            status = channel_bug.main()
            if status == 0 and evidence['verdict'] == 'passed':
                patch.setattr(sys, 'argv', arguments(job['steps'][1]['run']))
                status = channel_bug.main()
        if receipt_file.exists():
            content = io.BytesIO()
            with ZipFile(content, 'w') as zipped:
                zipped.writestr('channel-verdict.json', receipt_file.read_bytes())
            raw = content.getvalue()
            artifact_id = 5000 + 100 * run_id + attempt
            artifact_name = job['steps'][2]['with']['name']
            for expression, value in {'inputs.channel': evidence['channel'],
                                       'fromJSON(inputs.evidence).candidate.run_id': evidence['candidate']['run_id'],
                                       'fromJSON(inputs.evidence).candidate.run_attempt': evidence['candidate']['run_attempt'],
                                       'github.run_attempt': attempt}.items():
                artifact_name = artifact_name.replace('${{ ' + expression + ' }}', str(value))
            assert '${{' not in artifact_name
            self.uploads.setdefault(run_id, []).extend([{'id': artifact_id, 'expired': False, 'size_in_bytes': len(raw),
                                     'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(),
                                     'name': artifact_name}])
            self.archives[artifact_id] = raw
        else:
            self.uploads.setdefault(run_id, [])
        row.update(status='completed', conclusion='success' if status == 0 else 'failure')
        self.runs[:] = [item for item in self.runs if item['id'] != run_id]
        self.runs.append(row)
        self.own_attempts[(run_id, attempt)] = dict(row)
        self.ref_results.append(status)
        return status


def _ref_evidence(candidate, **kwargs):
    evidence = _channel_evidence(candidate, verdict='passed', **kwargs)
    if evidence['channel'] == 'dev':
        evidence['gate'] = 'heavy_acceptance'
        evidence['receipt']['heavy_acceptance'] = dict(HEAVY_PASSED)
        evidence['receipt_fingerprint'] = driver.channel_verdict_fingerprint(evidence)
    return evidence


def _poll_ref_channel(directory, candidate, **kwargs):
    # Real timer ticks first finish any retained prior candidate's reporting.
    result = _poll_channel(directory, candidate, **kwargs)
    if json.loads((directory / 'postmerge-dev-test.json').read_text())['candidate'] != asdict(candidate):
        result = _poll_channel(directory, candidate, **kwargs)
    return result


@pytest.fixture
def ref_github(monkeypatch, tmp_path):
    github = _RefGithub(monkeypatch, tmp_path)
    monkeypatch.setattr(driver, 'dispatch_channel_verdict', REAL_CHANNEL_DISPATCH)
    monkeypatch.setattr(driver.subprocess, 'run', github.transport)
    return github


def test_channel_refs_advance_only_on_green_verdicts(tmp_path, ref_github):
    github = ref_github
    first = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_ref_channel(tmp_path, first) == 0
    assert github.refs == {'dev': SHA, 'test': SHA}
    assert github.ref_results == [0, 0]
    red = github.add(replace(first, sha='c' * 40, run_id=124, artifact_id=457))
    assert _poll_ref_channel(tmp_path, red, red='dev') == 78
    assert github.refs == {'dev': SHA, 'test': SHA}
    dev_green = github.add(replace(first, sha='d' * 40, run_id=125, artifact_id=458))
    assert _poll_ref_channel(tmp_path, dev_green, red='test') == 78
    assert github.refs == {'dev': dev_green.sha, 'test': SHA}
    green = github.add(replace(first, sha='e' * 40, run_id=126, artifact_id=459))
    assert _poll_ref_channel(tmp_path, green) == 0
    assert github.refs == {'dev': green.sha, 'test': green.sha}
    ref_writes = [row for row in github.effects if '/git/refs' in row[1]]
    assert len(ref_writes) == 5
    assert all(row[2].get('force') is False for row in ref_writes if row[0] == 'PATCH')
    assert all('/main' not in row[1] and row[2].get('ref') != 'refs/heads/main' for row in ref_writes)


def _hold_issue(sha, number=6226):
    return {'number': number, 'state': 'open', 'user': {'login': 'RasmusTho', 'type': 'User'},
            'author_association': 'OWNER', 'labels': [],
            'body': channel_bug.HOLD_MARKER + '\n```json\n' + json.dumps({'sha': sha}) + '\n```\nTechnical hold.'}


def test_dev_hold_pins_ref_and_records_candidates(tmp_path, ref_github):
    github = ref_github
    first = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_ref_channel(tmp_path, first) == 0
    hold = _hold_issue(SHA)
    github.issues.append(hold)
    later = github.add(replace(first, sha='c' * 40, run_id=124, artifact_id=457))
    assert _poll_ref_channel(tmp_path, later) == 0
    stored = json.loads((tmp_path / 'postmerge-dev-test.json').read_text())
    assert stored['candidate'] == asdict(later) and stored['last_green'] == {'dev': later.sha, 'test': later.sha}
    assert github.refs == {'dev': SHA, 'test': later.sha}
    assert all(row['conclusion'] == 'success' for row in github.runs)
    held = github.advance(_ref_evidence(later))
    assert held == {'channel_ref': 'held', 'channel': 'dev', 'sha': SHA,
                    'hold_issue': f'https://github.com/{driver.REPOSITORY}/issues/6226'}
    hold['state'] = 'closed'
    assert github.advance(_ref_evidence(later))['channel_ref'] == 'advanced'
    assert github.refs['dev'] == later.sha


@pytest.mark.parametrize('fault', ['missing_dev', 'red_dev', 'foreign_digest', 'missing_artifact',
                                  'corrupt_artifact', 'foreign_receipt', 'failed_attempt', 'expired_artifact', 'native_only_dev'])
def test_test_ref_requires_exact_successful_dev_receipt(tmp_path, ref_github, fault):
    github = ref_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    if fault not in {'missing_dev', 'red_dev'}:
        assert _poll_ref_channel(tmp_path, candidate) == 0
        github.refs.pop('test')
        row = github.runs[0]
        artifact = github.uploads[row['id']][0]
        if fault == 'foreign_digest':
            candidate = replace(candidate, digest='sha256:' + 'c' * 64)
        elif fault == 'missing_artifact':
            github.uploads[row['id']] = []
        elif fault == 'corrupt_artifact':
            github.archives[artifact['id']] += b'drift'
        elif fault == 'expired_artifact':
            artifact['expired'] = True
        elif fault == 'foreign_receipt':
            artifact['name'] = artifact['name'].replace('-123-', '-999-')
        elif fault == 'failed_attempt':
            row['conclusion'] = 'failure'
        elif fault == 'native_only_dev':
            native = _channel_evidence(candidate, verdict='passed')
            raw = io.BytesIO()
            with ZipFile(raw, 'w') as zipped:
                zipped.writestr('channel-verdict.json', json.dumps(native))
            github.archives[artifact['id']] = raw.getvalue()
            artifact['digest'] = 'sha256:' + hashlib.sha256(raw.getvalue()).hexdigest()
            artifact['size_in_bytes'] = len(raw.getvalue())
            row['display_title'] = row['display_title'].rsplit('/', 1)[0] + '/' + native['receipt_fingerprint']
            github.own_attempts[(row['id'], 1)]['display_title'] = row['display_title']
    elif fault == 'red_dev':
        assert _poll_ref_channel(tmp_path, candidate, red='dev') == 78
    before = list(github.effects)
    with pytest.raises(channel_bug.AlertRefused):
        github.advance(_ref_evidence(candidate, channel='test'))
    assert github.effects == before and 'test' not in github.refs


@pytest.mark.parametrize('fault', ['actor', 'ref', 'repository', 'workflow_sha', 'own_run', 'artifact',
                                  'candidate_identity', 'receipt', 'channel', 'stale', 'diverged'])
def test_ref_authority_and_stale_requests_have_no_writes(tmp_path, ref_github, fault):
    github = ref_github
    previous = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    evidence, options = _ref_evidence(candidate), {}
    if fault in {'actor', 'ref', 'repository', 'workflow_sha'}:
        options[fault] = {'actor': 'outsider', 'ref': 'refs/heads/feature', 'repository': 'foreign/repo',
                          'workflow_sha': 'bad'}[fault]
    elif fault == 'own_run':
        github.own_runs[900] = {**github._run(), 'path': '.github/workflows/foreign.yml'}
    elif fault == 'artifact':
        github.artifact_fault = 'digest'
    elif fault == 'candidate_identity':
        evidence = _ref_evidence(replace(candidate, artifact_id=789))
    elif fault == 'receipt':
        evidence['receipt']['operation_id'] = previous.operation_id('dev')
    elif fault == 'channel':
        options['channel'] = 'main'
    elif fault == 'stale':
        github.refs['dev'] = candidate.sha
        evidence = _ref_evidence(previous)
    elif fault == 'diverged':
        github.refs['dev'] = previous.sha
        options['api'] = lambda method, path, data=None: ({'status': 'diverged'} if path.endswith(
            f'{previous.sha}...{candidate.sha}') else github.api(method, path, data))
    with pytest.raises(channel_bug.AlertRefused):
        github.advance(evidence, **options)
    assert not github.effects


@pytest.mark.parametrize('fault', ['pin_mismatch', 'malformed', 'ambiguous', 'unavailable', 'bootstrap'])
def test_dev_hold_activation_refuses_unknown_or_mismatched_state(ref_github, fault):
    github = ref_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.refs['dev'] = SHA
    issue = _hold_issue(SHA)
    github.issues.append(issue)
    if fault == 'pin_mismatch':
        issue['body'] = issue['body'].replace(SHA, 'c' * 40)
    elif fault == 'malformed':
        issue['body'] = channel_bug.HOLD_MARKER + '\nprivate garbage'
    elif fault == 'ambiguous':
        github.issues.append(_hold_issue(SHA, 6227))
    elif fault == 'bootstrap':
        github.refs.clear()
    api = github.api
    if fault == 'unavailable':
        api = lambda method, path, data=None: ((_ for _ in ()).throw(RuntimeError('unavailable'))
                                               if '/issues?' in path else github.api(method, path, data))
    with pytest.raises((channel_bug.AlertRefused, RuntimeError)):
        github.advance(_ref_evidence(candidate), api=api)
    assert not github.effects


@pytest.mark.parametrize('bootstrap', [True, False])
def test_ref_write_crash_replay_and_concurrent_candidate_order(ref_github, bootstrap):
    github = ref_github
    previous = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    newer = github.add(replace(candidate, sha='c' * 40, run_id=124, artifact_id=457))
    if not bootstrap:
        github.refs['dev'] = previous.sha
    github.fail_after_write = True
    with pytest.raises(channel_bug.AlertRefused, match='github_request_failed'):
        github.advance(_ref_evidence(candidate))
    assert github.refs['dev'] == candidate.sha
    before = list(github.effects)
    assert github.advance(_ref_evidence(candidate))['channel_ref'] == 'unchanged'
    assert github.effects == before
    github.before_write = lambda: github.refs.update(dev=newer.sha)
    with pytest.raises(channel_bug.AlertRefused, match='github_request_failed'):
        github.advance(_ref_evidence(newer))
    assert github.refs['dev'] == newer.sha and github.effects == before
    with pytest.raises(channel_bug.AlertRefused, match='channel_ref_not_fast_forward'):
        github.advance(_ref_evidence(candidate))
    assert github.refs['dev'] == newer.sha


def test_ref_readback_failure_and_delayed_bootstrap_never_claim_success(tmp_path, ref_github):
    github = ref_github
    older = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    newer = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_ref_channel(tmp_path, newer) == 0
    github.refs.clear()
    before = list(github.effects)
    assert github.advance(_ref_evidence(older))['channel_ref'] == 'stale'
    assert github.effects == before and not github.refs
    ref_reads = 0

    def readback(method, path, data=None):
        nonlocal ref_reads
        if '/git/matching-refs/' in path:
            ref_reads += 1
            if ref_reads > 1:
                return []
        return github.api(method, path, data)

    with pytest.raises(channel_bug.AlertRefused, match='channel_ref_readback_refused'):
        github.advance(_ref_evidence(newer), api=readback)
    assert github.refs['dev'] == newer.sha
    assert github.advance(_ref_evidence(newer))['channel_ref'] == 'unchanged'


def test_channel_ref_workflow_permissions_and_real_cli_are_narrow():
    workflow = yaml.safe_load((ROOT / '.github/workflows/postmerge-channel-bug.yml').read_text())
    assert workflow['concurrency'] == {'group': 'postmerge-channel-verdict', 'cancel-in-progress': False, 'queue': 'max'}
    job = workflow['jobs']['record-channel-ref']
    assert job['needs'] == 'reconcile'
    assert all(part in job['if'] for part in ("github.ref == 'refs/heads/main'", "github.actor == 'RasmusTho'"))
    assert job['permissions'] == {'contents': 'write', 'actions': 'read', 'issues': 'read'}
    assert job['steps'][0]['with'] == {'ref': '${{ github.sha }}', 'persist-credentials': False}
    assert '--advance-ref' in job['steps'][1]['run'] and '--receipt-file channel-verdict.json' in job['steps'][1]['run']
    assert '${{' not in job['steps'][1]['run']
    assert job['steps'][2]['with']['path'] == 'channel-verdict.json'
    assert workflow['jobs']['reconcile']['permissions']['contents'] == 'read'
    assert not any('secret' in str(step).lower() for step in job['steps'])


@pytest.mark.parametrize('latest', [('completed', 'failure'), ('in_progress', None)])
def test_exact_green_dev_artifact_survives_a_later_reporting_rerun(tmp_path, ref_github, latest):
    github = ref_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_ref_channel(tmp_path, candidate) == 0
    dev = github.runs[0]
    dev.update(run_attempt=2, status=latest[0], conclusion=latest[1])
    github.refs.pop('test')
    assert github.advance(_ref_evidence(candidate, channel='test'))['channel_ref'] == 'advanced'
    assert github.refs['test'] == SHA
    assert f'repos/{driver.REPOSITORY}/actions/runs/1000/attempts/1' in github.reads


def test_ref_consumer_reuses_exact_source_attempt_and_earlier_image_job(tmp_path, ref_github):
    github = ref_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 2, 456))
    github.image_attempts[123] = 1
    assert _poll_ref_channel(tmp_path, candidate) == 0
    assert github.refs == {'dev': SHA, 'test': SHA}
    assert github.ref_results == [0, 0]
    assert f'repos/{driver.REPOSITORY}/actions/runs/123/attempts/2' in github.reads
    assert f'repos/{driver.REPOSITORY}/actions/runs/123' not in github.reads


def test_dev_hold_authority_and_activation_race_are_explicit(ref_github):
    github = ref_github
    previous = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.refs['dev'] = previous.sha
    foreign = _hold_issue(previous.sha)
    foreign['user']['login'] = 'outsider'
    closed = {**_hold_issue(previous.sha, 6227), 'state': 'closed'}
    github.issues.extend((foreign, closed))
    requested = _hold_issue(previous.sha, 6228)
    # Opening the Issue is intent. Only a successful held receipt activates it.
    # If a previously admitted ref move wins, the pin mismatch refuses loudly.
    github.before_write = lambda: github.issues.append(requested)
    assert github.advance(_ref_evidence(candidate))['channel_ref'] == 'advanced'
    before = list(github.effects)
    with pytest.raises(channel_bug.AlertRefused, match='dev_hold_pin_mismatch'):
        github.advance(_ref_evidence(candidate))
    assert github.refs['dev'] == candidate.sha and github.effects == before
    requested['body'] = requested['body'].replace(previous.sha, candidate.sha)
    assert github.advance(_ref_evidence(candidate))['channel_ref'] == 'held'
    assert github.effects == before


@pytest.mark.parametrize('fault', ['actor', 'repository', 'head_repository', 'run_attempt', 'path'])
def test_ref_consumer_refuses_foreign_own_workflow_provenance(ref_github, fault):
    github = ref_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    row = github._run()
    row[fault] = ({'login': 'outsider'} if fault == 'actor' else {'full_name': 'foreign/repo'}
                  if fault in {'repository', 'head_repository'} else 2 if fault == 'run_attempt'
                  else '.github/workflows/foreign.yml')
    github.own_runs[900] = row
    with pytest.raises(channel_bug.AlertRefused, match='workflow_authority_refused'):
        github.advance(_ref_evidence(candidate))
    assert not github.effects


@pytest.mark.parametrize('fault', ['ref_read', 'hold_readback', 'hold_listing', 'hold_pagination'])
def test_channel_ref_unavailable_and_incomplete_reads_refuse_before_effect(ref_github, fault):
    github = ref_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.refs['dev'] = SHA
    if fault == 'hold_readback':
        github.issues.append(_hold_issue(SHA))

    def api(method, path, data=None):
        if fault == 'ref_read' and '/git/matching-refs/' in path:
            return None
        if fault == 'hold_readback' and '/issues/6226' in path:
            raise RuntimeError('private readback failure')
        if fault == 'hold_listing' and '/issues?' in path:
            return {'items': []}
        if fault == 'hold_pagination' and '/issues?' in path:
            return [{'number': i, 'body': 'ordinary owner Issue'} for i in range(100)]
        return github.api(method, path, data)

    with pytest.raises((channel_bug.AlertRefused, RuntimeError)):
        github.advance(_ref_evidence(candidate), api=api)
    assert github.refs['dev'] == SHA and not github.effects


@pytest.mark.parametrize('dev_delivery', ['reordered', 'cancelled', 'lost_response'])
def test_reordered_or_replaced_requests_recover_by_exact_workflow_rerun(tmp_path, ref_github, dev_delivery):
    github = ref_github
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.queue_only = True
    assert _poll_ref_channel(tmp_path, candidate) == 0
    dev, test = github.pending
    assert len(github.deliveries) == 2
    # Actions accepts both dispatches, but its concurrency group promises no
    # dispatch order. A test request can execute before any dev receipt exists.
    assert github.consume(*test) == 1
    assert not github.refs
    if dev_delivery == 'cancelled':
        fields, run_id = dev
        evidence = json.loads(fields['evidence'])
        row = github._run(run_id)
        row.update(status='completed', conclusion='cancelled',
                   display_title=f"channel-bug/dev/passed/{SHA}/123/1/{evidence['receipt_fingerprint']}")
        github.own_runs[run_id] = row
        github.own_attempts[(run_id, 1)] = dict(row)
        github.runs.append(row)
        assert github.consume(*test, attempt=2) == 1
        assert not github.refs
        assert github.consume(*dev, attempt=2) == 0
    elif dev_delivery == 'lost_response':
        github.fail_after_write = True
        assert github.consume(*dev) == 1
        assert github.refs == {'dev': SHA}
        assert not github.uploads[dev[1]]
        assert github.consume(*dev, attempt=2) == 0
    else:
        assert github.consume(*dev) == 0
    assert github.consume(*test, attempt=3) == 0
    assert github.refs == {'dev': SHA, 'test': SHA}
    assert len(github.deliveries) == 2  # no host resend or native deployment replay
    writes = [effect for effect in github.effects if '/git/refs' in effect[1]]
    assert len(writes) == 2 and all(effect[0] == 'POST' for effect in writes)


def test_newer_red_or_skipped_workflow_cannot_replace_green_ref_authority(tmp_path, ref_github):
    github = ref_github
    good = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    github.queue_only = True
    assert _poll_ref_channel(tmp_path, good) == 0
    bad = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    assert _poll_ref_channel(tmp_path, bad, red='dev') == 78
    dev, test, red = github.pending
    assert github.consume(*red) == 0 and not github.refs
    # The delayed prior green remains the channel's latest actual green even
    # after a newer red verdict has successfully updated its rolling bug.
    assert github.consume(*dev) == 0
    assert github.refs['dev'] == good.sha
    assert github.issues[0]['state'] == 'open'
    assert github.consume(*test) == 0
    assert github.refs['test'] == good.sha
    # Overall success with a skipped ref job has no green artifact authority.
    skipped = github._run(1500)
    skipped.update(status='completed', conclusion='success',
                   display_title=f"channel-bug/dev/passed/{SHA}/123/1/{'0' * 64}")
    github.own_runs[1500] = skipped
    github.runs.append(skipped)
    github.uploads[1500] = []
    github.refs.clear()
    assert github.advance(_ref_evidence(good))['channel_ref'] == 'advanced'
    assert github.refs['dev'] == good.sha


@pytest.mark.parametrize('fault', ['changed', 'unavailable', 'malformed'])
def test_dev_hold_confirmation_requires_final_ref_readback(ref_github, fault):
    github = ref_github
    previous = github.add(driver.Candidate('1' * 40, DIGEST, 122, 1, 455))
    candidate = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    github.refs['dev'] = previous.sha
    github.issues.append(_hold_issue(previous.sha))
    reads = 0

    def api(method, path, data=None):
        nonlocal reads
        if '/git/matching-refs/heads/dev' in path:
            reads += 1
            if reads == 2:
                if fault == 'changed':
                    github.refs['dev'] = candidate.sha
                elif fault == 'unavailable':
                    raise RuntimeError('private readback error')
                else:
                    return {'incomplete': True}
        return github.api(method, path, data)

    with pytest.raises((channel_bug.AlertRefused, RuntimeError)):
        github.advance(_ref_evidence(candidate), api=api)
    assert reads == 2 and not github.effects


def test_ref_authority_requires_current_heavy_dev_verdict(tmp_path, ref_github):
    github = ref_github
    first = github.add(driver.Candidate(SHA, DIGEST, 123, 1, 456))
    native = _channel_evidence(first, verdict='passed')
    assert github.consume({'channel': 'dev', 'evidence': json.dumps(native)}, 2000) == 1
    assert not github.effects and not github.refs
    assert _poll_ref_channel(tmp_path, first, heavy=lambda _: dict(HEAVY_PASSED, result='failed', failed=1)) == 78
    assert not github.refs and len(github.deliveries) == 1
    assert github.deliveries[0]['gate'] == 'heavy_acceptance' and github.deliveries[0]['verdict'] == 'failed'
    later = github.add(replace(first, sha='c' * 40, run_id=124, artifact_id=457))
    assert _poll_ref_channel(tmp_path, later) == 0
    assert github.refs == {'dev': later.sha, 'test': later.sha}
