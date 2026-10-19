from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import io
import json
import os
import plistlib
import shutil
from datetime import datetime, timedelta, timezone
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
    # A committed TEST candidate triggers the heavy step on the next tick; keep
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
    assert calls == [('dev', current), ('test', current)]
    checkpoint = json.loads(path.read_text())
    assert checkpoint['candidate'] == driver.asdict(current)
    assert checkpoint['phase'] == 'passed' and checkpoint['channel'] == 'test'


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


def _poll_channel(tmp_path, candidate, *, red=None, source_failure=None, **kwargs):
    tmp_path.chmod(0o700)

    def deploy(channel, received):
        receipt = _native_receipt(channel, received, 'failed' if channel == red else 'committed')
        if channel == red and source_failure:
            receipt['source_failure'] = source_failure
        return receipt

    return driver.poll(tmp_path, build=lambda: candidate.run_id, load=lambda _: candidate,
                       current_main=lambda: candidate.sha, deploy=deploy, **kwargs)


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
    assert workflow['concurrency'] == {'group': 'postmerge-channel-bug-${{ inputs.channel }}',
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
    assert driver.poll(tmp_path, deploy=lambda *_: pytest.fail('terminal deployment replay')) == 0
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
    checkout = tmp_path / 'reviewed'
    checkout.mkdir()
    for name in ('app/ops', 'app/config'):
        shutil.copytree(ROOT / name, checkout / name, ignore=shutil.ignore_patterns('__pycache__'))
    (checkout / 'app/__init__.py').write_bytes((ROOT / 'app/__init__.py').read_bytes())
    (checkout / 'scripts').mkdir()
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
    assert installer.main(['--checkout', str(checkout), '--python', sys.executable]) == 0
    state = home / '.local/state/yggdrasil/secret-controller/postmerge'
    config = plistlib.loads((home / 'Library/LaunchAgents' / (installer.LABEL + '.plist')).read_bytes())
    return SimpleNamespace(checkout=checkout, source=state / 'tooling' / sha / 'source',
                           state=state, config=config, sha=sha, signals=signals, gh=gh)


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


@pytest.mark.parametrize('fault', ['controller_import', 'host_import', 'lazy_import', 'pin_missing', 'python_identity', 'transport_down'])
def test_controller_self_check_fails_loud(installed_controller_pin, monkeypatch, fault):
    from scripts import dev_delivery_liveness as liveness
    pin = installed_controller_pin
    if fault in {'controller_import', 'host_import', 'lazy_import', 'transport_down'}:
        module = {'controller_import': 'scripts/postmerge_dev_test.py',
                  'host_import': 'app/ops/postgres_deploy_host.py',
                  'lazy_import': 'app/ops/native_source_bootstrap.py',
                  'transport_down': 'scripts/postmerge_dev_test.py'}[fault]
        (pin.source / module).write_text("raise ModuleNotFoundError('private input must not leak')\n")
    elif fault == 'pin_missing':
        (pin.source.parent / 'pin.json').unlink()
    else:
        path = pin.source.parent / 'pin.json'
        data = json.loads(path.read_text())
        data['python_version'] = 'wrong runtime'
        path.write_text(json.dumps(data))
    if fault == 'transport_down':
        pin.gh.write_text('#!/bin/sh\nexit 1\n')
    result = subprocess.run(pin.config['ProgramArguments'], cwd=pin.source,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 78
    assert json.loads(result.stdout) == {'result': 'startup_self_check_failed',
                                       'liveness_signal': 'failed' if fault == 'transport_down' else 'sent'}
    assert 'private input' not in result.stdout + result.stderr
    assert not (pin.state / 'postmerge-dev-test.json').exists()
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
    liveness.record_signal('heartbeat', json.dumps(payload), repo=driver.REPOSITORY,
                           event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                           triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999',
                           api=lambda _: {'status': 'identical'}, now=now)
    fields = dict(item.split('=', 1) for item in writes[0] if '=' in item)
    assert fields['state'] == 'failure' and fields['description'].endswith(';startup=self_check_failed')
    status = {key: fields[key] for key in ('state', 'context', 'description')}
    build = liveness.AdmittedBuild(SHA, now - timedelta(hours=1), 123)
    verdict = {'state': 'success', 'context': liveness.VERDICT_CONTEXT,
               'description': 'observed_at=' + (now - timedelta(minutes=2)).isoformat()}
    checked = liveness.evaluate(build, heartbeat_statuses=[status], verdict_statuses=[verdict], now=now)
    assert not checked.ok and checked.reason == 'startup_self_check_failed'
    recovered = {**status, 'state': 'success', 'description': 'observed_at=' + now.isoformat()}
    assert liveness.evaluate(build, heartbeat_statuses=[status, recovered], verdict_statuses=[verdict], now=now).ok


def test_installer_partial_pin_does_not_replace_active_launch_or_checkpoint(installed_controller_pin, monkeypatch):
    from scripts import install_postmerge_controller as installer
    pin = installed_controller_pin
    # Use the actual existing LaunchAgent path rather than manufacturing a
    # replacement producer. A failed staged runtime leaves it byte-identical.
    plist = next(pin.state.parents[4].glob('Library/LaunchAgents/*.plist'))
    before = plist.read_bytes()
    checkpoint = pin.state / 'postmerge-dev-test.json'
    checkpoint.write_text('retained same-ID recovery state')
    sha = 'c' * 40
    monkeypatch.setattr(installer, 'require_reviewed_checkout', lambda *_: sha)
    run = subprocess.run
    def fail_runtime(command, **kwargs):
        if 'venv' in command:
            raise subprocess.CalledProcessError(1, command)
        if 'archive' in command:
            command = [pin.sha if part == sha else part for part in command]
        return run(command, **kwargs)
    monkeypatch.setattr(installer.subprocess, 'run', fail_runtime)
    assert installer.main(['--checkout', str(pin.checkout), '--python', sys.executable]) == 78
    assert plist.read_bytes() == before
    assert checkpoint.read_text() == 'retained same-ID recovery state'
    assert not (pin.state / 'tooling' / sha).exists()
    assert not list((pin.state / 'tooling').glob('.install-*'))


@pytest.mark.parametrize('value', ['passed', 'unknown', True, None])
def test_startup_signal_refuses_non_failure_values(monkeypatch, value):
    from scripts import dev_delivery_liveness as liveness
    payload = {'protocol': driver.LIVENESS_PROTOCOL, 'sha': SHA,
               'observed_at': datetime.now(timezone.utc).isoformat(), 'startup': value}
    monkeypatch.setattr(liveness.subprocess, 'run', lambda *_a, **_k: pytest.fail('refused signal wrote a status'))
    with pytest.raises(liveness.LivenessRefused, match='signal_startup_refused'):
        liveness.record_signal('heartbeat', json.dumps(payload), repo=driver.REPOSITORY,
                               event='workflow_dispatch', ref='refs/heads/main', actor='RasmusTho',
                               triggering_actor='RasmusTho', run_url=f'https://github.com/{driver.REPOSITORY}/actions/runs/999')


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
