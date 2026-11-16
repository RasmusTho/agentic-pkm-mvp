"""Bound the #6560 body intent to an existing authenticated comment and exact bytes."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import datetime, timezone

import pytest

from scripts import legacy_6560_publication_gate as gate


@pytest.fixture
def intent_case(tmp_path, monkeypatch):
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    body = 'Governing-Issue: #6560\n\n<!-- operator-publication-attempt:' + '1' * 32 + ' -->\n'
    body_file = tmp_path / 'reviewed-body.txt'
    body_file.write_text(body)
    # Simulate GitHub's second-resolution creation time after the file exists.
    now = time.time()
    created = datetime.fromtimestamp(now + 3, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    monkeypatch.setattr(gate.time, 'time', lambda: now + 5)
    intent = {'issue': 6560, 'pr': 6565, 'repository': 'RasmusTho/agentic-pkm-mvp',
              'branch': 'codex/example', 'session': 'successor-session', 'agent': 'successor-agent',
              'lease_id': 'lease-successor', 'head': 'a' * 40, 'before_body_sha256': 'b' * 64,
              'body_sha256': hashlib.sha256(body.encode()).hexdigest(), 'body': body,
              'attempt_id': '1' * 32, 'reviewed': True}
    comment = {'id': 7, 'node_id': 'IC_example', 'performed_via_github_app': None,
               'issue_url': 'https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6560',
               'user': {'login': 'RasmusTho', 'id': 123, 'node_id': 'U_example', 'type': 'User'},
               'author_association': 'OWNER', 'created_at': created,
               'updated_at': created, 'body': json.dumps({'operator_publication_intent.v1': intent})}
    comments = [comment]
    monkeypatch.setattr(gate.agent_worktree, '_read_github_transfer_comment', lambda _id, **_kwargs: comment)
    monkeypatch.setattr(gate.recovery, '_operator_comments', lambda **_kwargs: comments)
    args = {'cwd': worktree, 'worktree': worktree, 'comment_id': 7, 'body_file': body_file,
            'branch': 'codex/example', 'session': 'successor-session', 'agent': 'successor-agent',
            'lease': 'lease-successor'}
    return intent, comment, comments, args


def test_exact_authenticated_comment_supplies_body_intent(intent_case):
    intent, comment, _, args = intent_case
    actual, source = gate._body_intent(**args)
    assert actual == intent and source == comment


def test_listed_comment_may_have_different_avatar_metadata(intent_case):
    intent, comment, comments, args = intent_case
    comment['user'].update({'id': 123, 'node_id': 'U_example', 'type': 'User',
                            'avatar_url': 'https://example.invalid/avatar?size=48'})
    listed = copy.deepcopy(comment)
    listed['user']['avatar_url'] = 'https://example.invalid/avatar?size=96'
    comments[:] = [listed]
    actual, _ = gate._body_intent(**args)
    assert actual == intent


@pytest.mark.parametrize('field', [
    'id', 'node_id', 'issue_url', 'body', 'created_at', 'updated_at', 'author_association',
    'user.login', 'user.id', 'user.node_id', 'user.type', 'performed_via_github_app',
])
def test_listed_comment_refuses_authority_or_content_drift(intent_case, field):
    _, comment, comments, args = intent_case
    listed = copy.deepcopy(comment)
    if field.startswith('user.'):
        listed['user'][field.split('.', 1)[1]] = 'different'
    elif field == 'body':
        listed[field] += ' '
    elif field == 'performed_via_github_app':
        listed[field] = {'id': 456, 'node_id': 'A_example', 'slug': 'different-app'}
    else:
        listed[field] = 'different'
    comments[:] = [listed]
    with pytest.raises(gate.PublicationProofError):
        gate._body_intent(**args)


@pytest.mark.parametrize('field', ['node_id', 'user.id', 'user.node_id', 'user.type',
                                   'performed_via_github_app'])
def test_intent_refuses_missing_stable_identity(intent_case, field):
    _, comment, _, args = intent_case
    if field.startswith('user.'):
        del comment['user'][field.split('.', 1)[1]]
    else:
        del comment[field]
    with pytest.raises(gate.PublicationProofError):
        gate._body_intent(**args)


@pytest.mark.parametrize('change', [
    'issue', 'pr', 'repository', 'branch', 'session', 'agent', 'lease_id', 'head',
    'body_sha256', 'body', 'attempt_id', 'reviewed', 'extra', 'foreign_author',
    'foreign_target', 'edited', 'duplicate', 'missing', 'late_file', 'extra_marker',
])
def test_body_intent_refuses_mismatched_or_unknown_source(intent_case, change):
    intent, comment, comments, args = intent_case
    if change in {'issue', 'pr', 'repository', 'branch', 'session', 'agent', 'lease_id',
                  'head', 'body_sha256', 'body', 'attempt_id', 'reviewed'}:
        intent[change] = False if change == 'reviewed' else 'foreign'
        comment['body'] = json.dumps({'operator_publication_intent.v1': intent})
    elif change == 'extra':
        intent['source'] = 'arbitrary caller assertion'
        comment['body'] = json.dumps({'operator_publication_intent.v1': intent})
    elif change == 'foreign_author':
        comment['user']['login'] = 'someone-else'
    elif change == 'foreign_target':
        comment['issue_url'] += '1'
    elif change == 'edited':
        comment['updated_at'] = '2000-01-01T00:00:00Z'
    elif change == 'duplicate':
        other = copy.deepcopy(comment)
        other['id'] = 8
        comments.append(other)
    elif change == 'missing':
        comments.clear()
    elif change == 'late_file':
        comment['created_at'] = comment['updated_at'] = '2000-01-01T00:00:00Z'
    elif change == 'extra_marker':
        intent['body'] += '<!-- operator-publication-attempt:' + '2' * 32 + ' -->\n'
        intent['body_sha256'] = hashlib.sha256(intent['body'].encode()).hexdigest()
        comment['body'] = json.dumps({'operator_publication_intent.v1': intent})
    with pytest.raises((gate.PublicationProofError, ValueError)):
        gate._body_intent(**args)
