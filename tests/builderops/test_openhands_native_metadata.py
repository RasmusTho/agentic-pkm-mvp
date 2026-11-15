import json
import uuid

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
