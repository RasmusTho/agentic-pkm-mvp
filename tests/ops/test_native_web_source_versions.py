"""Actual normal producers across the native request/version boundary."""
from __future__ import annotations

import hashlib
import asyncio
from uuid import uuid4

import pytest
from starlette.requests import Request

from app.ops import native_web_acceptance as web
from app.ops import native_web_fixture as fixture
from app.ops.native_web_runtime import AcknowledgedFixtureState, DailySourceFault
from tests.api.conftest import mock_product_api_routes as mock_product_api_routes
from tests.ops import native_daily_source_reference


@pytest.fixture
def sources(tmp_path, monkeypatch):
    from tests.helpers.pkm_alpha_helper import reset_memory_stores
    from app.agent_memory.review_queue import MemoryCandidateReviewQueue
    from app.api.routes import companion, capture
    from app.relevance import materialization
    from app.vault import manager
    from app.write_guard import DEFAULT_WRITE_GUARD
    reset_memory_stores()
    vault = tmp_path / 'vault'
    monkeypatch.setenv('DESIGN_HANDOFF_APP_LOCAL_SETTINGS', str(tmp_path / 'app-local.md'))
    monkeypatch.setenv('VAULT_ROOT', str(vault))
    monkeypatch.setenv('INDEX_OUTBOX_PATH', str(tmp_path / 'index-outbox.jsonl'))
    monkeypatch.setenv('PANEL_CONFIRMATION_STATE_DIR', str(tmp_path / 'panel'))
    monkeypatch.setattr(capture, 'INDEX_OUTBOX_PATH', tmp_path / 'index-outbox.jsonl')
    monkeypatch.setattr(manager, '_GLOBAL_MANAGER', None)
    monkeypatch.setattr(companion, '_MEMORY_CANDIDATE_REVIEW_QUEUE', MemoryCandidateReviewQueue())
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, 'snapshot_fn', lambda: {'state': 'healthy'})
    monkeypatch.setattr(materialization, 'DEFAULT_MOMENT_RECEIPTS_PATH', tmp_path / 'moments.jsonl')
    monkeypatch.setattr(fixture, '_daily_helper', lambda: native_daily_source_reference)
    data = fixture.bootstrap_fixture(vault, str(uuid4()))
    data['daily'] = fixture.prepare_daily_sources(data, 'a' * 40)
    effects = {pilot: dict.fromkeys(limits, 0) for pilot, limits in web.EFFECT_LIMITS.items()}
    state = AcknowledgedFixtureState(vault, data, effects)
    daily = DailySourceFault(vault, data['daily'], effects, state)
    return vault, data, effects, state, daily


def generate_daily(daily, effects):
    from app.api.routes.companion import trigger_first_contact_briefing
    effects['daily-briefing']['first_contact'] = 1
    daily.briefing.grant('first_contact')
    admitted = daily.briefing.begin_contact({})
    result = trigger_first_contact_briefing()
    daily.briefing.observe_contact(result, admitted)
    return result


def _capture():
    from app.api.routes.capture import CaptureRequest, capture_to_inbox
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/companion/capture', 'headers': []})
    return capture_to_inbox(CaptureRequest(text='Synthetic guarded capture.'), request).model_dump(mode='json')


@pytest.mark.usefixtures('mock_product_api_routes')
@pytest.mark.parametrize('fault', ['none', 'before_request', 'before_observe', 'duplicate', 'wrong_target'])
def test_normal_capture_exact_request_and_response_versions(sources, fault):
    vault, data, effects, state, daily = sources
    path = vault / data['capture_note_path']
    effects['deep-review']['capture'] = 1
    state.grant('capture')
    if fault == 'before_request':
        path.write_text(path.read_text() + '\nUnacknowledged before request.\n')
        with pytest.raises(web.NativeWebRefusal, match='prestate_drift'):
            state.begin_request('/api/companion/capture', {'text': 'Synthetic guarded capture.'})
        assert not state.acknowledgements
        return
    admitted = state.begin_request('/api/companion/capture', {'text': 'Synthetic guarded capture.'})
    ack = _capture()  # Normal guarded Product route; no native substitute.
    if fault == 'before_observe':
        path.write_text(path.read_text() + '\nUnacknowledged before response observation.\n')
        with pytest.raises(web.NativeWebRefusal, match='poststate_drift'):
            state.observe('/api/companion/capture', ack, admitted)
        assert not state.acknowledgements
        return
    if fault == 'wrong_target':
        ack['note_path'] = 'foreign.md'
        with pytest.raises(web.NativeWebRefusal, match='receipt_target_mismatch'):
            state.observe('/api/companion/capture', ack, admitted)
        return
    state.observe('/api/companion/capture', ack, admitted)
    daily.require_current()
    daily.require_restored()
    assert state.acknowledgements['capture']['pre_sha256'] == admitted['pre_sha256']
    assert state.versions[data['capture_note_path']] == hashlib.sha256(path.read_bytes()).hexdigest()
    if fault == 'duplicate':
        with pytest.raises(web.NativeWebRefusal):
            state.observe('/api/companion/capture', ack, admitted)
        with pytest.raises(web.NativeWebRefusal):
            state.begin_request('/api/companion/capture', {'text': 'Synthetic guarded capture.'})


@pytest.mark.usefixtures('mock_product_api_routes')
@pytest.mark.parametrize('immutable_source', ['note', 'marker'])
def test_serial_original_daily_sources_acknowledgement_fault_restore_and_drift(sources, monkeypatch, immutable_source):
    from app.api.routes.companion import _stage_queue_review_panel_proposal
    from app.api.routes.panel import panel_confirm
    from app.panel import confirmation
    vault, data, effects, state, daily = sources
    # Current-day helper works with its exact existing relative marker and the
    # native monthly append ordered afterwards. No backdated feature proof.
    assert isinstance(data['daily']['fixture_marker'], str)
    marker = vault / data['daily']['fixture_marker']
    assert marker.is_file() and marker.stat().st_mode & 0o777 == 0o600
    assert data['capture_note_path'] in data['daily']['source_files']
    generate_daily(daily, effects)
    monkeypatch.setenv('PANEL_AGENT_DECIDER', 'rule')
    proposal_id = _stage_queue_review_panel_proposal({'note_path': data['review_note_path'], 'artifact_uuid': data['review_note_uuid']})
    confirmation._proposal_store.get(proposal_id).proposed_at = 0.0
    payload = {'proposal_id': proposal_id, 'artifact_id': data['review_note_uuid'], 'action': 'confirm',
               'idempotency_key': 'native-serial-' + proposal_id}
    effects['deep-review']['panel_confirm'] = 1
    state.grant('panel_confirm')
    admitted_panel = state.begin_request('/api/panel/confirm', payload)
    panel_ack = asyncio.run(panel_confirm(confirmation.ConfirmRequest(**payload))).model_dump(mode='json')
    state.observe('/api/panel/confirm', panel_ack, admitted_panel)
    daily.require_current()
    effects['deep-review']['capture'] = 1
    state.grant('capture')
    admitted = state.begin_request('/api/companion/capture', {'text': 'Synthetic guarded capture.'})
    state.observe('/api/companion/capture', _capture(), admitted)
    daily.require_current()
    effects['daily-briefing']['degrade_source'] = 1
    daily.grant('degrade_source')
    daily.write(False)
    daily.require_current()
    effects['daily-briefing']['restore_source'] = 1
    daily.grant('restore_source')
    daily.write(True)
    daily.require_restored()
    immutable = vault / fixture.NOTE_PATH if immutable_source == 'note' else marker
    immutable.write_text(immutable.read_text() + '\nUnrelated drift.\n')
    with pytest.raises(web.NativeWebRefusal, match='daily_fixture_(source|marker)_drift'):
        daily.require_current()


@pytest.mark.usefixtures('mock_product_api_routes')
@pytest.mark.parametrize('fault', ['none', 'before_request', 'before_observe', 'duplicate', 'wrong_target', 'no_action'])
def test_normal_panel_request_acknowledgement_and_daily_owned_versions(sources, fault, monkeypatch):
    from app.api.routes.companion import _stage_queue_review_panel_proposal
    from app.api.routes.panel import panel_confirm
    from app.panel import confirmation
    # Normal rule-mode producer for this bounded write assertion. Native
    # qualification preserves its baked settings and selected real integration.
    monkeypatch.setenv('PANEL_AGENT_DECIDER', 'llm' if fault == 'no_action' else 'rule')
    vault, data, effects, state, daily = sources
    proposal_id = _stage_queue_review_panel_proposal({'note_path': data['review_note_path'], 'artifact_uuid': data['review_note_uuid']})
    confirmation._proposal_store.get(proposal_id).proposed_at = 0.0
    payload = {'proposal_id': proposal_id, 'artifact_id': data['review_note_uuid'], 'action': 'confirm',
               'idempotency_key': 'native-test-' + proposal_id}
    effects['deep-review']['panel_confirm'] = 1
    state.grant('panel_confirm')
    path = vault / data['review_note_path']
    if fault == 'before_request':
        path.write_text(path.read_text() + '\nUnacknowledged before panel request.\n')
        with pytest.raises(web.NativeWebRefusal, match='prestate_drift'):
            state.begin_request('/api/panel/confirm', payload)
        return
    if fault == 'wrong_target':
        payload['artifact_id'] = str(uuid4())
        with pytest.raises(web.NativeWebRefusal, match='target_mismatch'):
            state.begin_request('/api/panel/confirm', payload)
        return
    admitted = state.begin_request('/api/panel/confirm', payload)
    ack = asyncio.run(panel_confirm(confirmation.ConfirmRequest(**payload))).model_dump(mode='json')
    if fault == 'no_action':
        # The normal route's execution label alone cannot license a no-action
        # writeback as the fixed queue-review transition.
        with pytest.raises(web.NativeWebRefusal, match='poststate_drift'):
            state.observe('/api/panel/confirm', ack, admitted)
        return
    # This normal queue-review producer logs its action and writes the exact
    # status receipt. The original Deep executed/success proof still refuses
    # this response as feature acceptance; version evolution is narrower.
    assert ack['status'] == 'logged' and ack['receipt']['receipt_id']
    if fault == 'before_observe':
        path.write_text(path.read_text() + '\nUnacknowledged after normal panel write.\n')
        with pytest.raises(web.NativeWebRefusal, match='poststate_drift'):
            state.observe('/api/panel/confirm', ack, admitted)
        return
    state.observe('/api/panel/confirm', ack, admitted)
    daily.require_current()
    daily.require_restored()
    if fault == 'duplicate':
        with pytest.raises(web.NativeWebRefusal):
            state.observe('/api/panel/confirm', ack, admitted)
        with pytest.raises(web.NativeWebRefusal):
            state.begin_request('/api/panel/confirm', payload)
