"""Production envelope/producer proof; these doubles establish no live PASS."""
from __future__ import annotations

import hashlib
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import native_web_acceptance as web
from app.ops import native_web_acceptance_runner as runners
from app.ops import native_web_fixture as fixture
from app.ops import pg_acceptance as pg
from app.ops import postgres_deploy_linux as linux
from app.ops.postgres_deploy import DeployJournal, DeployPlan
from tests.deploy.test_postmerge_pg_acceptance import DIGEST, IMAGE_ID, DockerBoundary, _repository, _result
from tests.api.conftest import mock_product_api_routes as mock_product_api_routes


def _reports(binding=None):
    binding = binding or {'source_sha': 'a' * 40, 'image_digest': DIGEST, 'channel': 'test', 'run_id': str(uuid4()),
                          'resource_version': 'b' * 40, 'native_boundary_ref': 'c' * 64,
                          'fixture_metadata_sha256': 'd' * 64, 'local_instance_id': 'local-test',
                          'harness_hashes': {'live_deep_review.py': 'e' * 64, 'live_core_flow.py': 'f' * 64},
                          'manifest_sha256': 'a' * 64, 'configuration_hashes': {'runtime': 'b' * 64, 'vault': 'a' * 64}}
    deep = {'schema': 'companion_ui_deep_review_execution.v1', 'execution_kind': 'live', 'channel': 'test',
            'expected_sha': binding['source_sha'], 'expected_image_digest': binding['image_digest'],
            'run_id': binding['run_id'], 'test_resource_version': binding['resource_version'],
            'qualification_ref': binding['native_boundary_ref'], 'fixture_metadata_sha256': binding['fixture_metadata_sha256'],
            'local_instance_id': binding['local_instance_id'], 'harness_hashes': binding['harness_hashes'],
            'manifest_sha256': binding['manifest_sha256'], 'required_scenarios': list(web.SCENARIOS['deep-review']),
            'identity_verified': True, 'refused_requests': [], 'effects': dict(web.EFFECT_LIMITS['deep-review']),
            'effect_budget': dict(web.EFFECT_LIMITS['deep-review']), 'artifacts': {'trace': 'trace.zip', 'junit': 'junit.xml'},
            'passed': True, 'scenarios': []}
    native = {key: True for key in ('gateway_upstream_verified', 'synthetic_fixture_verified', 'native_lock_verified', 'first_contact_navigation_safe')}
    native.update(image_digest=binding['image_digest'], test_resource_version=binding['resource_version'], configuration_hashes=binding['configuration_hashes'])
    ack = {'status': 'executed', 'outcome': 'success', 'receipt': {'receipt_id': 'test-receipt'}}
    capture = {'outcome': 'written', 'trace_id': 'test-capture'}
    proofs = {
        'native_admission': {'native': native, 'served_sha': binding['source_sha']},
        'a1_overlay_selection_continuity': {'cycles': 2, 'selection': {'start': 1}},
        'a1_runtime_resume_position': {'prior_view': {'artifact_id': 'test', 'note_path': 'note.md', 'start': 1, 'end': 2, 'editor_scroll': 3, 'reading_scroll': 4},
            'restored': {'start': 1, 'end': 2, 'editor_scroll': 3, 'reading_scroll': 4},
            'runtime_leave_point': {'status': 'present', 'artifact_ref': {'artifact_uuid': 'test', 'logical_ref': 'note.md'}}},
        'b4_all_overlay_focus_escape_return': {'overlays': {k: {'focus_trap': True, 'escape': True, 'focus_return': True} for k in ('cmd', 'capture', 'receipts', 'settings', 'memory', 'map')}},
        'populated_vault_list_and_inspector': {'note_uuid': 'test', 'list_count': 1, 'inspector': True},
        'populated_governed_apply_exact_receipt': {'confirmation': ack, 'exact_persisted_readback': True, 'receipt_history': True},
        'populated_capture_confirmation_and_caret': {'capture': capture, 'source_readback': True, 'selection_restored': True},
        'public_copy_populated_and_entry': {'surfaces': ['shell', 'entry', 'cmd', 'memory', 'receipts', 'settings', 'map'], 'public_copy_clean': True},
        'public_copy_degraded': {'kind': 'browser_fault_injection', 'calm_unavailable': True},
    }
    for action, status in {'accept': 'accepted', 'reject': 'rejected', 'revise': 'revised', 'defer': 'deferred'}.items():
        proofs['populated_memory_' + action] = {'decision': {'status': status}, 'actual_pending_ids': [], 'server_authority': {'observed': True}}
    deep['scenarios'] = [{'id': name, 'status': 'passed', 'kind': 'browser_fault_injection' if name == 'public_copy_degraded' else 'actual',
                          'proof': {'source': 'served_product', **proofs[name]}} for name in web.SCENARIOS['deep-review']]
    deep['actual_proof'] = {'native': native}
    deep['backend_acknowledgements'] = {'panel_confirm': ack, 'capture': capture}
    daily = {'schema': 'daily_briefing_live_acceptance.v1', 'execution_kind': 'actual_native_browser', 'channel': 'test',
             'expected_sha': binding['source_sha'], 'expected_digest': binding['image_digest'], 'run_id': binding['run_id'],
             'resource_version': binding['resource_version'], 'native_boundary_ref': binding['native_boundary_ref'],
             'fixture_restored': True, 'trace': 'trace.zip', 'junit': 'junit.xml', 'passed': True,
             'effects_consumed': dict(web.EFFECT_LIMITS['daily-briefing']),
             'scenarios': [{'id': key, 'status': 'passed', 'kind': 'browser_local_failure' if key == 'text_only_degradation' else 'actual'} for key in web.SCENARIOS['daily-briefing']],
             'diagnostics': {'audio': {'playback_observed': True, 'frames': 12, 'sample_rate': 24000, 'audio_sha256': 'a' * 64,
                 'source_text_sha256': 'b' * 64, 'cache_key': 'c' * 64,
                 'segments': [{'language': 'sv-SE', 'provider': 'piper', 'voice_id': 'sv_SE-lisa-medium'},
                              {'language': 'en-US', 'provider': 'kokoro', 'voice_id': 'bf_isabella'}]}}}
    return {'deep-review': deep, 'daily-briefing': daily}


class WebBoundary(DockerBoundary):
    def command(self, *arguments, timeout=60):
        if arguments[:2] == ('start', '--attach'):
            self.commands.append((arguments, timeout))
            if self.fault == 'interrupt':
                raise KeyboardInterrupt()
            manifest = json.loads((self.runner.directory / 'source/native-web-manifest.json').read_text())
            row = self.containers[self.runner.name + '-tests']
            row['State'] = {'Running': False, 'ExitCode': 0}
            api = {key: manifest[key] for key in ('source_sha', 'image_digest', 'app_image_id', 'resource_tree', 'resource_generation')}
            api.update(api_module='/app/app/main.py', api_pid=42, browser_audio_assets_hash=web.hash_json(manifest['prerequisites']),
                       fixture={'resource_generation': manifest['resource_generation'], 'note_sha256': 'a' * 64,
                                'settings_hash': 'a' * 64, 'candidate_ids': list(fixture.CANDIDATE_IDS),
                                'logical_vault_id': 'synthetic-vault', 'local_clone_id': 'synthetic-clone',
                                'note_uuid': fixture.NOTE_UUID, 'note_path': fixture.NOTE_PATH,
                                'daily': {'date': '2026-10-11', 'briefing_path': 'System/briefings/2026-10-11.md',
                                          'moment_path': 'System/moments/daily.md', 'source_files': {'System/moments/daily.md': 'a' * 64}},
                                'controlled_mutable_sources': [
                                    {'note_uuid': uid, 'note_path': path, 'effect': effect, 'seed_sha256': 'a' * 64}
                                    for uid, path, effect in ((fixture.REVIEW_NOTE_UUID, fixture.REVIEW_NOTE_PATH, 'panel_confirm'),
                                        (fixture.CAPTURE_NOTE_UUID, fixture.CAPTURE_NOTE_PATH, 'capture'))]})
            observation = {'api': api, 'ui_pid': 43, 'configuration_hash': 'b' * 64,
                           'ui_program_sha256': manifest['files']['companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py']}
            from app.ops.native_web_reports import report_binding
            self.pilots = _reports(report_binding(manifest, observation))
            if self.fault == 'report_missing':
                for value in self.pilots.values():
                    value.pop('schema')
            if self.fault == 'report_foreign':
                for value in self.pilots.values():
                    value.update(schema='foreign', execution_kind='deterministic_fixture', channel='prod',
                                 expected_sha='f' * 40, expected_digest='sha256:' + 'f' * 64, run_id='foreign')
                    for scenario in value['scenarios']:
                        scenario['proof'] = None
            if self.fault == 'report_zero_effects':
                for pilot, value in self.pilots.items():
                    value['effects' if pilot == 'deep-review' else 'effects_consumed'] = dict.fromkeys(web.EFFECT_LIMITS[pilot], 0)
            if self.fault == 'report_no_proof':
                self.pilots['deep-review']['scenarios'][0]['proof'] = None
            if self.fault == 'report_audio':
                self.pilots['daily-briefing']['diagnostics']['audio']['playback_observed'] = False
            if self.fault == 'report_native_config':
                self.pilots['deep-review']['actual_proof']['native']['configuration_hashes'] = {'foreign': 'f' * 64}
            result = {**self.runner.identity, 'result': 'passed', 'wrappers': list(web.WRAPPERS),
                      'resource_tree': manifest['resource_tree'], 'app_image_id': IMAGE_ID,
                      'start': observation, 'end': observation,
                      'pilots': self.pilots, 'report_hash': web.hash_json(self.pilots)}
            sources = observation['api']['fixture']['controlled_mutable_sources']
            result['mutable_versions'] = {source['note_path']: 'c' * 64 for source in sources}
            result['guarded_acknowledgements'] = {source['effect']: {
                'target': source['note_path'], 'source_uuid': source['note_uuid'],
                'pre_sha256': source['seed_sha256'], 'post_sha256': 'c' * 64,
                'response_sha256': web.hash_json(self.pilots['deep-review']['backend_acknowledgements'][source['effect']]),
            } for source in sources}
            if self.fault == 'report_ack_foreign':
                result['guarded_acknowledgements']['capture']['response_sha256'] = 'f' * 64
            daily = api['fixture']['daily']
            target, date = daily['briefing_path'], daily['date']
            contacts = {key: {'target': target, 'date': date, 'triggered': key == 'first_contact:1',
                'reason': 'first_contact' if key == 'first_contact:1' else 'already_generated_today',
                'pre_sha256': None if key == 'first_contact:1' else 'c' * 64, 'post_sha256': 'c' * 64,
                'response_sha256': web.hash_json({'date': date, 'triggered': key == 'first_contact:1'}),
                'degraded_sections': []} for key in ('first_contact:1', 'first_contact:2', 'navigation:1', 'navigation:2', 'navigation:3', 'navigation:4')}
            result['daily_briefing_state'] = {'target': target, 'date': date, 'initial_absent': True,
                'version': 'c' * 64, 'healthy_version': 'c' * 64, 'contacts': contacts,
                'scheduled_replay': {'target': target, 'date': date, 'triggered': False, 'reason': 'already_generated_today',
                                     'briefing_sha256': 'c' * 64, 'durable_writes': 0}}
            faults = {effect: {'target': daily['moment_path'], 'receipt': {'operation': 'write_note', 'outcome': 'written', 'locator': {'path': daily['moment_path']}},
                'source_writes': 1, 'regenerations': 1, 'pre_sha256': ('a' if effect == 'degrade_source' else 'd') * 64,
                'post_sha256': ('d' if effect == 'degrade_source' else 'a') * 64,
                'regeneration': {'target': target, 'receipt': {'operation': 'write_note', 'outcome': 'written', 'locator': {'path': target}},
                    'pre_sha256': ('c' if effect == 'degrade_source' else 'e') * 64, 'post_sha256': ('e' if effect == 'degrade_source' else 'c') * 64,
                    'degraded_sections': ['moments'] if effect == 'degrade_source' else []}} for effect in ('degrade_source', 'restore_source')}
            result['daily_source_acknowledgements'] = faults
            self.pilots['daily-briefing']['diagnostics'].update(generation={'briefing_path': target, 'briefing_sha256': 'c' * 64},
                partial_source=faults['degrade_source'], restoration=faults['restore_source'])
            if self.fault == 'daily_preexisting':
                result['daily_briefing_state']['contacts']['first_contact:1']['pre_sha256'] = 'c' * 64
            if self.fault == 'daily_scheduled_written':
                result['daily_briefing_state']['scheduled_replay']['durable_writes'] = 1
            if self.fault == 'daily_missing_regeneration':
                faults['degrade_source']['regenerations'] = 0
            if self.fault == 'daily_bad_degradation':
                faults['degrade_source']['regeneration']['degraded_sections'] = []
            if self.fault == 'daily_restore_drift':
                faults['restore_source']['regeneration']['post_sha256'] = 'f' * 64
            result['report_hash'] = web.hash_json(self.pilots)
            if self.fault == 'fixture_drift':
                result['end'] = {'service': 'drift'}
            if self.fault == 'missing_scenario':
                result['pilots']['deep-review']['scenarios'].pop()
                result['report_hash'] = web.hash_json(result['pilots'])
            return ('YGGDRASIL_NATIVE_WEB=' + json.dumps(result)).encode()
        if arguments[0] == 'cp':
            self.commands.append((arguments, timeout))
            pilot, filename = arguments[1].split('/')[-2:]
            target = Path(arguments[-1])
            if self.fault == 'artifacts_text' and filename != 'report.json':
                target.write_text('actual transport artifact')
                return b''
            if filename == 'report.json':
                target.write_text(json.dumps(self.pilots[pilot]))
            elif filename == 'junit.xml':
                suite = ET.Element('testsuite')
                for name in web.SCENARIOS[pilot]:
                    ET.SubElement(suite, 'testcase', name=name)
                if self.fault == 'junit_foreign':
                    suite[0].set('name', 'unrelated_test')
                ET.ElementTree(suite).write(target, encoding='utf-8')
            else:
                events = [{'type': 'context-options'}]
                for i in range(len(web.SCENARIOS[pilot])):
                    events.extend([{'type': 'before', 'callId': str(i), 'params': {'url': web.UI_URL}}, {'type': 'after', 'callId': str(i)}])
                with zipfile.ZipFile(target, 'w') as trace:
                    trace.writestr('test.trace', '\n'.join(json.dumps(x) for x in events))
            return b''
        if arguments[0] == 'rm' and self.fault == 'cleanup':
            raise pg.PgAcceptanceError()
        output = super().command(*arguments, timeout=timeout)
        if arguments[:2] == ('image', 'inspect'):
            image = json.loads(output)[0]
            image.update(Os='linux', Architecture='amd64')
            image['Config']['Env'] = ['VCS_REF=' + self.runner.identity['source_sha']]
            return json.dumps([image]).encode()
        if arguments[0] == 'create':
            name = arguments[arguments.index('--name') + 1]
            self.containers[name]['HostConfig']['SecurityOpt'] = ['no-new-privileges']
            if name.endswith('-tests'):
                self.containers[name]['Config']['Entrypoint'] = ['/usr/bin/env']
                self.containers[name]['Config']['Cmd'] = list(arguments[arguments.index(self.runner.image) + 1:])
        return output


def _consumer_result():
    """Pure schema fixture reaching the mandatory consumer, never live PASS."""
    identity = web.web_identity('a' * 40, DIGEST, 'test', str(uuid4()))
    identity['resource_generation'] = str(uuid4())
    manifest = {**identity, 'app_image_id': IMAGE_ID, 'resource_tree': 'b' * 40,
                'prerequisites': {'scope': 'pure-consumer-fixture'}, 'files': {
                    'companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py': 'c' * 64,
                    'tests/companion_ui/live_deep_review.py': 'd' * 64,
                    'tests/companion_ui/live_core_flow.py': 'e' * 64}}
    class ManifestDirectory:
        def __truediv__(self, _path):
            return self
        def read_text(self):
            return json.dumps(manifest)
    boundary = object.__new__(WebBoundary)
    boundary.runner = SimpleNamespace(identity=identity, name='pure-schema', directory=ManifestDirectory())
    boundary.commands, boundary.fault = [], None
    boundary.containers = {'pure-schema-tests': {}}
    result = json.loads(boundary.command('start', '--attach', 'pure-schema').decode().split('=', 1)[1])
    result['cleanup'] = 'confirmed'
    return result, identity, manifest


def _pair_daily_reports(result):
    diagnostics = result['pilots']['daily-briefing']['diagnostics']
    faults = result['daily_source_acknowledgements']
    diagnostics['partial_source'] = copy.deepcopy(faults['degrade_source'])
    diagnostics['restoration'] = copy.deepcopy(faults['restore_source'])
    result['report_hash'] = web.hash_json(result['pilots'])


@pytest.mark.parametrize('version', ['healthy', 'degraded'])
def test_mandatory_consumer_accepts_complete_healthy_and_degraded_replays(version):
    result, identity, manifest = _consumer_result()
    daily = result['daily_briefing_state']
    digest = daily['healthy_version'] if version == 'healthy' else result['daily_source_acknowledgements']['degrade_source']['regeneration']['post_sha256']
    for key, contact in daily['contacts'].items():
        if key != 'first_contact:1':
            contact.update(pre_sha256=digest, post_sha256=digest,
                           degraded_sections=[] if version == 'healthy' else ['moments'])
    _pair_daily_reports(result)
    web.require_result(result, identity, manifest)


@pytest.mark.parametrize('fault,reason', [
    ('foreign_initial_moment_hash', 'daily_actual_source_restore_version_mismatch'),
    ('missing_replay_hashes', 'daily_actual_generation_or_replay_unknown'),
    ('non_hash_intermediate_regeneration', 'daily_actual_source_regeneration_incomplete'),
    ('foreign_replay_version', 'daily_actual_generation_or_replay_unknown'),
])
def test_mandatory_consumer_refuses_paired_daily_lineage_counterexamples(fault, reason):
    result, identity, manifest = _consumer_result()
    web.require_result(result, identity, manifest)
    faults = result['daily_source_acknowledgements']
    contact = result['daily_briefing_state']['contacts']['first_contact:2']
    if fault == 'foreign_initial_moment_hash':
        faults['degrade_source']['pre_sha256'] = 'f' * 64
    elif fault == 'missing_replay_hashes':
        contact.pop('pre_sha256')
        contact.pop('post_sha256')
    elif fault == 'non_hash_intermediate_regeneration':
        faults['degrade_source']['regeneration']['post_sha256'] = 'not-a-state-hash'
        faults['restore_source']['regeneration']['pre_sha256'] = 'not-a-state-hash'
    else:
        contact.update(pre_sha256='f' * 64, post_sha256='f' * 64)
    _pair_daily_reports(result)
    assert result['pilots']['daily-briefing']['diagnostics']['partial_source'] == faults['degrade_source']
    assert result['pilots']['daily-briefing']['diagnostics']['restoration'] == faults['restore_source']
    with pytest.raises(web.NativeWebRefusal, match=reason):
        web.require_result(result, identity, manifest)


@pytest.mark.parametrize('key', ['first_contact:1', 'first_contact:2', 'navigation:1', 'navigation:2', 'navigation:3', 'navigation:4'])
def test_mandatory_consumer_requires_each_contact_version(key):
    result, identity, manifest = _consumer_result()
    result['daily_briefing_state']['contacts'][key].pop('post_sha256')
    _pair_daily_reports(result)
    with pytest.raises(web.NativeWebRefusal, match='daily_actual_generation_or_replay_unknown'):
        web.require_result(result, identity, manifest)


@pytest.mark.parametrize('effect', ['degrade_source', 'restore_source'])
@pytest.mark.parametrize('record', ['source', 'regeneration'])
@pytest.mark.parametrize('field', ['pre_sha256', 'post_sha256'])
def test_mandatory_consumer_requires_each_source_and_derived_version(effect, record, field):
    result, identity, manifest = _consumer_result()
    ack = result['daily_source_acknowledgements'][effect]
    (ack if record == 'source' else ack['regeneration'])[field] = None
    _pair_daily_reports(result)
    with pytest.raises(web.NativeWebRefusal, match='daily_actual_source_regeneration_incomplete'):
        web.require_result(result, identity, manifest)


def _runner(tmp_path, monkeypatch, *, wrappers=True):
    root, _sha = _repository(tmp_path)
    for selector in web.WRAPPERS if wrappers else ():
        path = root / selector.split('::')[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# exact fixed wrapper\n')
        subprocess.run(['git', '-C', str(root), 'add', str(path)], check=True, capture_output=True)
    for name in ('live_deep_review.py', 'live_core_flow.py'):
        path = root / 'tests/companion_ui' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# fixed original report producer resource fixture')
        subprocess.run(['git', '-C', str(root), 'add', str(path)], check=True, capture_output=True)
    ui = root / 'companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py'
    ui.parent.mkdir(parents=True)
    ui.write_text('# fixed UI source fixture')
    subprocess.run(['git', '-C', str(root), 'add', str(ui)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'fixed wrappers'], check=True, capture_output=True)
    sha = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    native = tmp_path / 'native-runtime'
    for package, version in {'playwright': '1.63.0', 'pyee': '13.0.1', 'greenlet': '3.5.6'}.items():
        packages = native / 'lib/python3.12/site-packages'
        (packages / package).mkdir(parents=True)
        (packages / package / '__init__.py').write_text('# pinned native package')
        metadata = packages / f'{package}-{version}.dist-info/METADATA'
        metadata.parent.mkdir()
        metadata.write_text(f'Version: {version}\n')
    browser = native / 'browsers/chromium_headless_shell-1243/chrome-linux/headless_shell'
    browser.parent.mkdir(parents=True)
    browser.write_text('qualified source binary fixture')
    browser.chmod(0o755)
    tts = tmp_path / 'existing-models'
    for name in runners.TTS_FILES:
        path = tts / 'models' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('already selected model fixture')
    monkeypatch.setattr(runners, 'BROWSER_RUNTIME', native)
    monkeypatch.setattr(runners, '_command', lambda _argv: json.dumps({
        'platform': 'linux', 'machine': 'x86_64', 'python_abi': 'cpython-312-x86_64-linux-gnu',
        'python_minor': [3, 12], 'prefix': str(native), 'playwright': '1.63.0',
    }).encode())
    runner = runners.NativeWebRunner(root, tmp_path / 'journal', sha=sha, digest=DIGEST,
                                    channel='test', operation_id=str(uuid4()), tts_root=tts)
    boundary = WebBoundary(runner)
    monkeypatch.setattr(runner, '_docker', boundary.command)
    return runner, boundary


def test_fixed_native_entrypoint_owns_actual_product_service(tmp_path, monkeypatch):
    runner, boundary = _runner(tmp_path, monkeypatch)
    journal = DeployJournal(tmp_path / 'native-journal', 'test')
    plan = DeployPlan('test', runner.identity['source_sha'], ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=DIGEST, automatic=True)
    operation = runner.identity['operation_id']
    journal.bind_request(operation, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'authenticating', 'activating', 'verifying'):
        journal.write(operation, stage)
    journal.write(operation, 'committed', _result(plan.revision, 'test', operation))
    runtime = tmp_path / 'runtime.env'
    runtime.write_text(f'TTS_ENABLED=true\nTTS_HOST_ROOT={runner.tts_root}\nBWS_ACCESS_TOKEN=foreign-secret\n')
    config = SimpleNamespace(root=runner.repository, journal=journal, channel='test', runtime_env_file=runtime)
    effects = linux.LinuxEffects(config)
    effects.operation_id = operation
    effects.lock_fd = 123
    monkeypatch.setattr(linux, '_private_json', lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(linux, 'ensure_candidate_object', lambda _cfg, _sha: None)
    monkeypatch.setattr(runners, 'NativeWebRunner', lambda *_args, **_kwargs: runner)
    result = effects.qualify_web(operation)
    assert result['result'] == 'passed' and result['cleanup'] == 'confirmed'
    commands = [args for args, _ in boundary.commands]
    create = next(args for args in commands if args[0] == 'create' and args[args.index('--name') + 1].endswith('-tests'))
    assert create[create.index('--network') + 1].startswith('container:')
    assert ('python', '-m', 'app.ops.native_web_acceptance') == create[-5:-2]
    assert create[-2:] == ('--manifest', '/native-web-manifest.json')
    assert '-i' in create and '--read-only' in create and 'foreign-secret' not in json.dumps(commands)
    assert all('/app/app' not in value and 'docker.sock' not in value and '/existing-models' not in value
               for value in create if value.startswith('type=bind'))
    assert result['artifacts']['daily-briefing']['files'].keys() == {'report.json', 'trace.zip', 'junit.xml'}
    assert journal.read().pg_acceptance == _result(plan.revision, 'test', operation)
    for lock, wrong_operation in ((None, operation), (123, str(uuid4()))):
        effects.lock_fd = lock
        with pytest.raises(web.NativeWebRefusal):
            effects.qualify_web(wrong_operation)
    with pytest.raises(TypeError):
        effects.qualify_web(operation, command=['anything'])


@pytest.mark.usefixtures('mock_product_api_routes')
def test_api_process_bootstrap_uses_canonical_producers(tmp_path, monkeypatch):
    from app.agent_memory.review_queue import MemoryCandidateReviewQueue
    from app.api.routes import companion
    from app.knowledge import write_ops
    from app.relevance import materialization
    from app.services import commitment_persistence
    from app.receipts import decision_receipt_log
    from app.episodes import notes
    from app.agent_memory import companion_aware
    from app.vault import manager
    from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

    monkeypatch.setenv('DESIGN_HANDOFF_APP_LOCAL_SETTINGS', str(tmp_path / 'app-local.md'))
    monkeypatch.setenv('VAULT_ROOT', str(tmp_path / 'vault'))
    monkeypatch.setattr(manager, '_GLOBAL_MANAGER', None)
    monkeypatch.setattr(companion, '_MEMORY_CANDIDATE_REVIEW_QUEUE', MemoryCandidateReviewQueue())
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'healthy'})
    monkeypatch.setattr(materialization, 'DEFAULT_MOMENT_RECEIPTS_PATH', tmp_path / 'moments.jsonl')
    calls = []
    for module, name in ((manager.VaultManager, 'initialize_vault'), (manager.VaultManager, 'select_vault'),
                         (write_ops, 'write_note_relative'), (commitment_persistence, 'persist_commitment'),
                         (materialization, 'materialize_moment'), (decision_receipt_log, 'append_decision_receipt'),
                         (notes, 'render_episode_note'), (companion_aware, 'discover_candidates_from_companions')):
        original = getattr(module, name)
        def record(*args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, record)
    generation = str(uuid4())
    produced = fixture.bootstrap_fixture(tmp_path / 'vault', generation, review_queue=companion._MEMORY_CANDIDATE_REVIEW_QUEUE)
    from tests.ops import native_daily_source_reference
    monkeypatch.setattr(fixture, '_daily_helper', lambda: native_daily_source_reference)
    produced['daily'] = fixture.prepare_daily_sources(produced, 'a' * 40)
    assert set(calls) == {'initialize_vault', 'select_vault', 'write_note_relative', 'persist_commitment',
                          'materialize_moment', 'append_decision_receipt', 'render_episode_note', 'discover_candidates_from_companions'}
    assert produced['resource_generation'] == generation
    assert produced['note_sha256'] == hashlib.sha256((tmp_path / 'vault' / fixture.NOTE_PATH).read_bytes()).hexdigest()
    assert companion.get_memory_review_queue(None, None).pending_count == 4
    assert {entry.candidate_id for entry in companion._MEMORY_CANDIDATE_REVIEW_QUEUE.pending()} == set(fixture.CANDIDATE_IDS)
    from app.main import app
    producing_queue = companion._MEMORY_CANDIDATE_REVIEW_QUEUE
    _require_actual_serving_queue(app, producing_queue, fixture.CANDIDATE_IDS, monkeypatch)
    # An in-place module reload replaces function objects but preserves their
    # globals dictionary. Actual HTTP consumption, not the function address,
    # must bind the serving heap to the canonical producer's exact queue.
    stale_queue = MemoryCandidateReviewQueue()
    for entry in producing_queue.pending():
        stale_queue.enqueue(entry.candidate)
    with monkeypatch.context() as drift:
        drift.setattr(companion, '_MEMORY_CANDIDATE_REVIEW_QUEUE', stale_queue)
        # Identical projected IDs/counts cannot substitute another heap.
        with pytest.raises(AssertionError, match='serving_api_queue_heap_mismatch'):
            _require_actual_serving_queue(app, producing_queue, fixture.CANDIDATE_IDS, monkeypatch)
    from app.api.routes import capture
    from app.ops.native_web_runtime import AcknowledgedFixtureState, DailySourceFault
    from starlette.requests import Request
    effects = {pilot: dict.fromkeys(limits, 0) for pilot, limits in web.EFFECT_LIMITS.items()}
    observer = AcknowledgedFixtureState(tmp_path / 'vault', produced, effects, capture_entry=capture._compose_entry)
    daily_monitor = DailySourceFault(tmp_path / 'vault', produced['daily'], effects, observer)
    from tests.ops.test_native_web_source_versions import generate_daily
    generate_daily(daily_monitor, effects)
    effects['deep-review']['capture'] = 1
    observer.grant('capture')
    admitted = observer.begin_request('/api/companion/capture', {'text': 'Synthetic guarded capture.'})
    monkeypatch.setattr(capture, 'INDEX_OUTBOX_PATH', tmp_path / 'index-outbox.jsonl')
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/companion/capture', 'headers': []})
    acknowledgement = capture.capture_to_inbox(capture.CaptureRequest(text='Synthetic guarded capture.'), request)
    observer.observe('/api/companion/capture', acknowledgement.model_dump(mode='json'), admitted)
    observer.require_current(fixture.fixture_readback(tmp_path / 'vault', produced)['mutable_readback'])
    daily_monitor.require_current()
    effects['daily-briefing']['degrade_source'] = 1
    daily_monitor.grant('degrade_source')
    daily_monitor.write(False)
    effects['daily-briefing']['restore_source'] = 1
    daily_monitor.grant('restore_source')
    daily_monitor.write(True)
    daily_monitor.require_restored()
    capture_path = tmp_path / 'vault' / produced['capture_note_path']
    capture_path.write_text(capture_path.read_text() + '\nUnacknowledged fixture change.\n')
    with pytest.raises(web.NativeWebRefusal, match='unacknowledged_fixture_state_change'):
        observer.require_current(fixture.fixture_readback(tmp_path / 'vault', produced)['mutable_readback'])
    source = tmp_path / 'vault' / 'moment.md'
    original = '---\nuuid: synthetic-moment\n---\nSynthetic source.\n'
    write_ops.write_note_relative('moment.md', original, vault_root=tmp_path / 'vault')
    daily = {'source_files': {'moment.md': hashlib.sha256(source.read_bytes()).hexdigest()},
             'moment_path': 'moment.md', 'moment_full_text': original}
    fault = DailySourceFault(tmp_path / 'vault', daily, {pilot: dict.fromkeys(limits, 0) for pilot, limits in web.EFFECT_LIMITS.items()},
                             briefing=daily_monitor.briefing)
    with pytest.raises(web.NativeWebRefusal, match='without_budget'):
        fault.write(False)
    fault.effects['daily-briefing']['degrade_source'] = 1
    fault.grant('degrade_source')
    assert fault.write(False)['receipt']['outcome'] == 'written'
    fault.require_current()
    fault.effects['daily-briefing']['restore_source'] = 1
    fault.grant('restore_source')
    assert fault.write(True)['post_sha256'] == daily['source_files']['moment.md']
    assert source.read_text() == original
    with pytest.raises(web.NativeWebRefusal, match='fixture_not_fresh'):
        fixture.bootstrap_fixture(tmp_path / 'vault', generation, review_queue=companion._MEMORY_CANDIDATE_REVIEW_QUEUE)
    monkeypatch.setattr(companion, '_MEMORY_CANDIDATE_REVIEW_QUEUE', MemoryCandidateReviewQueue())
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'safe_mode'})
    with pytest.raises(WritesBlockedError):
        fixture.bootstrap_fixture(tmp_path / 'blocked-vault', str(uuid4()), review_queue=companion._MEMORY_CANDIDATE_REVIEW_QUEUE)
    assert not (tmp_path / 'blocked-vault' / fixture.NOTE_PATH).exists()
    assert companion.get_memory_review_queue(None, None).pending_count == 0


def _require_actual_serving_queue(app, producing_queue, candidate_ids, monkeypatch):
    from fastapi.testclient import TestClient
    observed = []
    original = producing_queue.pending
    def pending():
        observed.append(producing_queue)
        return original()  # Real queue read/reconciliation stays active.
    with monkeypatch.context() as probe:
        probe.setattr(producing_queue, 'pending', pending)
        client = TestClient(app)
        try:
            response = client.get('/api/companion/memory/review-queue')
        finally:
            client.close()
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['pending_count'] == len(candidate_ids)
    assert {row['candidate_id'] for row in payload['candidates']} == set(candidate_ids)
    assert len(observed) == 1 and observed[0] is producing_queue, 'serving_api_queue_heap_mismatch'


def test_qualification_starts_only_fixed_api_composition(monkeypatch):
    from contextlib import contextmanager
    from app.ops import native_web_runtime as runtime

    commands = []
    monkeypatch.setattr(runtime, '_asset_readback', lambda _manifest: {})
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *args, **kwargs: None)

    @contextmanager
    def calendar():
        yield {}

    @contextmanager
    def service(command, environment):
        commands.append(command)
        # Refuse at this first actual launch boundary; this local test never
        # substitutes a running Product service or fabricates pilot success.
        raise web.NativeWebRefusal('test_launch_boundary')
        yield  # pragma: no cover

    monkeypatch.setattr(runtime, '_caldav', calendar)
    monkeypatch.setattr(runtime, '_service', service)
    with pytest.raises(web.NativeWebRefusal, match='test_launch_boundary'):
        runtime.qualify({})
    assert commands == [[runtime.sys.executable, '-m', 'app.api.native_web_qualification',
                         '--api-process', '--manifest', '/native-web-manifest.json']]


@pytest.mark.parametrize('fault', ['sha', 'digest', 'fixture_drift', 'missing_scenario', 'missing_wrapper', 'tts_missing',
                                  'report_missing', 'report_foreign', 'report_zero_effects', 'report_no_proof',
                                  'report_audio', 'report_native_config', 'report_ack_foreign', 'artifacts_text', 'junit_foreign',
                                  'daily_preexisting', 'daily_scheduled_written', 'daily_missing_regeneration',
                                  'daily_bad_degradation', 'daily_restore_drift'])
def test_required_identity_and_integrations_cannot_false_green(tmp_path, monkeypatch, fault):
    runner, boundary = _runner(tmp_path, monkeypatch, wrappers=fault != 'missing_wrapper')
    boundary.fault = fault
    if fault == 'tts_missing':
        (runner.tts_root / 'models' / runners.TTS_FILES[0]).unlink()
    result = runner.verify()
    assert result['result'] != 'passed' and result['cleanup'] == 'confirmed'
    assert not boundary.containers and not runner.directory.exists()
    if fault == 'missing_wrapper':
        assert result['reason'] == 'required_wrapper_missing'
        assert not any(args[0] == 'create' for args, _ in boundary.commands)
    reports = _reports()
    reports['daily-briefing']['scenarios'][4]['status'] = 'skipped'
    with pytest.raises(web.NativeWebRefusal):
        web.require_reports(reports)
    reports = _reports()
    reports['deep-review']['effects']['capture'] = 2
    with pytest.raises(web.NativeWebRefusal):
        web.require_reports(reports)
    # Real selected reader/HTTP REPORT consumer, with no fake rendered card.
    from app.ops.native_web_runtime import _caldav
    from app.episodes.calendar_stream import CalendarBinding, _default_transport
    with _caldav() as source:
        source['calendar_etag'] = '"exact-owned-etag"'
        rows = _default_transport(CalendarBinding(calendar_id='default', base_url=web.CALDAV_URL,
                                  username='synthetic', app_password='synthetic',
                                  calendar_path='/calendar/', scope='work'))
        assert len(rows) == 1 and rows[0].etag == source['calendar_etag'].strip('"')
        assert rows[0].uid == source['calendar_uid'] and source['report_count'] == 1


@pytest.mark.parametrize('fault', ['interrupt', 'cleanup', 'foreign'])
def test_owned_cleanup_and_interrupted_execution_preserve_foreign_resources(tmp_path, monkeypatch, fault):
    runner, boundary = _runner(tmp_path, monkeypatch)
    boundary.fault = fault
    if fault == 'foreign':
        name = runner.name + '-db'
        boundary.containers[name] = {'Id': 'f' * 64, 'Name': '/' + name, 'Config': {'Labels': {}}, 'Image': IMAGE_ID}
    unrelated = {'Id': 'e' * 64, 'Name': '/unrelated', 'Config': {'Labels': {}}}
    boundary.containers['unrelated'] = unrelated
    result = runner.verify()
    assert boundary.containers['unrelated'] == unrelated
    assert result['result'] != 'passed'
    if fault == 'interrupt':
        assert result['reason'] == 'interrupted_execution' and result['cleanup'] == 'confirmed'
        assert not runner.marker.exists()
        boundary.fault = None
        retry = runner.verify()
        assert retry['result'] == 'passed' and retry['resource_generation'] != result['resource_generation']
    else:
        assert result['result'] == 'unknown' and result['cleanup'] == 'unknown'
    if fault == 'foreign':
        assert boundary.containers[runner.name + '-db']['Id'] == 'f' * 64


def test_existing_pg_acceptance_contract_is_unchanged(tmp_path, monkeypatch):
    from tests.deploy.test_postmerge_pg_acceptance import _runner as pg_runner
    runner, boundary, sha, operation = pg_runner(tmp_path, monkeypatch)
    proof = runner.verify()
    pg.require_pass(proof, sha, DIGEST, 'dev', operation)
    assert proof['profile_version'] == 'postmerge-pg.v1'
    assert proof['selection_hash'] == pg.SELECTION_HASH
    assert len(pg.SELECTORS) == 65 and pg.PROFILE_DEADLINE == 3600
    assert not boundary.containers
    # An apparently green web result is never a retained PG receipt.
    with pytest.raises(pg.PgAcceptanceError):
        pg.require_pass({**proof, 'profile_version': web.WEB_PROFILE}, sha, DIGEST, 'dev', operation)


# ERE-13 / #6002: these tests exercise the profile's production admission and
# reader/effect seams without private bindings or a real-day operation.
_ERE_NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
_ERE_DAY = '2026-10-14'
_ERE_REGISTRY = {source: {'stream_id': source, 'status': 'live'} for source in web.ERE_ADMITTED_SOURCES}


def _ere_manifest(**overrides):
    manifest = {
        'profile_version': web.ERE_PROFILE,
        'source_sha': 'a' * 40,
        'image_digest': 'sha256:' + 'b' * 64,
        'channel': 'test',
        'operation_id': str(uuid4()),
        'local_date': _ERE_DAY,
        'sources': ['heimdal.observations', 'vault.activity', 'calendar'],
        'bindings': {
            'heimdal.observations': {'binding_id': 'heimdal:test', 'scope': 'test', 'consent_ref': 'grant:test'},
            'vault.activity': {'binding_id': 'vault:test', 'scope': 'test'},
            'calendar': {'binding_id': 'cal:test', 'calendar_id': 'calendar:test', 'scope': 'test'},
        },
    }
    manifest.update(overrides)
    return manifest


def _ere_readers(*, extra=False, outside=False):
    timestamp = '2026-10-14T12:00:00+02:00' if not outside else '2026-10-15T00:00:00+02:00'
    def rows(source, binding, **extra_fields):
        row = {'stream_id': source, 'binding_id': binding, 'scope': 'test', 'observed_at': timestamp,
               'record_id': source + ':inside', **extra_fields}
        if source == 'calendar':
            row['calendar_id'] = 'calendar:test'
            row.pop('binding_id')
        if source == 'heimdal.observations':
            row['consent_ref'] = 'grant:test'
        return [row]
    readers = {
        'heimdal.observations': lambda binding, window: rows('heimdal.observations', binding.binding_id, grant='ok'),
        'vault.activity': lambda binding, window: rows('vault.activity', binding.binding_id),
        'calendar': lambda binding, window: rows('calendar', binding.binding_id),
    }
    if extra:
        readers['vault.activity'] = lambda binding, window: rows('vault.activity', 'vault:foreign') + rows('vault.activity', binding.binding_id)
    if outside:
        readers['vault.activity'] = lambda binding, window: rows('vault.activity', binding.binding_id)
    return readers


def test_ere_profile_admits_only_registered_live_sources():
    admission = web.admit_ere_profile(_ere_manifest(), registry=_ERE_REGISTRY, now=_ERE_NOW)
    assert set(admission.bindings) == web.ERE_ADMITTED_SOURCES
    for source in ('planned.native_capture', 'chat.sessions', 'location', 'builderops.records'):
        with pytest.raises(web.EreProfileRefusal, match='source_inventory_not_admitted'):
            web.admit_ere_profile(_ere_manifest(sources=['heimdal.observations', 'vault.activity', source]),
                                  registry={**_ERE_REGISTRY, source: {'stream_id': source, 'status': 'planned'}}, now=_ERE_NOW)
    with pytest.raises(web.EreProfileRefusal, match='profile_not_admitted'):
        web.admit_ere_profile(_ere_manifest(profile_version='native-web-pilots.v1'), registry=_ERE_REGISTRY, now=_ERE_NOW)


def test_ere_profile_refuses_incomplete_or_mismatched_source_binding():
    readers_called = []
    writes = []
    guard_calls = []
    readers = {source: (lambda binding, window, source=source: readers_called.append(source) or [])
               for source in web.ERE_ADMITTED_SOURCES}
    effects = {'proposal': lambda records, admission: writes.append('proposal')}

    class Guard:
        def assert_writes_allowed(self, action):
            guard_calls.append(action)

    with pytest.raises(web.EreProfileRefusal, match='candidate_digest_invalid'):
        web.run_ere_profile({**_ere_manifest(), 'image_digest': 'foreign'}, readers=readers,
                            effects=effects, write_guard=Guard(), registry=_ERE_REGISTRY, now=_ERE_NOW)
    assert readers_called == []
    assert writes == [] and guard_calls == []
    bad = _ere_manifest(bindings={**_ere_manifest()['bindings'], 'calendar': {'binding_id': 'cal:test', 'scope': 'other', 'calendar_id': 'calendar:test'}})
    with pytest.raises(web.EreProfileRefusal, match='test_vault_scope_mismatch'):
        web.run_ere_profile(bad, readers=readers, effects=effects, write_guard=Guard(),
                            registry=_ERE_REGISTRY, now=_ERE_NOW)
    assert readers_called == []
    assert writes == [] and guard_calls == []


def test_ere_profile_reads_only_admitted_source_bindings():
    seen = []
    readers = _ere_readers(extra=True)
    original = readers['vault.activity']
    readers['vault.activity'] = lambda binding, window: (seen.append(binding.binding_id) or original(binding, window))
    normalized, evidence = web.read_ere_sources(
        web.admit_ere_profile(_ere_manifest(), registry=_ERE_REGISTRY, now=_ERE_NOW), readers)
    assert seen == ['vault:test']
    assert len(normalized) == 3 and evidence['vault.activity'][0].startswith('ref:')
    assert all('foreign' not in reference for reference in evidence['vault.activity'])


def test_ere_profile_limits_each_source_to_selected_local_day():
    admission = web.admit_ere_profile(_ere_manifest(), registry=_ERE_REGISTRY, now=_ERE_NOW)
    calls = []
    def reader(binding, window):
        calls.append((binding.identity, window.start, window.end))
        return [
            {'stream_id': 'vault.activity', 'binding_id': 'vault:test', 'scope': 'test',
             'observed_at': '2026-10-13T23:59:59+02:00', 'record_id': 'before'},
            {'stream_id': 'vault.activity', 'binding_id': 'vault:test', 'scope': 'test',
             'observed_at': '2026-10-14T23:59:59+02:00', 'record_id': 'inside'},
            {'stream_id': 'vault.activity', 'binding_id': 'vault:test', 'scope': 'test',
             'observed_at': '2026-10-15T00:00:00+02:00', 'record_id': 'after'},
        ]
    readers = {'heimdal.observations': lambda binding, window: [], 'vault.activity': reader,
               'calendar': lambda binding, window: []}
    normalized, _ = web.read_ere_sources(admission, readers)
    assert [row['record_id'] for row in normalized] == ['inside']
    assert calls and calls[0][1].tzinfo is not None and calls[0][1] < calls[0][2]


def test_ere_profile_effect_inventory_is_guarded_and_source_read_only():
    calls = []
    class Guard:
        def assert_writes_allowed(self, action):
            calls.append(('guard', action))
    writes = []
    effects = {'proposal': lambda records, admission: writes.append(('proposal', len(records))),
               'projection': lambda records, admission: writes.append(('projection', len(records)))}
    result = web.run_ere_profile(_ere_manifest(), readers=_ere_readers(), effects=effects,
                                 write_guard=Guard(), registry=_ERE_REGISTRY, now=_ERE_NOW)
    assert result['effects'] == {'proposal': 1, 'projection': 1}
    assert len(writes) == 2 and len(calls) == 2 and all(item[1].startswith('episode-resolution.real-day.') for item in calls)
    with pytest.raises(web.EreProfileRefusal, match='effect_not_admitted'):
        web.run_ere_profile(_ere_manifest(), readers=_ere_readers(), effects={'calendar_write': lambda *_: None},
                            registry=_ERE_REGISTRY, now=_ERE_NOW)


def test_ere_profile_preserves_scope_and_human_recut_boundaries():
    readers = _ere_readers()
    readers['vault.activity'] = lambda binding, window: [
        {'stream_id': 'vault.activity', 'binding_id': 'vault:test', 'scope': 'test',
         'observed_at': '2026-10-14T12:00:00+02:00', 'record_id': 'private'},
    ]
    with pytest.raises(web.EreProfileRefusal, match='cross_scope_flow_required'):
        web.run_ere_profile(_ere_manifest(), readers=readers,
                            normalize=lambda source, row: {**row, 'scope': 'private'} if source == 'vault.activity' else row,
                            registry=_ERE_REGISTRY, now=_ERE_NOW)
    readers['vault.activity'] = lambda binding, window: [{
        'stream_id': 'vault.activity', 'binding_id': 'vault:test', 'scope': 'test',
        'observed_at': '2026-10-14T12:00:00+02:00', 'record_id': 'recut', 'segmentation': 're-cut',
    }]
    writes = []
    with pytest.raises(web.EreProfileRefusal, match='human_recut_terminal'):
        web.run_ere_profile(_ere_manifest(), readers=readers,
                            effects={'proposal': lambda *_: writes.append('proposal')},
                            registry=_ERE_REGISTRY, now=_ERE_NOW)
    assert writes == []
