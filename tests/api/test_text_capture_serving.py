"""Actual app assembly and filesystem capture/find/open, without model access."""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from app.write_guard import WritesBlockedError
from tests.api._vault_test_helpers import bind_initialized_vault

api = importlib.import_module('app.api.app')
capture = importlib.import_module('app.api.routes.capture')


def _text_app(monkeypatch, channel='dev'):
    monkeypatch.setenv('PKM_ENVIRONMENT', channel)
    monkeypatch.setenv('PKM_ACTIVATION_SCOPE', 'text-capture')
    return api._create_app()


def _forbidden(*_args, **_kwargs):
    pytest.fail('text activation reached a prohibited model/semantic handler')


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_text_boundary_refuses_before_handlers(monkeypatch, channel):
    application = _text_app(monkeypatch, channel)
    blocked = []
    # Poison actual assembled route call sites, including their dependencies.
    # No body, validation or dependency may run for a denied method/path.
    allowed_get = {
        '/api/companion/orientation', '/api/health', '/api/status',
        '/api/companion/vault-browser', '/api/companion/workspace',
        '/api/companion/vault-link-index', '/api/companion/vault/notes',
        '/api/companion/vault-related', '/api/companion/briefing/today',
        '/healthz', '/readyz', '/status', '/version', '/metrics',
    }
    for route in application.routes:
        if not hasattr(route, 'dependant'):
            continue
        for method in route.methods:
            if ((method == 'GET' and route.path in allowed_get)
                or (method == 'POST' and route.path == '/api/companion/capture')):
                continue
            route.dependant.call = _forbidden
            for dependency in route.dependant.dependencies:
                dependency.call = _forbidden
            blocked.append((method, route.path.replace('{session_id}', 'sample')))
    assert len(blocked) > 50
    client = TestClient(application)
    for method, path in [*blocked, ('POST', '/api/companion/orientation'),
                         ('GET', '/api/companion/capture'), ('POST', '/api/companion/briefing/first-contact'),
                         ('POST', '/api/companion/capture/compatibility'), ('GET', '/search')]:
        response = client.request(method, path, json={})
        assert response.status_code == 503, (method, path, response.text)
        assert response.json()['detail']['error'] == 'activation_scope_unavailable'
    assert client.get('/healthz').json() == {'ok': True}
    assert client.get('/version').headers['X-PKM-Activation-Scope'] == 'text-capture'


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_capture_find_open_without_inference_preserves_write_guard(tmp_path, monkeypatch, channel):
    vault = tmp_path / 'vault'
    vault.mkdir()
    bind_initialized_vault(monkeypatch, vault, channel=channel, store_dir=tmp_path)
    outbox = tmp_path / 'events.jsonl'
    monkeypatch.setenv('INDEX_OUTBOX_PATH', str(outbox))
    monkeypatch.setenv('VAULT_INBOX_DIR_REL', 'Inbox')
    monkeypatch.delenv('VAULT_CAPTURE_NOTE_REL', raising=False)
    application = _text_app(monkeypatch, channel)
    monkeypatch.setattr(capture, '_offer_question_registration_proposal', _forbidden)
    classifier = importlib.import_module('app.components.llm.question_intent_classifier')
    monkeypatch.setattr(classifier.QuestionIntentClassifierCognition, 'classify', _forbidden)
    monkeypatch.setattr(importlib.import_module('app.retrieval.hybrid'), 'hybrid_search', _forbidden)
    monkeypatch.setattr(importlib.import_module('app.components.llm.fabric'), 'get_product_embedding_client', _forbidden)
    monkeypatch.setattr(importlib.import_module('app.services.artifact_identity'), 'ensure_note_uuid', _forbidden)
    client = TestClient(application)
    text = 'Text-only exact original: literal-body-6340 Ω?'
    response = client.post('/api/companion/capture', json={'text': text})
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt['registration_state'] == 'unavailable'
    assert receipt['registration_proposal_id'] is None
    assert receipt['governed_write']['authority_receipt']['outcome'] == 'applied'
    original = (vault / receipt['note_path']).read_text()
    assert text in original
    events = [json.loads(line) for line in outbox.read_text().splitlines()]
    assert any(event.get('event') == 'capture.inbox.appended' for event in events)
    found = client.get('/api/companion/vault-browser', params={'q': 'literal-BODY-6340 Ω?'})
    assert found.status_code == 200, found.text
    assert [note['note_path'] for note in found.json()['notes']] == [receipt['note_path']]
    opened = client.get('/api/companion/workspace', params={'note_path': receipt['note_path']})
    assert opened.status_code == 200, opened.text
    assert opened.json()['artifact']['body'] == original
    assert (vault / receipt['note_path']).read_text() == original
    before_events = outbox.read_bytes()
    # Present-but-blank context still invokes the existing scoped-write refusal.
    scoped = client.post('/api/companion/capture', json={'text': 'must not write'},
                         headers={'X-Active-Context-Session': ''})
    assert scoped.status_code == 409, scoped.text

    def blocked(action):
        raise WritesBlockedError(state='safe_mode', reason='fixture block', action=action)

    monkeypatch.setattr(capture.DEFAULT_WRITE_GUARD, 'assert_writes_allowed', blocked)
    refused = client.post('/api/companion/capture', json={'text': 'must not write'})
    assert refused.status_code == 409, refused.text
    assert (vault / receipt['note_path']).read_text() == original
    assert outbox.read_bytes() == before_events


def test_startup_and_capture_scope_is_explicit_and_default_full(tmp_path, monkeypatch):
    vault = tmp_path / 'vault'
    vault.mkdir()
    bind_initialized_vault(monkeypatch, vault, store_dir=tmp_path)
    monkeypatch.setenv('INDEX_OUTBOX_PATH', str(tmp_path / 'events.jsonl'))
    calls = []
    for name in ('_run_ingress_key_preflight', '_run_cold_volume_startup_binding',
                 '_log_v6_seam_status', '_ingest_settings_at_startup'):
        monkeypatch.setattr(api, name, lambda: None)
    monkeypatch.setattr(importlib.import_module('app.agent_memory.ask_provenance_manifest'),
                        'start_ask_provenance_runtime', lambda: None)

    async def index_preflight():
        calls.append('index')

    monkeypatch.setattr(api, '_run_index_preflight', index_preflight)
    monkeypatch.setattr(api, '_warm_retrieval_cache', lambda: calls.append('warm'))
    monkeypatch.setattr(capture, '_offer_question_registration_proposal', lambda **_kwargs: calls.append('classify'))
    text_application = _text_app(monkeypatch)
    with TestClient(text_application) as client:
        assert client.post('/api/companion/capture', json={'text': 'plain intake'}).status_code == 200
        health = importlib.import_module('app.api.routes.health')

        def cached_health(**kwargs):
            assert kwargs == {'model_access_sampling': 'cache'}
            return {'ok': False, 'required_ok': False}

        monkeypatch.setattr(health, 'run_health', cached_health)
        diagnostic = client.get('/api/health?model_access_sampling=background').json()
        assert diagnostic == {'ok': False, 'required_ok': False, 'activation_scope': 'text-capture',
                              'full_channel_qualified': False}
    assert calls == []
    monkeypatch.delenv('PKM_ACTIVATION_SCOPE')
    with TestClient(api._create_app()) as client:
        assert client.post('/api/companion/capture', json={'text': 'ordinary intake'}).status_code == 200
    assert calls == ['index', 'warm', 'classify']
    for scope, channel in [('unknown', 'dev'), ('', 'test'), ('text-capture', 'prod')]:
        monkeypatch.setenv('PKM_ACTIVATION_SCOPE', scope)
        monkeypatch.setenv('PKM_ENVIRONMENT', channel)
        with pytest.raises(ValueError, match='activation scope refused'):
            api._create_app()
    monkeypatch.delenv('PKM_ENVIRONMENT')
    monkeypatch.delenv('PKM_SETTINGS_PROFILE', raising=False)
    with pytest.raises(ValueError, match='activation scope refused'):
        api._create_app()
