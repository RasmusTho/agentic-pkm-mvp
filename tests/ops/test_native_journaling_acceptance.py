"""Native mechanism/refusal proof only; never a qualified Product PASS."""
from __future__ import annotations

import copy
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
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
from tests.ops.test_native_web_lock_lifecycle import admitted as admitted


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
    published = []
    original_publish, original_fsync = journaling.private_json, os.fsync
    def publish(path, value):
        original_publish(path, value)
        published.append(path)
    def sync_before_publication(descriptor):
        assert not published, 'no fallible sync after complete terminal publication'
        original_fsync(descriptor)
    monkeypatch.setattr(journaling, 'private_json', publish)
    monkeypatch.setattr(os, 'fsync', sync_before_publication)
    outcome = effects.qualify_journaling(operation)
    assert outcome['result'] == 'refused' and len(calls) == 1 and len(published) == 1
    monkeypatch.setattr(os, 'fsync', original_fsync)
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
        elif target.name == 'junit.xml':
            target.write_text('<testsuites><testsuite><testcase name="test_conversational_journaling_live_acceptance" '
                              'classname="tests.journaling.test_conversational_journaling_live_acceptance" />'
                              '</testsuite></testsuites>')
        else:
            target.write_text(json.dumps({'event': 'journal.entry.accepted', 'event_id': 'contract-receipt'}) + '\n')
        return b''
    monkeypatch.setattr(runner, '_docker', copy_artifact)
    retained = runner._retain('owned-container', bound)
    assert retained['report'] == original
    directory = Path(retained['artifacts']['directory'])
    assert set(retained['artifacts']['files']) == {'report.json', 'junit.xml', 'journal-review-outbox.jsonl'}
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


def test_owner_preparing_crash_recovers_exact_generation(tmp_path, monkeypatch):
    runner, boundary = _runner(tmp_path, monkeypatch)
    runner.preparing.parent.mkdir(mode=0o700, parents=True)
    journaling.private_json(runner.preparing, runner.identity)
    recovered = runners.NativeJournalingRunner(runner.repository, tmp_path / 'journal',
        sha=runner.identity['source_sha'], digest=DIGEST, channel='test', operation_id=runner.identity['operation_id'])
    assert recovered.identity == runner.identity
    monkeypatch.setattr(recovered, '_docker', boundary.command)
    recovered.cleanup()
    assert not recovered.preparing.exists()
    journaling.private_json(recovered.preparing, {**runner.identity, 'source_sha': 'f' * 40})
    with pytest.raises(web.NativeWebRefusal, match='foreign_resource_owner'):
        runners.NativeJournalingRunner(runner.repository, tmp_path / 'journal', sha=runner.identity['source_sha'],
                                      digest=DIGEST, channel='test', operation_id=runner.identity['operation_id'])
    assert recovered.preparing.exists()


def test_unknown_relay_cleanup_never_retires_channel_admission(request, tmp_path, monkeypatch):
    runner, _boundary = _runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, '_execute', lambda: (_ for _ in ()).throw(
        web.NativeWebRefusal('native_provider_transport_cleanup_unknown')))
    unknown = runner.verify()
    assert unknown['result'] == 'unknown' and unknown['cleanup'] == 'unknown'
    effects, operation, lock = request.getfixturevalue('admitted')
    monkeypatch.setattr(effects, 'qualify_journaling', lambda _operation: unknown)
    with pytest.raises(linux.PostgresDeployError):
        effects.run_journaling_qualification(operation)
    assert lock.is_dir() and (lock / 'bws-owner').is_file()
    before = effects.config.journal.read().payload()
    with pytest.raises(web.NativeWebRefusal):
        effects.run_journaling_qualification(str(uuid4()))
    monkeypatch.setattr(effects, 'qualify_journaling', lambda _operation: {'result': 'refused', 'cleanup': 'confirmed'})
    assert effects.run_journaling_qualification(operation)['result'] == 'refused'
    assert not lock.exists() and effects.config.journal.read().payload() == before


def test_terminal_fsync_failure_leaves_no_pass_file(tmp_path, monkeypatch):
    target = tmp_path / 'terminal.json'
    original = os.fsync
    for fail_at, failure in ((1, OSError), (2, OSError), (2, KeyboardInterrupt)):
        calls = []
        def fail(descriptor):
            calls.append(descriptor)
            if len(calls) == fail_at:
                raise failure('injected durability failure')
            return original(descriptor)
        with monkeypatch.context() as context:
            context.setattr(journaling.os, 'fsync', fail)
            with pytest.raises(failure):
                journaling.private_json(target, {'result': 'passed', 'cleanup': 'confirmed'})
        if fail_at == 2:
            assert len(calls) == 3  # Durable invalidation after publication failure.
        assert not target.exists() and not list(tmp_path.glob('.terminal.json.*'))
    journaling.private_json(target, {'result': 'refused'})
    assert json.loads(target.read_text()) == {'result': 'refused'}


def test_journaling_refusal_is_not_native_web_evidence(monkeypatch, capsys):
    assert linux.main(['qualify-journaling', 'prod', str(uuid4())]) == 78
    outcome = json.loads(capsys.readouterr().out)
    assert outcome['profile_version'] == journaling.PROFILE and outcome['cleanup'] == 'not_started'
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: object())
    monkeypatch.setattr(linux, 'LinuxEffects', lambda _config: SimpleNamespace(
        _web_admission=lambda _operation: None,
        run_journaling_qualification=lambda _operation: (_ for _ in ()).throw(
            web.NativeWebRefusal('journaling_evidence_directory_unqualified'))))
    assert linux.main(['qualify-journaling', 'test', str(uuid4())]) == 78
    outcome = json.loads(capsys.readouterr().out)
    assert outcome['profile_version'] == journaling.PROFILE
    assert outcome['result'] == 'unknown' and outcome['cleanup'] == 'unknown'


@pytest.mark.parametrize('failure_point', ['link_ack', 'staging_cleanup'])
def test_terminal_ambiguous_link_and_cleanup_leave_absence_not_pass(tmp_path, monkeypatch, failure_point):
    target = tmp_path / 'terminal.json'
    original_link, original_unlink = os.link, Path.unlink
    faults = []
    def ambiguous_link(*args, **kwargs):
        original_link(*args, **kwargs)
        faults.append('link')
        raise KeyboardInterrupt('link happened; caller never acknowledged return')
    def interrupted_unlink(path, *args, **kwargs):
        if path.name.startswith('.terminal.json.') and not faults:
            faults.append('unlink')
            raise OSError('injected staging cleanup failure')
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as context:
        if failure_point == 'link_ack':
            context.setattr(os, 'link', ambiguous_link)
            failure = KeyboardInterrupt
        else:
            context.setattr(Path, 'unlink', interrupted_unlink)
            failure = OSError
        with pytest.raises(failure):
            journaling.private_json(target, {'result': 'passed', 'cleanup': 'confirmed'})
    assert len(faults) == 1 and not target.exists() and not list(tmp_path.glob('.terminal.json.*'))
    target.write_text('foreign evidence, never overwrite or remove')
    with pytest.raises(FileExistsError):
        journaling.private_json(target, {'result': 'passed', 'cleanup': 'confirmed'})
    assert target.read_text() == 'foreign evidence, never overwrite or remove'


def test_actual_product_observer_rejects_deterministic_provider_substitution(tmp_path, monkeypatch):
    from app.write_guard import DEFAULT_WRITE_GUARD
    from tests.journaling.test_live_journaling_acceptance_contract import _install_real_product_seams
    from tests.journaling import live_journaling_acceptance as live
    bound = binding()
    monkeypatch.setattr(journaling, 'VAULT', tmp_path / 'vault')
    monkeypatch.setattr(journaling, 'EVIDENCE', tmp_path / 'evidence')
    monkeypatch.setattr(journaling, 'MANIFEST', tmp_path / 'manifest.json')
    monkeypatch.setenv('VAULT_ROOT', str(tmp_path / 'vault'))
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'healthy'})
    fixture = journaling.bootstrap(bound)
    manifest = live.load_manifest(tmp_path / 'manifest.json')
    _install_real_product_seams(monkeypatch, manifest)
    observer = journaling.EffectObserver(root=Path(__file__).resolve().parents[2])
    sys.setprofile(observer.profile)
    try:
        produced = live.run_qualified_journey(manifest)
    finally:
        sys.setprofile(None)
    assert produced.feature_acceptance == 'PASS'  # Unit journey only; native must refuse it below.
    observed = observer.require_complete(produced.as_payload())
    assert observed['provider_calls'] == []
    candidate = {**bound, 'result': 'passed', 'wrapper': journaling.WRAPPER, 'report': produced.as_payload(),
                 'report_hash': web.hash_json(produced.as_payload()), 'effect_observer': observed, 'fixture': fixture,
                 'provider': {'execution_host_profile': 'profile.codex_remote_host', 'provider': 'codex_cli', 'model': 'unit-only'}}
    with pytest.raises(web.NativeWebRefusal, match='provider_calls_incomplete'):
        journaling.require_result(candidate, bound)
    candidate['effect_observer']['observed'][1]['cognition']['degraded'] = True
    with pytest.raises(web.NativeWebRefusal):
        journaling.require_result(candidate, bound)


def test_image_main_compiles_and_ingests_settings_before_model_admission(tmp_path, monkeypatch, capsys):
    from app.components.llm import fabric
    from app.settings import compiler, runtime
    from app.write_guard import DEFAULT_WRITE_GUARD
    bound = binding()
    bound['files'] = {journaling.WRAPPER.split('::')[0]: 'a' * 64}
    resource = tmp_path / 'resources.json'
    journaling.private_json(resource, bound)
    monkeypatch.setattr(journaling, 'VAULT', tmp_path / 'vault')
    monkeypatch.setattr(journaling, 'EVIDENCE', tmp_path / 'evidence')
    monkeypatch.setattr(journaling, 'MANIFEST', tmp_path / 'manifest.json')
    monkeypatch.setattr(compiler, 'RUNTIME', tmp_path / 'runtime/settings')
    monkeypatch.setattr(runtime, 'RUNTIME', tmp_path / 'runtime/settings')
    monkeypatch.setattr(runtime, '_CURRENT', None)
    monkeypatch.setenv('VAULT_ROOT', str(tmp_path / 'vault'))
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'healthy'})
    # Resource/image and migration transport are unavailable in this local test;
    # canonical bootstrap, compiler and runtime ingestion remain real.
    monkeypatch.setattr(pg, 'verify_resources', lambda _binding: None)
    migrations = []
    monkeypatch.setattr(journaling.subprocess, 'run', lambda args, **kwargs: migrations.append(args))
    called = []
    def unavailable(_intent):
        assert (compiler.RUNTIME / 'llm_routing.yaml').is_file()
        assert runtime.get_settings_bundle().llm_routing.default_provider != 'mock'
        assert (tmp_path / 'manifest.json').is_file()
        called.append('actual_provider_admission_after_canonical_settings')
        raise web.NativeWebRefusal('actual_product_provider_unavailable')
    monkeypatch.setattr(fabric, 'get_chat_client', unavailable)
    assert journaling.main(['--manifest', str(resource)]) == 78
    assert migrations == [[sys.executable, '-m', 'alembic', 'upgrade', 'head']]
    assert called == ['actual_provider_admission_after_canonical_settings']
    line = next(line for line in capsys.readouterr().out.splitlines() if line.startswith('YGGDRASIL_NATIVE_JOURNALING='))
    assert json.loads(line.split('=', 1)[1])['reason'] == 'actual_product_provider_unavailable'
    assert not list((tmp_path / 'vault').glob('**/journal/*.md'))


def test_passive_interaction_observer_refuses_foreign_producer_origin():
    from app.chat.reflection_conversation import ReflectionConversationService
    observer = journaling.EffectObserver(root=Path(__file__).resolve().parents[2])
    foreign = ReflectionConversationService.start.__code__.replace(co_filename='/foreign/interaction.py')
    with pytest.raises(web.NativeWebRefusal, match='order_or_origin_invalid'):
        observer.profile(SimpleNamespace(f_code=foreign, f_locals={}), 'call', None)
    assert observer.order == [] and observer.observed == []


def test_native_container_command_is_fixed_and_namespace_drift_refuses_before_product(tmp_path, monkeypatch):
    runner, boundary = _runner(tmp_path, monkeypatch)
    refs = {transport.REFERENCE_KEYS[0]: 'https://10.0.0.8:8123'}
    for key in transport.REFERENCE_KEYS[1:]:
        source = tmp_path / key
        source.write_text('unit-only certificate fixture; never a provider PASS')
        refs[key] = str(source)
    monkeypatch.setattr(runners, 'selected_references', lambda: refs)
    original_docker = runner._docker
    def docker(*args, timeout=60):
        output = original_docker(*args, timeout=timeout)
        if args[0] == 'create':
            name = args[args.index('--name') + 1]
            row = boundary.containers[name]
            row['HostConfig']['SecurityOpt'] = ['no-new-privileges']
            if name.endswith('-tests'):
                row['Config']['Entrypoint'] = ['/usr/bin/env']
                row['Config']['Cmd'] = list(args[args.index(runner.image) + 1:])
            else:
                row['State'] = {'Pid': 123, 'Running': True}
                row['NetworkSettings'] = {'SandboxKey': '/foreign/namespace'}
        return output
    monkeypatch.setattr(runner, '_docker', docker)
    outcome = runner.verify()
    assert outcome['result'] == 'refused' and outcome['cleanup'] == 'confirmed'
    assert outcome['reason'] == 'database_namespace_identity_unknown'
    assert not boundary.containers
    command = runner._candidate_command
    assert command[-5:] == ['python', '-m', 'app.ops.native_journaling_acceptance',
                            '--manifest', '/native-journaling-manifest.json']
    assert command[0] == '-i'
    assert not any(value.startswith(('LLM_PROVIDER=', 'LLM_FORCE_PROVIDER=', 'BWS_ACCESS_TOKEN=')) for value in command)
    creations = [args for args, _ in boundary.commands if args[0] == 'create']
    app = next(args for args in creations if args[args.index('--name') + 1].endswith('-tests'))
    mounts = [app[index + 1] for index, value in enumerate(app) if value == '--mount']
    assert all('readonly' in mount and '/app/app' not in mount and 'docker.sock' not in mount for mount in mounts)
    assert not any(args[:2] == ('start', '--attach') for args, _ in boundary.commands)


def test_provider_relay_forwards_unchanged_bytes_and_confirms_own_worker_exit():
    import socket
    from threading import Thread
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    def echo():
        with server.accept()[0] as remote:
            remote.settimeout(3)
            data = remote.recv(4096)
            remote.sendall(data)
    remote_worker = Thread(target=echo)
    remote_worker.start()
    relay = transport.ProviderRelay(0, 'https://127.0.0.1:' + str(server.getsockname()[1]))
    # Exercise the real forwarding/stop loop, without changing a host namespace
    # or making a Product/provider acceptance claim.
    relay.listener = socket.socket()
    relay.listener.bind(('127.0.0.1', 0))
    relay.listener.listen(1)
    relay.listener.settimeout(0.2)
    relay.worker = Thread(target=relay._run)
    relay.worker.start()
    payload = b'unit-only opaque TLS-like bytes'
    try:
        with socket.create_connection(relay.listener.getsockname(), timeout=3) as client:
            client.sendall(payload)
            assert client.recv(4096) == payload
    finally:
        relay.__exit__()
        server.close()
        remote_worker.join(timeout=3)
    observed = relay.readback()
    assert observed['connections'] == 1 and observed['bytes'] == len(payload) * 2
    assert not relay.worker.is_alive() and not remote_worker.is_alive()


def test_provider_relay_unknown_worker_exit_is_never_complete():
    relay = transport.ProviderRelay(0, 'https://10.0.0.8:8123')
    relay.worker = SimpleNamespace(join=lambda **kwargs: None, is_alive=lambda: True)
    relay.listener = SimpleNamespace(close=lambda: None)
    with pytest.raises(web.NativeWebRefusal, match='cleanup_unknown'):
        relay.__exit__()
    with pytest.raises(web.NativeWebRefusal, match='transport_incomplete'):
        relay.readback()


def test_interrupted_relay_and_fresh_runner_keep_exact_owner_admission(tmp_path, monkeypatch):
    runner, boundary = _runner(tmp_path, monkeypatch)
    runner.resources(IMAGE_ID)
    process = {'pid': 123, 'boot_id': str(uuid4()), 'start_ticks': '100'}
    monkeypatch.setattr(runners, 'process_identity', lambda _pid: process)
    monkeypatch.setattr(transport, 'process_identity', lambda _pid: process)
    runner._relay_owner()
    relay = transport.ProviderRelay(0, 'https://10.0.0.8:8123')
    closed = []
    def interrupted(**kwargs):
        raise KeyboardInterrupt()
    relay.worker = SimpleNamespace(join=interrupted, is_alive=lambda: True)
    relay.listener = SimpleNamespace(close=lambda: closed.append(True))
    with pytest.raises(KeyboardInterrupt):
        relay.__exit__()
    assert closed == [True] and not relay.cleanup_confirmed
    recovered = runners.NativeJournalingRunner(runner.repository, tmp_path / 'journal',
        sha=runner.identity['source_sha'], digest=DIGEST, channel='test', operation_id=runner.identity['operation_id'])
    monkeypatch.setattr(recovered, '_docker', boundary.command)
    assert recovered.identity == runner.identity
    with pytest.raises(web.NativeWebRefusal, match='cleanup_unknown'):
        recovered.cleanup()
    assert runner.marker.exists() and (runner.directory / 'relay-owner.json').exists()
    # Kernel readback proves the exact owner departed; never kill by PID.
    monkeypatch.setattr(transport, 'process_identity', lambda _pid: None)
    recovered.cleanup()
    assert not runner.marker.exists() and not runner.directory.exists()


def test_deadline_exhaustion_cannot_consume_late_pass_logs(tmp_path, monkeypatch):
    runner, boundary = _runner(tmp_path, monkeypatch)
    refs = {transport.REFERENCE_KEYS[0]: 'https://10.0.0.8:8123'}
    for key in transport.REFERENCE_KEYS[1:]:
        source = tmp_path / key
        source.write_text('unit-only certificate fixture')
        refs[key] = str(source)
    monkeypatch.setattr(runners, 'selected_references', lambda: refs)
    native_owner = {'pid': 123, 'boot_id': str(uuid4()), 'start_ticks': '100'}
    monkeypatch.setattr(runners, 'process_identity', lambda _pid: native_owner)
    namespace_file = tmp_path / 'namespace-inode'
    namespace_file.write_text('unit-only inode identity; no namespace effects')
    original_open, original_stat, original_docker = os.open, os.stat, runner._docker
    monkeypatch.setattr(runners.os, 'open', lambda path, *args, **kwargs:
        original_open(namespace_file if path == '/var/run/docker/netns/unit' else path, *args, **kwargs))
    monkeypatch.setattr(runners.os, 'stat', lambda path, *args, **kwargs:
        original_stat(namespace_file if path == '/proc/123/ns/net' else path, *args, **kwargs))
    class QuietRelay:
        cleanup_confirmed = False
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.cleanup_confirmed = True
    monkeypatch.setattr(runners, 'ProviderRelay', QuietRelay)
    def docker(*args, timeout=60):
        if args[:2] == ('start', '--attach'):
            raise pg.PgAcceptanceDeadlineExceeded()
        if args[0] == 'logs':
            pytest.fail('deadline must never substitute late PASS logs')
        output = original_docker(*args, timeout=timeout)
        if args[0] == 'create':
            name = args[args.index('--name') + 1]
            row = boundary.containers[name]
            row['HostConfig']['SecurityOpt'] = ['no-new-privileges']
            if name.endswith('-tests'):
                row['Config']['Entrypoint'] = ['/usr/bin/env']
                row['Config']['Cmd'] = list(args[args.index(runner.image) + 1:])
            else:
                row['State'] = {'Pid': 123, 'Running': True}
                row['NetworkSettings'] = {'SandboxKey': '/var/run/docker/netns/unit'}
        return output
    monkeypatch.setattr(runner, '_docker', docker)
    outcome = runner.verify()
    assert outcome['result'] == 'refused' and outcome['reason'] == 'journaling_deadline_exceeded'
    assert outcome['cleanup'] == 'confirmed' and not boundary.containers
    assert not runner.marker.exists() and not runner.directory.exists()
