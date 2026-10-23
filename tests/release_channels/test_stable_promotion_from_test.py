"""Real promotion admission with GitHub/Docker transports isolated from effects."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from app.release_channels import promotion_receipt as receipts
from app.release_channels import stable_promotion as promotion
from app.release_channels.channel_manifest import render_channel_manifest
from app.release_channels.prepare_promotion import generate_plan
from scripts.postmerge_dev_test import Candidate, IMAGE_REPOSITORY, REPOSITORY

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def _git(root: Path, *args: str, input: str | None = None) -> str:
    return subprocess.run(['git', *args], cwd=root, input=input, text=True,
                          capture_output=True, check=True).stdout.strip()


def _write_plan(root: Path, evidence: dict, *, approve: bool = False) -> Path:
    plan = generate_plan(evidence['stable_baseline'], evidence['candidate']['sha'], root / 'plans',
                         promotion_evidence=evidence)
    path = Path(plan.artifact_path)
    if approve:
        evidence['approval'] = {'operator': 'Synthetic test operator',
                                'plan_digest': promotion.approval_digest(evidence, plan_text=path.read_text())}
        plan = generate_plan(evidence['stable_baseline'], evidence['candidate']['sha'], root / 'plans',
                             promotion_evidence=evidence)
    path.write_text(path.read_text().replace('- [ ]', '- [x]'))
    return path


@pytest.mark.parametrize('fault', ['oversized', 'symlink', 'fifo', 'operator_type'])
def test_malformed_plan_refuses_before_evidence_or_effects(tmp_path, fault):
    evidence = {'candidate': {'sha': 'b' * 40}, 'stable_baseline': 'a' * 40, 'deployment_model': 'pinned-image',
                'functional_evidence': {}, 'approval': {}, 'execution': {}}
    plan = _write_plan(tmp_path, evidence, approve=True)
    if fault == 'oversized':
        plan.write_bytes(b'x' * 262145)
    elif fault in {'symlink', 'fifo'}:
        target = tmp_path / 'plan-input'
        if fault == 'symlink':
            target.symlink_to(plan)
        else:
            os.mkfifo(target)
        plan = target
    else:
        evidence['approval']['operator'] = 123
        _write_plan(tmp_path, evidence)
    with pytest.raises(promotion.PromotionRefused, match='promotion_plan_invalid|exact_plan_approval_required'):
        promotion._load_plan(plan)


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    # Existing STARTUP renderer/writer and #6226 producer remain real. Only
    # GitHub transport and canonical remote-ref readback are substituted.
    from tests.runtime.test_startup_artifact_call_sites import (
        _promotion_admission_context, _promotion_test_candidate_inputs,
        _seed_promotion_registry,
    )
    from tests.deploy.test_postmerge_dev_test import _RefGithub, _ref_evidence

    repo = tmp_path / 'source'
    repo.mkdir()
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.name', 'Synthetic promotion test')
    _git(repo, 'config', 'user.email', 'promotion-test@example.invalid')
    (repo / 'code').write_text('old')
    migrations = repo / 'app/alembic/versions'
    migrations.mkdir(parents=True)
    (migrations / '__init__.py').write_text('')
    protocol = repo / 'app/config/database.py'
    protocol.parent.mkdir()
    protocol.write_text('DATABASE_FILE_CREDENTIAL_PROTOCOL = 1\n')
    _git(repo, 'add', 'code', 'app/alembic/versions/__init__.py', 'app/config/database.py')
    _git(repo, 'commit', '-qm', 'baseline')
    baseline = _git(repo, 'rev-parse', 'HEAD')
    (repo / 'code').write_text('new')
    _git(repo, 'commit', '-qam', 'candidate')
    sha = _git(repo, 'rev-parse', 'HEAD')
    tree = _git(repo, 'rev-parse', 'HEAD^{tree}')
    merged = _git(repo, 'commit-tree', tree, '-p', baseline, '-p', sha, input='protected promotion\n')
    current = {'stable': baseline}
    monkeypatch.setattr(receipts, '_fetch_authoritative_prod_baseline', lambda: current['stable'])
    context = _promotion_admission_context(migration_baseline_sha=baseline)
    rendered, manifest = _promotion_test_candidate_inputs(source_sha=sha)
    manifest['artifact']['repository'] = IMAGE_REPOSITORY
    compose = rendered['compose']
    compose['services']['api']['image'] = IMAGE_REPOSITORY + '@' + manifest['artifact']['platform_digest']
    rendered = render_channel_manifest(manifest, compose, channel='promotion-test',
                                       mode='promotion', intent='promotion')
    report = receipts.build_promotion_test_check_report(
        rendered=rendered, channel_manifest=manifest, prod_admission_context=context,
        check_results={name: True for name in receipts.REQUIRED_CHECKS if name != 'migration'},
        source_repo=repo,
    )
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    store = tmp_path / 'receipt-store'
    _seed_promotion_registry(store, public)
    receipt = receipts.write_promotion_test_terminal_receipt(
        attempt_id='pt-' + '1' * 32, rendered=rendered, channel_manifest=manifest,
        prod_admission_context=context, check_report=report, source_repo=repo,
        issued_at=NOW, fresh_until=NOW + timedelta(hours=1), issuer_id='promotion-test-issuer',
        issuer_key_id='promotion-test-issuer-key-v1', signer=key.sign, issuer_public_key=public,
        receipt_store=store, resettable_roots=(repo / 'tmp-test', repo / 'vault-test'),
    )
    (tmp_path / 'context.json').write_text(json.dumps(context))
    (tmp_path / 'report.json').write_text(json.dumps(report))
    (tmp_path / 'rendered.json').write_text(json.dumps(rendered))
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    model = repo / 'ops/deployments/prod-latest.json'
    model.parent.mkdir(parents=True)
    model.write_text(json.dumps({'channel': 'prod', 'fleet_model_fitness': {
        'guard': 'fleet_model_fitness.v1', 'channel': 'prod', 'model': 'pinned-image', 'ok': True,
    }}))
    candidate = Candidate(sha, context['artifact_digest'], 102, 1, 202)
    github = _RefGithub(monkeypatch, tmp_path)
    github.candidates = [Candidate(baseline, 'sha256:' + 'c' * 64, 101, 1, 201), candidate]
    for channel in ('dev', 'test'):
        evidence = _ref_evidence(candidate, channel=channel)
        assert github.consume({'channel': channel, 'evidence': json.dumps(evidence)},
                              1000 if channel == 'dev' else 1001) == 0
    github.refs['stable'] = baseline
    protection = {'enforce_admins': {'enabled': True}, 'required_pull_request_reviews': {},
                  'required_status_checks': {'strict': True, 'contexts': ['smoke', 'smoke-docker', 'pr-contract']},
                  'allow_force_pushes': {'enabled': False}, 'allow_deletions': {'enabled': False}}
    pr = {'merged': True, 'base': {'ref': 'stable', 'repo': {'full_name': REPOSITORY}},
          'head': {'sha': sha, 'repo': {'full_name': REPOSITORY}}, 'merge_commit_sha': merged}
    commits = {sha: {'tree': {'sha': tree}},
               merged: {'tree': {'sha': tree}, 'parents': [{'sha': baseline}, {'sha': sha}]}}
    comparison = {'status': 'ahead'}

    def api(method, path, data=None):
        assert method == 'GET', 'promotion admission may not mutate GitHub'
        if path.endswith('/branches/stable/protection'):
            return protection
        if path.endswith('/pulls/7000'):
            return pr
        if '/git/commits/' in path:
            return commits[path.rsplit('/', 1)[-1]]
        if '/compare/' in path:
            return comparison
        return github.api(method, path, data)

    monkeypatch.setattr(promotion.channels, '_api', api)
    monkeypatch.setattr(promotion, '_github', github.archive)
    evidence = {'candidate': asdict(candidate), 'stable_baseline': baseline,
                'deployment_model': 'pinned-image',
                'functional_evidence': {
                    'receipt': str(store / 'receipts' / (receipt['receipt_id'][7:] + '.json')),
                    'registry': str(store / 'registry.json'), 'context': str(tmp_path / 'context.json'),
                    'check_report': str(tmp_path / 'report.json'), 'receipt_id': receipt['receipt_id'],
                    'rendered': str(tmp_path / 'rendered.json'), 'manifest': str(tmp_path / 'manifest.json'),
                }, 'approval': {}, 'execution': {}}
    plan = _write_plan(tmp_path, evidence, approve=True)

    def authorize(phase='promotion', **kwargs):
        kwargs.setdefault('api', api)
        kwargs.setdefault('archive', github.archive)
        kwargs.setdefault('now', NOW)
        return promotion.authorize_promotion(plan, phase=phase, source_repo=repo,
                                             **kwargs)

    def execute():
        current['stable'] = github.refs['stable'] = merged
        evidence['execution'] = {'pull_request': 7000, 'stable_sha': merged}
        _write_plan(tmp_path, evidence)

    return locals()


def test_promotion_requires_test_passed_candidate(admitted):
    a = admitted
    accepted = a['authorize']()
    assert accepted['candidate'] == asdict(a['candidate'])
    assert accepted['image_digest'] == a['candidate'].digest
    for value in (a['baseline'], 'f' * 40):
        a['github'].refs['test'] = value
        with pytest.raises(promotion.PromotionRefused, match='candidate_is_not_current_test'):
            a['authorize']()
    a['github'].refs.pop('test')
    with pytest.raises(promotion.PromotionRefused, match='current_channel_ref_missing'):
        a['authorize']()


def test_protected_merge_preserves_tested_image_and_signed_baseline(admitted):
    a = admitted
    a['execute']()
    accepted = a['authorize']('deploy', candidate_sha=a['sha'], image_digest=a['candidate'].digest)
    assert accepted['stable_sha'] == a['merged'] != accepted['candidate']['sha']
    assert accepted['stable_baseline'] == a['baseline']
    with pytest.raises(promotion.PromotionRefused, match='deploy_target_identity_mismatch'):
        a['authorize']('deploy', candidate_sha=a['merged'])


@pytest.mark.parametrize('fault', ['approval', 'model', 'cutover', 'protection', 'ancestry', 'test_green', 'image'])
def test_promotion_refuses_unqualified_inputs(admitted, fault):
    a = admitted
    if fault == 'approval':
        a['evidence']['approval']['plan_digest'] = 'sha256:' + '0' * 64
    elif fault == 'model':
        a['evidence']['deployment_model'] = 'checkout'
    elif fault == 'cutover':
        a['model'].unlink()
    elif fault == 'protection':
        a['protection']['enforce_admins']['enabled'] = False
    elif fault == 'ancestry':
        a['comparison']['status'] = 'diverged'
    elif fault == 'test_green':
        for run in a['github'].runs:
            if '/test/' in run.get('display_title', ''):
                run['conclusion'] = 'failure'
    elif fault == 'image':
        a['github'].artifact_fault = 'digest'
    _write_plan(a['tmp_path'], a['evidence'], approve=fault in {'model', 'ancestry'})
    with pytest.raises(promotion.PromotionRefused):
        a['authorize']()


@pytest.mark.parametrize('property', ['reviews', 'strict', 'checks', 'force_pushes', 'deletions'])
def test_promotion_requires_complete_protected_stable_policy(admitted, property):
    a = admitted
    if property == 'reviews':
        a['protection']['required_pull_request_reviews'] = None
    elif property in {'strict', 'checks'}:
        a['protection']['required_status_checks'][
            'strict' if property == 'strict' else 'contexts'
        ] = False if property == 'strict' else ['smoke', 'pr-contract']
    else:
        a['protection']['allow_' + property]['enabled'] = True
    with pytest.raises(promotion.PromotionRefused, match='stable_protection_required'):
        a['authorize']()


@pytest.mark.parametrize('property', ['merged', 'base', 'base_repository', 'head_repository', 'merge'])
def test_deploy_requires_exact_merged_protected_pr(admitted, property):
    a = admitted
    a['execute']()
    if property == 'merged':
        a['pr']['merged'] = False
    elif property == 'base':
        a['pr']['base']['ref'] = 'main'
    elif property in {'base_repository', 'head_repository'}:
        a['pr'][property.split('_', 1)[0]]['repo']['full_name'] = 'foreign/repository'
    else:
        a['pr']['merge_commit_sha'] = a['sha']
    with pytest.raises(promotion.PromotionRefused, match='protected_promotion_receipt_mismatch'):
        a['authorize']('deploy')


@pytest.mark.parametrize('fault', ['parents', 'tree', 'pr', 'stable', 'digest', 'receipt', 'report',
                                  'context', 'rendered', 'manifest', 'revoked'])
def test_deploy_refuses_changed_transition_or_functional_evidence(admitted, fault):
    a = admitted
    a['execute']()
    if fault == 'parents':
        a['commits'][a['merged']]['parents'].reverse()
    elif fault == 'tree':
        a['commits'][a['merged']]['tree'] = {'sha': 'f' * 40}
    elif fault == 'pr':
        a['pr']['head']['sha'] = a['baseline']
    elif fault == 'stable':
        a['github'].refs['stable'] = a['baseline']
    elif fault == 'digest':
        a['evidence']['candidate']['digest'] = 'sha256:' + 'f' * 64
        _write_plan(a['tmp_path'], a['evidence'], approve=True)
    elif fault == 'revoked':
        registry = a['store'] / 'registry.json'
        document = json.loads(registry.read_text())
        document['entries'][a['receipt']['receipt_id']]['status'] = 'revoked'
        registry.write_text(json.dumps(document))
    else:
        path = Path(a['evidence']['functional_evidence'][fault if fault != 'report' else 'check_report'])
        path.write_text('{}')
    with pytest.raises(promotion.PromotionRefused):
        a['authorize']('deploy')


def test_reviewed_narrative_and_inputs_are_immutable_but_observed_outputs_are_retained(admitted):
    a = admitted
    original = a['plan'].read_text()
    a['plan'].write_text(original + '\n' + promotion.OUTCOMES + '\nObserved verification pending.\n')
    assert a['authorize']()['candidate']['sha'] == a['sha']
    a['plan'].write_text(original.replace('## Risk notes', 'Changed reviewed risk.\n\n## Risk notes'))
    with pytest.raises(promotion.PromotionRefused, match='exact_plan_approval_required'):
        a['authorize']()
    a['plan'].write_text(original.replace('- [x]', '- [ ]', 1))
    with pytest.raises(promotion.PromotionRefused, match='exact_plan_approval_required'):
        a['authorize']()


@pytest.mark.parametrize('endpoint', ['refs', 'protection', 'pulls', 'artifacts'])
def test_denied_or_unavailable_evidence_is_a_bounded_refusal(admitted, endpoint):
    a = admitted
    a['execute']()

    def denied(method, path, data=None):
        if {'refs': '/git/matching-refs/', 'protection': '/protection',
            'pulls': '/pulls/', 'artifacts': '/artifacts'}[endpoint] in path:
            raise PermissionError('synthetic provider-private diagnostic')
        return a['api'](method, path, data)

    with pytest.raises(promotion.PromotionRefused, match='promotion_evidence_unavailable_or_invalid') as refused:
        a['authorize']('deploy', api=denied)
    assert 'provider-private' not in str(refused.value)


def test_stale_functional_pass_and_changed_baselines_refuse(admitted):
    a = admitted
    with pytest.raises(promotion.PromotionRefused):
        a['authorize'](now=NOW + timedelta(hours=2))
    a['github'].refs['stable'] = a['merged']
    with pytest.raises(promotion.PromotionRefused, match='stable_baseline_changed'):
        a['authorize']()
    a['execute']()
    a['current']['stable'] = a['baseline']
    with pytest.raises(promotion.PromotionRefused):
        a['authorize']('deploy')


@pytest.mark.parametrize('changed', ['plan', 'test', 'stable'])
def test_changed_frontier_during_real_functional_validation_refuses(admitted, monkeypatch, changed):
    a = admitted
    original = receipts.prepare_prod_activation

    def concurrent_change(*args, **kwargs):
        result = original(*args, **kwargs)
        if changed == 'plan':
            a['evidence']['execution'] = {'pull_request': 9000, 'stable_sha': a['merged']}
            _write_plan(a['tmp_path'], a['evidence'])
        else:
            a['github'].refs[changed] = a['merged']
        return result

    monkeypatch.setattr(receipts, 'prepare_prod_activation', concurrent_change)
    with pytest.raises(promotion.PromotionRefused, match='promotion_plan_changed|promotion_ref_changed'):
        a['authorize']()


def test_valid_signed_receipt_cannot_substitute_foreign_source_or_another_approved_receipt(admitted):
    a = admitted
    # A different source may share the declared image digest in a malformed
    # producer input. Its fully signed receipt still cannot qualify current C.
    manifest = json.loads(json.dumps(a['manifest']))
    manifest['artifact']['source_sha'] = a['baseline']
    rendered = render_channel_manifest(manifest, a['rendered']['compose'], channel='promotion-test',
                                       mode='promotion', intent='promotion')
    report = receipts.build_promotion_test_check_report(
        rendered=rendered, channel_manifest=manifest, prod_admission_context=a['context'],
        check_results={name: True for name in receipts.REQUIRED_CHECKS if name != 'migration'},
        source_repo=a['repo'],
    )
    foreign = receipts.write_promotion_test_terminal_receipt(
        attempt_id='pt-' + '2' * 32, rendered=rendered, channel_manifest=manifest,
        prod_admission_context=a['context'], check_report=report, source_repo=a['repo'],
        issued_at=NOW, fresh_until=NOW + timedelta(hours=1), issuer_id='promotion-test-issuer',
        issuer_key_id='promotion-test-issuer-key-v1', signer=a['key'].sign, issuer_public_key=a['public'],
        receipt_store=a['store'], resettable_roots=(a['repo'] / 'tmp-test', a['repo'] / 'vault-test'),
    )
    a['execute']()
    registry = json.loads((a['store'] / 'registry.json').read_text())
    with pytest.raises(receipts.PromotionReceiptError, match='protected_transition_invalid'):
        receipts.prepare_prod_activation(foreign, registry, a['context'], check_report=report,
                                          source_repo=a['repo'], now=NOW, promotion_plan=a['plan'])
    functional = a['evidence']['functional_evidence']
    functional['receipt_id'] = foreign['receipt_id']
    functional['receipt'] = str(a['store'] / 'receipts' / (foreign['receipt_id'][7:] + '.json'))
    for field, data in [('manifest', manifest), ('rendered', rendered), ('check_report', report)]:
        Path(functional[field]).write_text(json.dumps(data))
    _write_plan(a['tmp_path'], a['evidence'], approve=True)
    with pytest.raises(promotion.PromotionRefused, match='functional_test_identity_mismatch'):
        a['authorize']('deploy')


@pytest.mark.parametrize('object_name', ['baseline', 'sha', 'merged'])
@pytest.mark.parametrize('fault', ['missing', 'corrupt'])
def test_protected_api_merge_cannot_replace_verified_local_git_identity(admitted, fault, object_name):
    a = admitted
    a['execute']()
    object_id = a[object_name]
    object_path = a['repo'] / '.git/objects' / object_id[:2] / object_id[2:]
    assert object_path.is_file()
    if fault == 'missing':
        object_path.unlink()
    else:
        object_path.chmod(0o600)
        object_path.write_bytes(b'not the immutable merge object')
    with pytest.raises(promotion.PromotionRefused):
        a['authorize']('deploy')


def test_native_preflight_runs_real_admission_before_any_secret_read(admitted, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DATABASE_CONSUMERS, DeployPlan

    a = admitted
    a['execute']()
    reads = []

    def secret_boundary():
        reads.append('reader')
        raise RuntimeError('synthetic secret boundary reached')

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(promotion, 'datetime', Clock)
    config = SimpleNamespace(root=a['repo'], reader=secret_boundary)
    effects = linux.LinuxEffects(config)
    # Consumer discovery is a read of deployment source/host state, outside this
    # promotion assertion. The production admission and signed validator stay real.
    monkeypatch.setattr(effects, 'select_active_plan', lambda plan: plan)
    plan = DeployPlan('prod', a['sha'], tuple(DATABASE_CONSUMERS.values()), tuple(DATABASE_CONSUMERS),
                      image_digest=a['candidate'].digest, promotion_plan=str(a['plan']))
    a['github'].refs['test'] = a['baseline']
    with pytest.raises(promotion.PromotionRefused, match='candidate_is_not_current_test'):
        effects.preflight(plan)
    assert reads == []
    a['github'].refs['test'] = a['sha']
    with pytest.raises(RuntimeError, match='synthetic secret boundary reached'):
        effects.preflight(plan)
    assert reads == ['reader']



@pytest.mark.parametrize('fault', ['missing_plan', 'stale_test', 'revoked', None])
def test_supervised_bootstrap_admits_before_secrets_or_ready(admitted, monkeypatch, fault):
    from dataclasses import replace
    from types import SimpleNamespace
    from uuid import uuid4
    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import load_host_secret_contract
    from app.ops.postgres_deploy import DATABASE_CONSUMERS, DeployJournal, DeployPlan, PostgresDeployError

    a = admitted
    a['execute']()
    events = []
    contract = load_host_secret_contract()
    synthetic = {
        contract.bws_identity(channel='prod', consumer='heimdal-api-ingress', secret=secret): value
        for secret, value in [('heimdal.raw-store-key', 'a' * 64),
                              ('github.token', 'synthetic-bootstrap-token')]
    }

    class Reader:
        def lookup(self, project, identity):
            events.append('lookup')
            return synthetic[(project, identity)]

    def reader():
        events.append('reader')
        return Reader()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    class BeforeActivation(Exception):
        pass

    class ActivationBoundary:
        def wait(self):
            # Stop at the existing host bootstrap/activation boundary. The
            # real supervisor orchestration, journal and result remain real.
            raise BeforeActivation()

    monkeypatch.setattr(promotion, 'datetime', Clock)
    for key in ('DATABASE_URL', 'DB_DSN', 'POSTGRES_PASSWORD', 'PGPASSWORD',
                'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'):
        monkeypatch.delenv(key, raising=False)
    # External host discovery is isolated; source protocol validation and the
    # promotion/signed/green/consumer readers run through their real paths.
    monkeypatch.setattr(linux, '_capture_watch_configured', lambda _cfg: False)
    monkeypatch.setattr(linux, '_raw_representation_migration_pending', lambda *_a, **_kw: False)
    journal = DeployJournal(a['tmp_path'] / 'journal', 'prod')
    config = SimpleNamespace(root=a['repo'], channel='prod', journal=journal, reader=reader)
    effects = linux.LinuxEffects(config)

    def initialized():
        events.append('initialized')
        return False

    monkeypatch.setattr(effects, 'initialized', initialized)
    plan = DeployPlan('prod', a['sha'], tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'),
                      image_digest=a['candidate'].digest, promotion_plan=str(a['plan']))
    if fault == 'missing_plan':
        plan = replace(plan, promotion_plan=None)
    elif fault == 'stale_test':
        a['github'].refs['test'] = a['baseline']
    elif fault == 'revoked':
        path = Path(a['evidence']['functional_evidence']['registry'])
        registry = json.loads(path.read_text())
        registry['entries'][a['receipt']['receipt_id']]['status'] = 'revoked'
        path.write_text(json.dumps(registry))
    operation = linux.SupervisedOperation(effects, str(uuid4()), plan, bootstrap=True)
    operation.activation = ActivationBoundary()
    if fault:
        with pytest.raises((promotion.PromotionRefused, PostgresDeployError)):
            operation._run_locked()
        assert events == []
        assert not operation.ready.is_set() and operation.empty is False
        assert journal.read().stage == 'aborted'
    else:
        with pytest.raises(BeforeActivation):
            operation._run_locked()
        assert events == ['reader', 'lookup', 'lookup', 'initialized']
        assert operation.result() == {'pending': True, 'empty': True, 'ready': True}
        assert journal.read().stage == 'prepared'


def test_missing_plan_refuses_actual_prod_script_and_make_before_effects(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    effects = tmp_path / 'external-effect'
    for command in ('docker', 'curl', 'gh'):
        executable = bin_dir / command
        executable.write_text('#!/bin/sh\ntouch ' + str(effects) + '\nexit 99\n')
        executable.chmod(0o755)
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'], 'PYTHON': sys.executable}
    commands = [
        ['bash', str(ROOT / 'scripts/deploy_channel.sh'), 'deploy', 'prod', 'a' * 40],
        ['make', '--no-print-directory', 'deploy-prod', 'SHA=' + 'a' * 40],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        assert result.returncode != 0
        assert 'production deploy requires an approved promotion plan' in result.stderr
        assert not effects.exists()


def test_native_plan_preserves_production_approval_handle():
    from app.ops.postgres_deploy import DATABASE_CONSUMERS, DeployPlan
    plan = DeployPlan('prod', 'a' * 40, tuple(DATABASE_CONSUMERS.values()), tuple(DATABASE_CONSUMERS),
                      image_digest='sha256:' + 'b' * 64, promotion_plan='/private/promotion.md')
    assert DeployPlan.from_payload(plan.payload()) == plan
    legacy = DeployPlan('dev', 'a' * 40, plan.services, plan.consumers)
    assert 'promotion_plan' not in legacy.payload()
    assert DeployPlan.from_payload(legacy.payload()) == legacy


def test_native_activation_forwards_tested_identity_and_plan_to_existing_script(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DATABASE_CONSUMERS, DeployPlan

    source = tmp_path / 'synthetic-secret-handles'
    source.mkdir()
    config = SimpleNamespace(root=tmp_path, source_directory=source,
                             journal=SimpleNamespace(read=lambda: SimpleNamespace(
                                 stage='activating', operation_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')))
    effects = linux.LinuxEffects(config)
    effects.lock_fd = 123
    effects.active_consumers = tuple(DATABASE_CONSUMERS)
    effects.consumer_values = {consumer: {'postgres.password': 'synthetic-password'}
                               for consumer in DATABASE_CONSUMERS}
    monkeypatch.setattr(effects.source, 'verify', lambda: None)
    monkeypatch.setattr(effects, 'environment', lambda: {})
    monkeypatch.setattr(effects, '_reclaim_image_cache', lambda plan: None)
    commands = []
    monkeypatch.setattr(linux, '_command', lambda argv, **kwargs: commands.append((argv, kwargs)))
    plan = DeployPlan('prod', 'a' * 40, tuple(DATABASE_CONSUMERS.values()), tuple(DATABASE_CONSUMERS),
                      image_digest='sha256:' + 'b' * 64, promotion_plan='/target/approved-plan.md')
    effects.activate(plan)
    assert len(commands) == 1
    assert commands[0][0] == ['bash', str(tmp_path / 'scripts/deploy_channel.sh'), 'deploy', 'prod',
                               plan.revision, '--image-digest', plan.image_digest,
                               '--promotion-plan', plan.promotion_plan]
    assert list(source.iterdir()) == []


def test_real_deploy_caller_forwards_plan_and_digest_and_stops_on_refusal(tmp_path):
    from tests.deploy.test_deploy_channel import _deploy_harness, _run_deploy

    root, env, sha = _deploy_harness(tmp_path)
    args = tmp_path / 'promotion-args'
    env.update(FAKE_PROMOTION_ARGS_FILE=str(args), FAKE_PROMOTION_ADMISSION='fail')
    result = _run_deploy(root, env, sha, channel='prod')
    assert result.returncode == 78
    assert args.read_text().splitlines() == [
        '-m', 'app.release_channels.stable_promotion', '--plan', str(root / 'approved-promotion.md'),
        '--phase', 'deploy', '--candidate', sha, '--image-digest', 'sha256:' + 'b' * 64,
    ]
    assert not Path(env['FAKE_DEPLOY_EVENT_LOG']).exists()
    assert not (root / 'config/deploy/prod.env').exists()
