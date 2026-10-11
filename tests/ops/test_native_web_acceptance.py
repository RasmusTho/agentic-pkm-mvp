"""Production envelope/producer proof; these doubles establish no live PASS."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
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


def _reports():
    return {pilot: {'passed': True, 'scenarios': [{'id': key, 'status': 'passed'} for key in keys],
                    'effects' if pilot == 'deep-review' else 'effects_consumed': dict.fromkeys(web.EFFECT_LIMITS[pilot], 0)}
            for pilot, keys in web.SCENARIOS.items()}


class WebBoundary(DockerBoundary):
    def command(self, *arguments, timeout=60):
        if arguments[:2] == ('start', '--attach'):
            self.commands.append((arguments, timeout))
            if self.fault == 'interrupt':
                raise KeyboardInterrupt()
            manifest = json.loads((self.runner.directory / 'source/native-web-manifest.json').read_text())
            row = self.containers[self.runner.name + '-tests']
            row['State'] = {'Running': False, 'ExitCode': 0}
            self.pilots = _reports()
            api = {key: manifest[key] for key in ('source_sha', 'image_digest', 'app_image_id', 'resource_tree', 'resource_generation')}
            api.update(api_module='/app/app/main.py', api_pid=42, browser_audio_assets_hash=web.hash_json(manifest['prerequisites']),
                       fixture={'resource_generation': manifest['resource_generation'], 'note_sha256': 'a' * 64,
                                'settings_hash': 'a' * 64, 'candidate_ids': list(fixture.CANDIDATE_IDS),
                                'logical_vault_id': 'synthetic-vault', 'local_clone_id': 'synthetic-clone',
                                'note_uuid': fixture.NOTE_UUID, 'note_path': fixture.NOTE_PATH})
            observation = {'api': api, 'ui_pid': 43, 'configuration_hash': 'b' * 64,
                           'ui_program_sha256': manifest['files']['companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py']}
            result = {**self.runner.identity, 'result': 'passed', 'wrappers': list(web.WRAPPERS),
                      'resource_tree': manifest['resource_tree'], 'app_image_id': IMAGE_ID,
                      'start': observation, 'end': observation,
                      'pilots': self.pilots, 'report_hash': web.hash_json(self.pilots)}
            if self.fault == 'fixture_drift':
                result['end'] = {'service': 'drift'}
            if self.fault == 'missing_scenario':
                result['pilots']['deep-review']['scenarios'].pop()
                result['report_hash'] = web.hash_json(result['pilots'])
            return ('YGGDRASIL_NATIVE_WEB=' + json.dumps(result)).encode()
        if arguments[0] == 'cp':
            self.commands.append((arguments, timeout))
            pilot, filename = arguments[1].split('/')[-2:]
            Path(arguments[-1]).write_text(json.dumps(self.pilots[pilot]) if filename == 'report.json' else 'actual transport artifact')
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


def _runner(tmp_path, monkeypatch, *, wrappers=True):
    root, _sha = _repository(tmp_path)
    for selector in web.WRAPPERS if wrappers else ():
        path = root / selector.split('::')[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# exact fixed wrapper\n')
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
    produced = fixture.bootstrap_fixture(tmp_path / 'vault', generation)
    assert set(calls) == {'initialize_vault', 'select_vault', 'write_note_relative', 'persist_commitment',
                          'materialize_moment', 'append_decision_receipt', 'render_episode_note', 'discover_candidates_from_companions'}
    assert produced['resource_generation'] == generation
    assert produced['note_sha256'] == hashlib.sha256((tmp_path / 'vault' / fixture.NOTE_PATH).read_bytes()).hexdigest()
    assert companion.get_memory_review_queue().pending_count == 4
    assert {entry.candidate_id for entry in companion._MEMORY_CANDIDATE_REVIEW_QUEUE.pending()} == set(fixture.CANDIDATE_IDS)
    from app.main import app
    assert next(route.endpoint for route in app.routes if getattr(route, 'path', '') == '/api/companion/memory/review-queue') is companion.get_memory_review_queue
    from app.api.routes import capture
    from app.ops.native_web_runtime import AcknowledgedFixtureState, DailySourceFault
    from starlette.requests import Request
    effects = {pilot: dict.fromkeys(limits, 0) for pilot, limits in web.EFFECT_LIMITS.items()}
    observer = AcknowledgedFixtureState(tmp_path / 'vault', produced, effects)
    effects['deep-review']['capture'] = 1
    monkeypatch.setattr(capture, 'INDEX_OUTBOX_PATH', tmp_path / 'index-outbox.jsonl')
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/companion/capture', 'headers': []})
    acknowledgement = capture.capture_to_inbox(capture.CaptureRequest(text='Synthetic guarded capture.'), request)
    observer.observe('/api/companion/capture', acknowledgement.model_dump(mode='json'))
    observer.require_current(fixture.fixture_readback(tmp_path / 'vault', produced)['mutable_readback'])
    capture_path = tmp_path / 'vault' / produced['capture_note_path']
    capture_path.write_text(capture_path.read_text() + '\nUnacknowledged fixture change.\n')
    with pytest.raises(web.NativeWebRefusal, match='unacknowledged_fixture_state_change'):
        observer.require_current(fixture.fixture_readback(tmp_path / 'vault', produced)['mutable_readback'])
    source = tmp_path / 'vault' / 'moment.md'
    original = '---\nuuid: synthetic-moment\n---\nSynthetic source.\n'
    write_ops.write_note_relative('moment.md', original, vault_root=tmp_path / 'vault')
    daily = {'source_files': {'moment.md': hashlib.sha256(source.read_bytes()).hexdigest()},
             'moment_path': 'moment.md', 'moment_full_text': original}
    fault = DailySourceFault(tmp_path / 'vault', daily, effects)
    with pytest.raises(web.NativeWebRefusal, match='without_budget'):
        fault.write(False)
    effects['daily-briefing']['degrade_source'] = 1
    assert fault.write(False)['receipt']['outcome'] == 'written'
    fault.require_current()
    effects['daily-briefing']['restore_source'] = 1
    assert fault.write(True)['post_sha256'] == daily['source_files']['moment.md']
    assert source.read_text() == original
    with pytest.raises(web.NativeWebRefusal, match='fixture_not_fresh'):
        fixture.bootstrap_fixture(tmp_path / 'vault', generation)
    monkeypatch.setattr(companion, '_MEMORY_CANDIDATE_REVIEW_QUEUE', MemoryCandidateReviewQueue())
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'safe_mode'})
    with pytest.raises(WritesBlockedError):
        fixture.bootstrap_fixture(tmp_path / 'blocked-vault', str(uuid4()))
    assert not (tmp_path / 'blocked-vault' / fixture.NOTE_PATH).exists()
    assert companion.get_memory_review_queue().pending_count == 0


@pytest.mark.parametrize('fault', ['sha', 'digest', 'fixture_drift', 'missing_scenario', 'missing_wrapper', 'tts_missing'])
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
