"""Actual HTTP/normal writer proof, with explicit absent native preconditions."""
from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.request import urlopen
from uuid import uuid4

import pytest

from app.api import native_web_qualification as composition
from app.ops import native_web_fixture as fixture
from tests.api.conftest import mock_product_api_routes as mock_product_api_routes
from tests.ops import native_daily_source_reference


@pytest.fixture
def actual_api(tmp_path, monkeypatch):
    from app.agent_memory.review_queue import MemoryCandidateReviewQueue
    from app.relevance import materialization
    from app.vault import manager
    from app.write_guard import DEFAULT_WRITE_GUARD
    from tests.helpers.pkm_alpha_helper import reset_memory_stores
    reset_memory_stores()
    vault = tmp_path / 'vault'
    monkeypatch.setenv('DESIGN_HANDOFF_APP_LOCAL_SETTINGS', str(tmp_path / 'app-local.md'))
    monkeypatch.setenv('VAULT_ROOT', str(vault))
    monkeypatch.setenv('PKM_ENVIRONMENT', 'test')
    monkeypatch.setenv('STORE_BACKEND', 'memory')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('DB_DSN', raising=False)
    monkeypatch.setenv('INDEX_OUTBOX_PATH', str(tmp_path / 'index-outbox.jsonl'))
    monkeypatch.setenv('PANEL_STAGING_DB_PATH', str(tmp_path / 'panel.sqlite3'))
    monkeypatch.setattr(manager, '_GLOBAL_MANAGER', None)
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'healthy'})
    monkeypatch.setattr(materialization, 'DEFAULT_MOMENT_RECEIPTS_PATH', tmp_path / 'moments.jsonl')
    from app.api.routes import companion
    monkeypatch.setattr(companion, '_MEMORY_CANDIDATE_REVIEW_QUEUE', MemoryCandidateReviewQueue())
    from app.settings import compiler, runtime as settings_runtime
    monkeypatch.setattr(compiler, 'RUNTIME', tmp_path / 'compiled-settings')
    monkeypatch.setattr(settings_runtime, 'RUNTIME', tmp_path / 'compiled-settings')
    from app.main import app
    monkeypatch.setattr(app.router, 'routes', list(app.router.routes))
    monkeypatch.setattr(app, 'user_middleware', list(app.user_middleware))
    monkeypatch.setattr(app, 'middleware_stack', None)
    original_path = composition.Path
    monkeypatch.setattr(composition, 'Path', lambda value: vault if str(value) == '/scratch/vault' else original_path(value))
    monkeypatch.setattr(fixture, '_daily_helper', lambda: native_daily_source_reference)
    # Only unavailable native boundary preconditions are substituted locally.
    # Normal API routes, source readers, writers, guards and receipts are real.
    monkeypatch.setattr(composition, 'verify_resources', lambda _manifest: None)
    monkeypatch.setattr(composition, '_asset_readback', lambda _manifest: {'browser_audio_assets_hash': 'local-contract-only'})
    from app.tts import config, providers
    monkeypatch.setattr(config, 'load_tts_config', lambda: SimpleNamespace(enabled=True, local_only=True,
        allow_browser_fallback=False, allow_cloud_fallback=False))
    monkeypatch.setattr(providers, 'resolve_voice', lambda _config, language: SimpleNamespace(available=True,
        language=language, provider='piper' if language == 'sv-SE' else 'kokoro',
        voice_id='sv_SE-lisa-medium' if language == 'sv-SE' else 'bf_isabella'))
    manifest = {'source_sha': 'a' * 40, 'image_digest': 'sha256:' + 'b' * 64, 'app_image_id': 'sha256:' + 'c' * 64,
                'resource_tree': 'd' * 40, 'resource_generation': str(uuid4())}
    from fastapi.testclient import TestClient
    client = TestClient(composition.create_native_web_app(manifest), raise_server_exceptions=False)
    observed = client.get('/__native_web_identity')
    assert observed.status_code == 200, observed.text
    data = observed.json()['identity']['fixture']
    assert companion.get_memory_review_queue(None, None).pending_count == len(fixture.CANDIDATE_IDS)
    assert {entry.candidate_id for entry in companion._MEMORY_CANDIDATE_REVIEW_QUEUE.pending()} == set(fixture.CANDIDATE_IDS)
    yield client, vault, data
    client.close()


def grant(client, effect):
    response = client.get('/__native_web_identity', params={'pilot': 'daily-briefing', 'effect': effect})
    assert response.status_code == 200, response.text


def generate(client):
    grant(client, 'first_contact')
    response = client.post('/api/companion/briefing/first-contact', json={})
    assert response.status_code == 200, response.text
    assert response.json()['triggered'] is True
    return response


def assert_briefing_has_derived_identity(vault, relative_path):
    from app.services.note_uuid import resolve_read_only_derived_uuid
    target = vault / relative_path
    expected = resolve_read_only_derived_uuid(target, vault_root=vault)
    assert ('uuid: ' + expected + '\n').encode() in target.read_bytes()


@pytest.mark.usefixtures('mock_product_api_routes')
@pytest.mark.parametrize('fault', ['none', 'unadmitted', 'hook_drift', 'post_drift', 'scheduled_absent', 'scheduled_duplicate'])
def test_actual_http_first_generation_and_zero_write_replays(actual_api, monkeypatch, fault):
    from app.api.routes import companion
    client, vault, data = actual_api
    target = vault / data['daily']['briefing_path']
    assert not target.exists()
    if fault == 'unadmitted':
        assert client.post('/api/companion/briefing/first-contact', json={}).status_code == 500
        assert not target.exists()
        return
    if fault == 'scheduled_absent':
        assert client.post('/__native_web_fixture/scheduled-replay').status_code == 500
        assert not target.exists()
        return
    if fault == 'hook_drift':
        grant(client, 'first_contact')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('Unacknowledged dated note.')
        before = target.read_bytes()
        assert client.post('/api/companion/briefing/first-contact', json={}).status_code == 500
        assert target.read_bytes() == before
        return
    if fault == 'post_drift':
        original = companion.read_today_briefing
        def drift():
            target.write_text(target.read_text() + '\nUnacknowledged response drift.\n')
            return original()
        monkeypatch.setattr(companion, 'read_today_briefing', drift)
        grant(client, 'first_contact')
        assert client.post('/api/companion/briefing/first-contact', json={}).status_code == 500
        assert client.get('/__native_web_identity').status_code == 500
        return
    generate(client)
    assert_briefing_has_derived_identity(vault, data['daily']['briefing_path'])
    prior = target.read_bytes()
    grant(client, 'first_contact')
    replay = client.post('/api/companion/briefing/first-contact', json={})
    assert replay.status_code == 200 and replay.json()['reason'] == 'already_generated_today'
    scheduled = client.post('/__native_web_fixture/scheduled-replay')
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()['durable_writes'] == 0
    if fault == 'scheduled_duplicate':
        assert client.post('/__native_web_fixture/scheduled-replay').status_code == 500
    assert target.read_bytes() == prior


@pytest.mark.usefixtures('mock_product_api_routes')
@pytest.mark.parametrize('fault', ['none', 'hook_source_drift', 'hook_note_drift', 'guard', 'inside_reader_note_drift', 'post_drift', 'duplicate'])
def test_actual_http_source_write_and_guarded_regeneration(actual_api, monkeypatch, fault):
    from app.write_guard import DEFAULT_WRITE_GUARD
    client, vault, data = actual_api
    generate(client)
    assert_briefing_has_derived_identity(vault, data['daily']['briefing_path'])
    source = vault / data['daily']['moment_path']
    note = vault / data['daily']['briefing_path']
    original_source, original_note = source.read_bytes(), note.read_bytes()
    grant(client, 'degrade_source')
    if fault in {'hook_source_drift', 'hook_note_drift'}:
        target = source if fault == 'hook_source_drift' else note
        target.write_bytes(target.read_bytes() + b'\nUnacknowledged hook drift.\n')
        before = target.read_bytes()
        assert client.post('/__native_web_fixture/degrade-source').status_code == 500
        assert target.read_bytes() == before
        return
    if fault == 'guard':
        monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'safe_mode'})
        assert client.post('/__native_web_fixture/degrade-source').status_code == 500
        assert source.read_bytes() == original_source and note.read_bytes() == original_note
        return
    if fault == 'inside_reader_note_drift':
        from app.briefing import compose
        original = compose.read_note_text_with_version
        def drift(path):
            note.write_bytes(original_note + b'\nUnacknowledged before CAS-token read.\n')
            return original(path)
        monkeypatch.setattr(compose, 'read_note_text_with_version', drift)
        assert client.post('/__native_web_fixture/degrade-source').status_code == 500
        assert note.read_bytes() == original_note + b'\nUnacknowledged before CAS-token read.\n'
        return
    if fault == 'post_drift':
        from app.briefing import trigger
        original = trigger.regenerate_briefing
        def drift(**kwargs):
            result = original(**kwargs)
            note.write_bytes(note.read_bytes() + b'\nUnacknowledged regeneration drift.\n')
            return result
        monkeypatch.setattr(trigger, 'regenerate_briefing', drift)
        assert client.post('/__native_web_fixture/degrade-source').status_code == 500
        observed = client.get('/__native_web_identity')
        assert observed.status_code == 500
        return
    degraded = client.post('/__native_web_fixture/degrade-source')
    assert degraded.status_code == 200, degraded.text
    ack = degraded.json()
    assert ack['source_writes'] == ack['regenerations'] == 1
    assert ack['regeneration']['receipt']['operation'] == 'write_note'
    assert ack['regeneration']['receipt']['locator']['path'] == data['daily']['briefing_path']
    assert ack['regeneration']['post_sha256'] == hashlib.sha256(note.read_bytes()).hexdigest()
    assert_briefing_has_derived_identity(vault, data['daily']['briefing_path'])
    # Main's current Moment reader may silently omit the invalid source. This
    # normal observed result is not the original named-degradation feature PASS.
    if fault == 'duplicate':
        before = note.read_bytes()
        assert client.post('/__native_web_fixture/degrade-source').status_code == 500
        assert note.read_bytes() == before
    grant(client, 'restore_source')
    restored = client.post('/__native_web_fixture/restore-source')
    assert restored.status_code == 200, restored.text
    assert source.read_bytes() == original_source and note.read_bytes() == original_note


@pytest.mark.usefixtures('mock_product_api_routes')
def test_every_actual_ui_root_caller_preserves_fresh_then_acknowledged_note(actual_api, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'companion-ui/companion-app'))
    from companion_ui.workspace.serve_dev_page import CompanionThreadingHTTPServer, make_handler
    client, vault, data = actual_api
    class ActualApiTransport:
        def get(self, path, params=None):
            return client.get(path, params=params or {}).json()
        def post(self, path, json=None, **_kwargs):
            response = client.post(path, json=json or {})
            if response.status_code != 200:
                raise RuntimeError('actual API refused')
            return response.json()
    server = CompanionThreadingHTTPServer(('127.0.0.1', 0), make_handler(client=ActualApiTransport(),
        api_base_url='http://127.0.0.1:8000', runtime_channel='test', runtime_git_sha='a' * 40))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    target = vault / data['daily']['briefing_path']
    try:
        with urlopen(url + '/healthz') as response:
            assert response.status == 200
        assert not target.exists()
        # The actual gateway catches first-contact refusal and renders its
        # ordinary pending state. It cannot create an uncharged fresh note.
        with urlopen(url + '/') as response:
            assert response.status == 200
        assert not target.exists()
        generate(client)
        prior = target.read_bytes()
        for path in ('/', '/workspace'):
            grant(client, 'navigation')
            with urlopen(url + path) as response:
                assert b'<script' in response.read()
            assert target.read_bytes() == prior
        # Later Deep navigation has no first-generation licence and no write.
        with urlopen(url + '/') as response:
            assert response.status == 200
        assert target.read_bytes() == prior
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
