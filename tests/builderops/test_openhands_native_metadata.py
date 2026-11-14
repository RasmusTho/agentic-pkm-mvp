import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.builderops import openhands_native_metadata as metadata


def write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


def fixture(tmp_path, engine):
    home, codex = tmp_path / 'home', tmp_path / 'codex'
    conversation, session = str(uuid.uuid4()), str(uuid.uuid4())
    state = home / 'openhands' / 'conversations' / uuid.UUID(conversation).hex / 'base_state.json'
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({'id': conversation, 'execution_status': 'finished',
                                 'workspace': {'working_dir': '/workspace'},
                                 'agent_state': {'acp_session_id': session, 'acp_session_cwd': '/workspace'}}))
    if engine == 'codex':
        path = codex / 'sessions' / '2026' / '11' / '13' / f'rollout-test-{session}.jsonl'
        rows = [{'type': 'session_meta', 'payload': {'id': session}},
                {'type': 'turn_context', 'timestamp': '2026-11-13T00:00:00Z',
                 'payload': {'model': 'gpt-6.1-terra', 'effort': 'high'}},
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': 'private'}}]
    else:
        path = home / '.claude' / 'projects' / '-workspace' / f'{session}.jsonl'
        rows = [{'type': 'assistant', 'sessionId': session, 'timestamp': '2026-11-13T00:00:00Z',
                 'message': {'model': 'claude-opus-5-5', 'content': 'private'}}]
    write_lines(path, rows)
    return home, codex, conversation, session, path, rows


@pytest.mark.parametrize('engine,model', [('codex', 'gpt-6.1-terra'), ('claude-code', 'claude-opus-5-5')])
def test_associates_native_log_to_exact_retained_conversation(tmp_path, engine, model):
    home, codex, conversation, session, path, rows = fixture(tmp_path, engine)
    result = metadata.observe(home, codex, engine, conversation)
    assert result['session_id'] == session and result['model'] == model
    assert 'private' not in json.dumps(result)
    if engine == 'codex':
        rows[0]['payload']['id'] = str(uuid.uuid4())
    else:
        rows[0]['sessionId'] = str(uuid.uuid4())
    write_lines(path, rows)
    with pytest.raises(ValueError):
        metadata.observe(home, codex, engine, conversation)


def test_context_without_execution_and_mixed_models_refuse(tmp_path):
    home, codex, conversation, _, path, rows = fixture(tmp_path, 'codex')
    write_lines(path, rows[:2])
    with pytest.raises(ValueError, match='missing'):
        metadata.observe(home, codex, 'codex', conversation)
    rows += [{'type': 'turn_context', 'timestamp': 'later', 'payload': {'model': 'other', 'effort': 'high'}},
             {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant'}}]
    write_lines(path, rows)
    with pytest.raises(ValueError, match='mixed'):
        metadata.observe(home, codex, 'codex', conversation)


def test_mismatched_workspace_refuses_old_session(tmp_path):
    home, codex, conversation, session, _, _ = fixture(tmp_path, 'claude-code')
    state_path = home / 'openhands' / 'conversations' / uuid.UUID(conversation).hex / 'base_state.json'
    state = json.loads(state_path.read_text())
    state['agent_state']['acp_session_id'] = str(uuid.uuid4())
    state_path.write_text(json.dumps(state))
    with pytest.raises(OSError):
        metadata.observe(home, codex, 'claude-code', conversation)


def test_native_metadata_refuses_symlink_and_oversized_private_log(tmp_path, monkeypatch):
    home, codex, conversation, _, path, _ = fixture(tmp_path, 'codex')
    monkeypatch.setattr(metadata, 'MAX_FILE', 1)
    with pytest.raises(ValueError, match='too large'):
        metadata.observe(home, codex, 'codex', conversation)
    monkeypatch.setattr(metadata, 'MAX_FILE', 64 * 1024 * 1024)
    path.unlink()
    path.symlink_to('/etc/passwd')
    with pytest.raises(OSError):
        metadata.observe(home, codex, 'codex', conversation)


# Sanitized metadata of the observed steering control record (#6618); no conversation content.
def control_row(session):
    return {'type': 'assistant', 'sessionId': session, 'timestamp': '2026-11-14T07:33:33.081Z',
            'isApiErrorMessage': False,
            'message': {'model': '<synthetic>', 'content': [{'type': 'text', 'text': 'No response requested.'}],
                        'stop_reason': 'stop_sequence',
                        'usage': {'output_tokens_details': None, 'input_tokens': 0, 'output_tokens': 0,
                                  'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0,
                                  'server_tool_use': {'web_search_requests': 0, 'web_fetch_requests': 0},
                                  'service_tier': None,
                                  'cache_creation': {'ephemeral_1h_input_tokens': 0, 'ephemeral_5m_input_tokens': 0},
                                  'inference_geo': None, 'iterations': None, 'speed': None,
                                  'fallback_credit': None}}}


def claude_rows(session, model='claude-sonnet-5-5', count=27):
    return [{'type': 'assistant', 'sessionId': session, 'timestamp': f'2026-11-14T07:{i:02d}:00.000Z',
             'message': {'model': model, 'content': 'private'}} for i in range(count)]


def test_claude_steering_control_record_is_skipped_after_same_session_validation(tmp_path):
    home, codex, conversation, session, path, _ = fixture(tmp_path, 'claude-code')
    rows = claude_rows(session)
    write_lines(path, rows[:20] + [control_row(session)] + rows[20:])
    result = metadata.observe(home, codex, 'claude-code', conversation)
    assert result == {'engine': 'claude-code', 'conversation_id': conversation, 'session_id': session,
                      'model': 'claude-sonnet-5-5', 'effort': None, 'timestamp': rows[-1]['timestamp']}
    write_lines(path, rows + [control_row(session)])
    assert metadata.observe(home, codex, 'claude-code', conversation)['timestamp'] == rows[-1]['timestamp']


def _mutate(path, value):
    def apply(row):
        *parents, leaf = path
        target = row
        for key in parents:
            target = target[key]
        if value is KeyError:
            del target[leaf]
        else:
            target[leaf] = value
        return row
    return apply


@pytest.mark.parametrize('change', [
    _mutate(('sessionId',), 'ce21fe8b-680e-4597-9878-b80052fa2b1b'),
    _mutate(('timestamp',), KeyError),
    _mutate(('timestamp',), 'not-a-time'),
    _mutate(('isApiErrorMessage',), KeyError),
    _mutate(('message', 'content'), [{'type': 'text', 'text': 'Something else.'}]),
    _mutate(('message', 'content'), [{'type': 'text', 'text': 'No response requested.'},
                                     {'type': 'tool_use', 'name': 'x'}]),
    _mutate(('message', 'stop_reason'), 'end_turn'),
    _mutate(('message', 'role'), 'user'),
    _mutate(('message', 'usage'), KeyError),
    _mutate(('message', 'usage'), 'zero'),
    _mutate(('message', 'usage', 'input_tokens'), 1),
    _mutate(('message', 'usage', 'output_tokens'), KeyError),
    _mutate(('message', 'usage', 'cache_read_input_tokens'), False),
    _mutate(('message', 'usage', 'cache_creation_input_tokens'), '0'),
    _mutate(('message', 'usage', 'unknown_counter'), 0),
    _mutate(('message', 'usage', 'service_tier'), 'standard'),
    _mutate(('message', 'usage', 'server_tool_use', 'web_search_requests'), 2),
    _mutate(('message', 'usage', 'cache_creation', 'other'), 0),
    _mutate(('message', 'usage', 'cache_creation'), [0]),
])
def test_claude_synthetic_records_outside_the_control_shape_refuse(tmp_path, change):
    home, codex, conversation, session, path, _ = fixture(tmp_path, 'claude-code')
    write_lines(path, claude_rows(session) + [change(control_row(session))])
    with pytest.raises(ValueError):
        metadata.observe(home, codex, 'claude-code', conversation)


def test_claude_control_never_substitutes_for_single_model_execution(tmp_path):
    home, codex, conversation, session, path, _ = fixture(tmp_path, 'claude-code')
    write_lines(path, [control_row(session)])
    with pytest.raises(ValueError, match='missing'):
        metadata.observe(home, codex, 'claude-code', conversation)
    write_lines(path, claude_rows(session, count=2) + [control_row(session)]
                + claude_rows(session, model='claude-opus-5-5', count=1))
    with pytest.raises(ValueError, match='mixed'):
        metadata.observe(home, codex, 'claude-code', conversation)


def test_claude_api_error_record_keeps_existing_skip(tmp_path):
    home, codex, conversation, session, path, _ = fixture(tmp_path, 'claude-code')
    error = {'type': 'assistant', 'isApiErrorMessage': True, 'message': {'model': '<synthetic>'}}
    write_lines(path, claude_rows(session, count=1) + [error])
    assert metadata.observe(home, codex, 'claude-code', conversation)['model'] == 'claude-sonnet-5-5'
    write_lines(path, [error])
    with pytest.raises(ValueError, match='missing'):
        metadata.observe(home, codex, 'claude-code', conversation)


def test_controller_command_form_emits_only_allowlisted_metadata(tmp_path):
    home, codex, conversation, session, path, _ = fixture(tmp_path, 'claude-code')
    write_lines(path, claude_rows(session) + [control_row(session)])
    source = Path(metadata.__file__).read_text(encoding='utf-8')
    done = subprocess.run([sys.executable, '-I', '-c', source, str(home), str(codex), 'claude-code', conversation],
                          capture_output=True, text=True, timeout=30, check=False)
    assert done.returncode == 0, done.stderr
    assert set(json.loads(done.stdout)) == {'engine', 'conversation_id', 'session_id', 'model', 'effort', 'timestamp'}
    assert 'private' not in done.stdout and 'No response' not in done.stdout
