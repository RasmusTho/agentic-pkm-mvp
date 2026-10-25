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
        '/api/companion/vault/notes/scoped', '/api/companion/active-context/selection',
        '/api/companion/vault-related', '/api/companion/briefing/today',
        '/healthz', '/readyz', '/status', '/version', '/metrics',
    }
    for route in application.routes:
        if not hasattr(route, 'dependant'):
            continue
        for method in route.methods:
            if ((method == 'GET' and route.path in allowed_get)
                or (method == 'POST' and route.path in {
                    '/api/companion/capture', '/api/companion/capture/compatibility',
                })):
                continue
            route.dependant.call = _forbidden
            for dependency in route.dependant.dependencies:
                dependency.call = _forbidden
            blocked.append((method, route.path.replace('{session_id}', 'sample')))
    assert len(blocked) > 50
    client = TestClient(application)
    for method, path in [*blocked, ('POST', '/api/companion/orientation'),
                         ('GET', '/api/companion/capture'), ('POST', '/api/companion/briefing/first-contact'),
                         ('POST', '/api/companion/note/save/compatibility'), ('GET', '/search')]:
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


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('journey', ['carrier-free', 'scoped'])
def test_served_capture_handshake_retains_real_admission(tmp_path, monkeypatch, channel, journey):
    import app.api.routes.active_context_selection as selections
    import app.api.routes.companion as companion
    import tests._mvr05b_picker_browser as browser
    from app.instance.local_operator_principal import AuthPosture
    from app.instance.runtime import open_default_vault_service
    from app.instance.settings_rebind import _install_dormant_settings_rebind
    from app.vault.app_local import AppLocalSettingsStore
    from app.vault.manager import VaultManager
    from companion_ui.workspace.scoped_session import session_cookie, session_transport_digest
    from tests._mvr03_principal_harness import run_principal_cutover
    from tests._mvr_default_vault_harness import activate, new_runtime
    from tests.companion_ui.live_core_flow import _CAPTURE_PATHS
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY
    from tests.helpers.vault_settings import initialize_test_vault

    # Produce the initialized admission fixture through the existing real
    # authority/floor/principal producers, solely in this temporary directory.
    runtime = new_runtime(tmp_path, channel=channel)
    vault = tmp_path / 'vault'
    vault.mkdir()
    binding = runtime.bootstrap_env_binding(vault_root=vault, watcher_vault_path=vault)
    activate(runtime, binding, tmp_path)
    open_default_vault_service(runtime.registry.path).set(binding.vault_binding_id)
    run_principal_cutover(runtime, channel_id=channel, posture=AuthPosture(
        configured_credentials=0, credential=None, loopback_listener_proven=True,
        companion_proxy_configured=False,
    ))
    initialize_test_vault(vault)
    _install_dormant_settings_rebind(runtime.registry, binding_id=binding.vault_binding_id,
                                   _capability=STORAGE_MUTATION_CAPABILITY)
    monkeypatch.setenv('PKM_ENVIRONMENT', channel)
    monkeypatch.setenv('INSTANCE_VAULT_REGISTRY_PATH', str(runtime.registry.path))
    monkeypatch.setenv('INSTANCE_OWNERSHIP_ROOT', str(runtime.ledger.root))
    monkeypatch.setenv('WATCHER_ENABLE', '0')
    monkeypatch.setenv('INDEX_OUTBOX_PATH', str(tmp_path / 'events.jsonl'))
    monkeypatch.setenv('VAULT_INBOX_DIR_REL', 'Inbox')
    monkeypatch.delenv('VAULT_CAPTURE_NOTE_REL', raising=False)
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / 'app-local.md'))
    monkeypatch.setattr(companion, 'get_vault_manager', lambda: manager)
    monkeypatch.setattr('app.api.routes.vault_resolution.get_vault_manager', lambda: manager)
    monkeypatch.setattr('app.settings.ingestion.ingest_settings', lambda *_args, **_kwargs: None)
    manager.select_vault(vault, remember=False)
    selections.reset_selection_store_for_tests()
    cookie = ''
    if journey == 'scoped':
        # An existing selected session is a fixture precondition, not a picker
        # mutation newly admitted by the limited text API.
        monkeypatch.delenv('PKM_ACTIVATION_SCOPE', raising=False)
        # Do not enter the unrelated full startup lifespan in this fixture.
        full = TestClient(api._create_app(), client=('127.0.0.1', 40000))
        selected = full.post('/api/companion/active-context/selection',
                             json={'vault_binding_ids': [binding.vault_binding_id]})
        assert selected.status_code == 201
        bearer = selected.json()['context_selection_id']
        cookie = session_cookie(bearer).split(';', 1)[0] + '; companion_context_intent=' + session_transport_digest(bearer)
        full.close()
    application = _text_app(monkeypatch, channel)
    monkeypatch.setattr(browser, 'app', application)
    monkeypatch.setattr(capture, '_offer_question_registration_proposal', _forbidden)
    monkeypatch.setattr('app.components.llm.question_intent_classifier.QuestionIntentClassifierCognition.classify', _forbidden)
    monkeypatch.setattr('app.components.llm.fabric.get_product_embedding_client', _forbidden)
    monkeypatch.setattr('app.retrieval.hybrid.hybrid_search', _forbidden)
    monkeypatch.setattr('app.services.artifact_identity.ensure_note_uuid', _forbidden)
    monkeypatch.setattr('app.api.routes.health.run_health', lambda **_kwargs: {'ok': False, 'required_ok': False})
    text = 'served text capture literal-6340 Ω?'
    with browser.picker_browser(monkeypatch, cookie=cookie, raise_server_exceptions=True) as (run, calls):
        result = run('''
await bootDocument('/workspace');
var response=await fetch('/api/companion/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:TEXT})});
console.log(JSON.stringify({status:response.status,body:await response.json()}));
'''.replace('TEXT', json.dumps(text)))
    assert result['status'] == 200, result
    posts = [call for call in calls if call[0] == 'POST' and call[1] in _CAPTURE_PATHS]
    assert len(posts) == 1 and posts[0][1] == '/api/companion/capture/compatibility'
    assert posts[0][2].get('X-Compatibility-Write-Precondition')
    assert 'X-Active-Context-Session' not in posts[0][2]
    assert not any(path.endswith('/vault/select') or path.endswith('/vault/initialize') for _, path, _, _ in calls)
    if journey == 'scoped':
        assert any(path == '/api/companion/active-context/selection' for _, path, _, _ in calls)
        assert any(path == '/api/companion/vault/notes/scoped' for _, path, _, _ in calls)
    note_path = result['body']['note_path']
    original = (vault / note_path).read_bytes()
    assert text in original.decode()
    outbox = tmp_path / 'events.jsonl'
    assert any(json.loads(line).get('event') == 'capture.inbox.appended' for line in outbox.read_text().splitlines())
    before_events = outbox.read_bytes()
    client = TestClient(application, client=('127.0.0.1', 40000))
    found = client.get('/api/companion/vault-browser', params={'q': 'LITERAL-6340 Ω?'})
    assert [note['note_path'] for note in found.json()['notes']] == [note_path]
    opened = client.get('/api/companion/workspace', params={'note_path': note_path})
    assert opened.json()['artifact']['body'].encode() == original
    assert client.post('/api/companion/capture/compatibility', json={'text': 'no proof'}).status_code == 409
    remote = client.post('/api/companion/capture/compatibility', json={'text': 'unauthenticated'}, headers={
        'X-Forwarded-For': '203.0.113.8',
        'X-Compatibility-Write-Precondition': posts[0][2]['X-Compatibility-Write-Precondition'],
    })
    assert remote.status_code == 401
    for path in ('/api/companion/active-context/selection', '/api/companion/vault/notes/scoped'):
        stale = client.get(path, headers={'X-Active-Context-Session': 'never-issued'})
        assert stale.status_code == 401, stale.text
    def blocked(action):
        raise WritesBlockedError(state='safe_mode', reason='fixture block', action=action)

    monkeypatch.setattr(capture.DEFAULT_WRITE_GUARD, 'assert_writes_allowed', blocked)
    refused = client.post('/api/companion/capture/compatibility', json={'text': 'no guarded write'},
                          headers={'X-Compatibility-Write-Precondition': posts[0][2]['X-Compatibility-Write-Precondition']})
    assert refused.status_code == 409, refused.text
    assert (vault / note_path).read_bytes() == original and outbox.read_bytes() == before_events
    client.close()


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
