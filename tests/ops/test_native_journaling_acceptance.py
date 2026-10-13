"""Native mechanism/refusal proof only; never a qualified Product PASS."""
from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import native_journaling_acceptance as journaling
from app.ops import native_journaling_acceptance_runner as runners
from app.ops import native_journaling_transport as transport
from app.ops import native_web_acceptance as web
from app.ops import pg_acceptance as pg
from app.ops import postgres_deploy_linux as linux
from app.ops.postgres_deploy import DeployJournal, DeployPlan
from tests.deploy.test_postmerge_pg_acceptance import DIGEST, IMAGE_ID, DockerBoundary, _repository, _result


def binding() -> dict:
    return {**journaling.identity('a' * 40, DIGEST, 'test', str(uuid4())),
            'resource_generation': str(uuid4()), 'resource_tree': 'b' * 40, 'app_image_id': IMAGE_ID}


def report(bound: dict) -> dict:
    return {'schema': 'conversational_journaling_execution.v1', 'run_id': bound['resource_generation'],
            'fixture_id': 'jrnl-' + bound['resource_generation'], 'actor_id': journaling.ACTOR, 'channel': 'test',
            'for_date': date.today().isoformat(), 'expected_sha': bound['source_sha'], 'observed_sha': bound['source_sha'],
            'expected_image_digest': DIGEST, 'observed_image_digest': DIGEST, 'feature_acceptance': 'PASS',
            'scenarios': [{'name': name, 'outcome': 'passed', 'detail': 'contract fixture'} for name in journaling.SCENARIOS],
            'effects': dict(journaling.EFFECTS), 'limitation': None,
            'artifacts': {**dict.fromkeys(('primary_transcript_sha256', 'second_transcript_sha256',
                'primary_candidate_sha256', 'addendum_candidate_sha256', 'canonical_before_sha256',
                'canonical_after_sha256'), 'f' * 64), 'acceptance_receipt_id': 'contract-receipt'}}


def _runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, _sha = _repository(tmp_path)
    for selector in (*web.WRAPPERS, journaling.WRAPPER):
        path = root / selector.split('::')[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# exact wrapper\n')
    subprocess.run(['git', '-C', str(root), 'add', 'tests'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '-m', 'wrappers'], check=True, capture_output=True)
    sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    runner = runners.NativeJournalingRunner(root, tmp_path / 'journal', sha=sha, digest=DIGEST,
                                            channel='test', operation_id=str(uuid4()))
    boundary = DockerBoundary(runner)
    def docker(*args, timeout=60):
        output = boundary.command(*args, timeout=timeout)
        if args[:2] == ('image', 'inspect'):
            image = json.loads(output)[0]
            image.update(Os='linux', Architecture='amd64')
            image['Config']['Env'] = ['VCS_REF=' + sha]
            return json.dumps([image]).encode()
        return output
    monkeypatch.setattr(runner, '_docker', docker)
    return runner, boundary


def test_fixed_entrypoint_owns_manifest_and_refuses_caller_control(tmp_path, monkeypatch):
    runner, _boundary = _runner(tmp_path, monkeypatch)
    journal = DeployJournal(tmp_path / 'native-journal', 'test')
    operation = runner.identity['operation_id']
    plan = DeployPlan('test', runner.identity['source_sha'], ('db', 'api'), ('postgres-db', 'postgres-api'),
                     image_digest=DIGEST, automatic=True)
    journal.bind_request(operation, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'authenticating', 'activating', 'verifying'):
        journal.write(operation, stage)
    journal.write(operation, 'committed', _result(plan.revision, 'test', operation))
    config = SimpleNamespace(root=runner.repository, journal=journal, channel='test')
    effects = linux.LinuxEffects(config)
    effects.operation_id, effects.lock_fd = operation, 123
    monkeypatch.setattr(linux, '_private_json', lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(linux, 'ensure_candidate_object', lambda _config, _sha: None)
    calls = []
    monkeypatch.setattr(runners, 'NativeJournalingRunner', lambda *args, **kwargs: (
        calls.append(kwargs) or SimpleNamespace(verify=lambda: {**runner.identity, 'result': 'refused',
            'reason': 'actual_product_provider_references_unavailable', 'cleanup': 'confirmed'})))
    outcome = effects.qualify_journaling(operation)
    assert outcome['result'] == 'refused' and len(calls) == 1
    assert calls[0] == {'sha': plan.revision, 'digest': DIGEST, 'channel': 'test', 'operation_id': operation}
    assert journal.read().pg_acceptance == _result(plan.revision, 'test', operation)
    for key in ('command', 'profile', 'selector', 'fixture_path', 'provider', 'effect_budget', 'manifest'):
        with pytest.raises(TypeError):
            effects.qualify_journaling(operation, **{key: 'caller-controlled'})
    for channel, lock, op in (('prod', 123, operation), ('dev', 123, operation),
                              ('test', None, operation), ('test', 123, str(uuid4()))):
        config.channel, effects.lock_fd = channel, lock
        with pytest.raises(web.NativeWebRefusal):
            effects.qualify_journaling(op)
    assert len(calls) == 1


def test_actual_image_runner_uses_canonical_sources_and_product_provider(tmp_path, monkeypatch):
    from app.write_guard import DEFAULT_WRITE_GUARD
    from app.journaling.day_context import assemble_day_context
    from app.vault.manager import get_vault_manager
    bound = binding()
    monkeypatch.setattr(journaling, 'VAULT', tmp_path / 'vault')
    monkeypatch.setattr(journaling, 'EVIDENCE', tmp_path / 'evidence')
    monkeypatch.setattr(journaling, 'MANIFEST', tmp_path / 'manifest.json')
    monkeypatch.setenv('VAULT_ROOT', str(tmp_path / 'vault'))
    # This test bounds canonical producer mechanics; its health fixture cannot
    # produce qualified evidence and is not part of the native candidate code.
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'healthy'})
    fixture = journaling.bootstrap(bound)
    bundle = assemble_day_context(vault_context=get_vault_manager().context, for_date=date.today())
    assert set(bundle.sections) == {'commitments', 'decision_receipts', 'captures'}
    assert all(section.status == 'available' and section.items for section in bundle.sections.values())
    assert fixture['actor_id'] == journaling.ACTOR and fixture['sources']
    from tests.journaling.live_journaling_acceptance import load_manifest
    manifest = load_manifest(tmp_path / 'manifest.json')
    assert manifest.effect_budget == journaling.EFFECTS and manifest.expected_sha == bound['source_sha']
    assert not list((tmp_path / 'vault').glob('**/journal/*.md'))
    with pytest.raises(web.NativeWebRefusal, match='not_fresh'):
        journaling.bootstrap(bound)
    runner, boundary = _runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runners, 'selected_references', lambda: (_ for _ in ()).throw(
        web.NativeWebRefusal('actual_product_provider_references_unavailable')))
    result = runner.verify()
    assert result['result'] == 'refused' and result['cleanup'] == 'confirmed'
    assert result['reason'] == 'actual_product_provider_references_unavailable'
    assert not any(args[0] == 'create' for args, _ in boundary.commands)


def test_complete_journey_and_effect_inventory_cannot_false_green():
    bound = binding()
    original = report(bound)
    journaling.require_report(original, bound)
    for fault in ('missing', 'skip', 'duplicate', 'reorder', 'zero', 'over', 'bool', 'overwrite', 'receipt'):
        changed = copy.deepcopy(original)
        if fault == 'missing':
            changed['scenarios'].pop()
        elif fault == 'skip':
            changed['scenarios'][1]['outcome'] = 'not_run'
        elif fault == 'duplicate':
            changed['scenarios'][-1] = changed['scenarios'][0]
        elif fault == 'reorder':
            changed['scenarios'].reverse()
        elif fault in {'zero', 'over', 'bool'}:
            changed['effects']['canonical_accepts'] = {'zero': 0, 'over': 2, 'bool': True}[fault]
        elif fault == 'overwrite':
            changed['artifacts']['canonical_after_sha256'] = 'e' * 64
        else:
            changed['artifacts'].pop('acceptance_receipt_id')
        with pytest.raises(web.NativeWebRefusal):
            journaling.require_report(changed, bound)
    plugin = journaling.RequiredJournalingResults()
    plugin.pytest_runtest_logreport(SimpleNamespace(skipped=False, failed=False, when='call', passed=True,
                                                   nodeid=journaling.WRAPPER))
    plugin.require_complete(0)
    plugin.pytest_runtest_logreport(SimpleNamespace(skipped=True, failed=False, when='setup', passed=False,
                                                   nodeid=journaling.WRAPPER))
    with pytest.raises(web.NativeWebRefusal):
        plugin.require_complete(0)
    observer = journaling.EffectObserver()
    with pytest.raises(web.NativeWebRefusal, match='observed_effects_incomplete'):
        observer.require_complete(original)


def test_evidence_identity_and_owned_cleanup_are_atomic_or_refused(tmp_path, monkeypatch):
    bound = binding()
    for key in ('run_id', 'fixture_id', 'actor_id', 'expected_sha', 'observed_image_digest', 'schema'):
        changed = report(bound)
        changed[key] = 'foreign'
        with pytest.raises(web.NativeWebRefusal):
            journaling.require_report(changed, bound)
    target = tmp_path / 'receipt.json'
    journaling.private_json(target, {'result': 'refused'})
    with pytest.raises(FileExistsError):
        journaling.private_json(target, {'result': 'passed'})
    assert json.loads(target.read_text()) == {'result': 'refused'}
    runner, boundary = _runner(tmp_path, monkeypatch)
    runner.resources(IMAGE_ID)
    owner = json.loads(runner.marker.read_text())
    owner['resource_generation'] = str(uuid4())
    runner.marker.write_text(json.dumps(owner))
    result = runner.verify()
    assert result['result'] == 'unknown' and result['cleanup'] == 'unknown'
    assert runner.marker.exists() and runner.directory.exists()
    assert not any(args[0] == 'rm' for args, _ in boundary.commands)


def test_complete_retention_requires_original_report_and_junit(tmp_path, monkeypatch):
    runner, _boundary = _runner(tmp_path, monkeypatch)
    runner.resources(IMAGE_ID)
    bound = {**runner.identity, 'resource_tree': 'd' * 40, 'app_image_id': IMAGE_ID}
    original = report(bound)
    def copy_artifact(*args, timeout=60):
        assert args[0] == 'cp'
        target = Path(args[-1])
        if target.name == 'report.json':
            target.write_text(json.dumps(original))
        else:
            target.write_text('<testsuites><testsuite><testcase name="test_conversational_journaling_live_acceptance" '
                              'classname="tests.journaling.test_conversational_journaling_live_acceptance" />'
                              '</testsuite></testsuites>')
        return b''
    monkeypatch.setattr(runner, '_docker', copy_artifact)
    retained = runner._retain('owned-container', bound)
    assert retained['report'] == original
    directory = Path(retained['artifacts']['directory'])
    assert set(retained['artifacts']['files']) == {'report.json', 'junit.xml'}
    assert not directory.with_name(directory.name + '.pending').exists()
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / 'report.json').stat().st_mode & 0o777 == 0o600
    runner.identity['resource_generation'] = str(uuid4())
    bound['resource_generation'] = runner.identity['resource_generation']
    original = report(bound)
    original['scenarios'][-1]['outcome'] = 'failed'
    with pytest.raises(web.NativeWebRefusal):
        runner._retain('owned-container', bound)
    failed_final = directory.parent / (runner.identity['operation_id'] + '-' + runner.identity['resource_generation'])
    assert not failed_final.exists()
    assert directory.exists()  # Earlier complete evidence is never overwritten.


def test_existing_native_web_and_pg_contracts_remain_independent():
    assert web.WEB_PROFILE == 'native-web-pilots.v1'
    assert web.PILOT_ORDER == ('daily-briefing', 'deep-review')
    assert len(web.WRAPPERS) == 2 and journaling.WRAPPER not in web.WRAPPERS
    assert pg.PROFILE_VERSION == 'postmerge-pg.v1'
    assert journaling.PROFILE not in {web.WEB_PROFILE, pg.PROFILE_VERSION}
    bound = binding()
    with pytest.raises(pg.PgAcceptanceError):
        pg.require_pass({**bound, 'result': 'passed'}, bound['source_sha'], DIGEST, 'test', bound['operation_id'])
    with pytest.raises(web.NativeWebRefusal):
        web.require_reports(report(bound), bound)
    for channel in ('prod', 'dev'):
        with pytest.raises((web.NativeWebRefusal, pg.PgAcceptanceError)):
            journaling.identity('a' * 40, DIGEST, channel, str(uuid4()))


def test_provider_binding_refuses_missing_or_caller_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('MODEL_ACCESS_CODEX_VLAN_ENDPOINT', 'https://127.0.0.1/mock')
    monkeypatch.setattr(transport, 'REFERENCE_FILE', tmp_path / 'missing.env')
    with pytest.raises(web.NativeWebRefusal, match='references_unavailable'):
        transport.selected_references()
    (tmp_path / 'missing.env').symlink_to(tmp_path / 'foreign.env')
    with pytest.raises(web.NativeWebRefusal, match='references_unavailable'):
        transport.selected_references()
