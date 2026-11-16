"""Independent peer authority for candidate lifecycle tests."""
import copy
import subprocess
import time
from datetime import datetime, timezone

import pytest

from app.builderops import openhands_pr_cycle as cycle


def registered_peer(tmp_path, monkeypatch, layout, entry, real_lifecycle_owner):
    source = cycle.Path(entry['lifecycle_repo'])
    checkout = tmp_path / 'peer-owner'
    subprocess.run(['git', '-C', str(source), 'worktree', 'add', '-b', 'b/peer',
                    str(checkout), entry['head_sha']], check=True, capture_output=True, text=True)
    now = int(time.time())
    cycle.agent_worktree.register_worktree(source, worktree=checkout, owner='peer-session',
                                           now=now - 30, ttl_seconds=3600)
    peer = {**entry, 'number': 9, 'worker': 'peer', 'claimant': 'peer-owner',
            'session': 'peer-session', 'lease_id': 'peer-lease', 'owner_worktree': str(checkout.resolve())}
    previous_lifecycle = cycle._lifecycle_owner
    monkeypatch.setattr(cycle, '_lifecycle_owner', lambda layout, admitted, branch:
                        real_lifecycle_owner(layout, admitted, branch) if branch == 'b/peer'
                        else previous_lifecycle(layout, admitted, branch))
    task_id = cycle.github_issue_task_id(cycle.completion.REPOSITORY, 6619)
    task = {'task_id': task_id, 'repo': cycle.completion.REPOSITORY, 'issue_number': 6619,
            'status': 'claimed', 'claimed_by': 'peer-owner', 'lease_id': 'peer-lease',
            'lease_expires_at': '2099-01-01T00:00:00Z', 'linked_pr': 9}
    lease = {'lease_id': 'peer-lease', 'holder': 'peer-owner', 'resource': 'issue:6619',
             'expires_at': task['lease_expires_at'], 'released_at': None}
    events = [{'task_id': task_id, 'event_type': 'task.claimed', 'actor': 'peer-owner',
               'lease_id': 'peer-lease', 'timestamp': datetime.fromtimestamp(now - 20, timezone.utc).isoformat(),
               'payload': {'session': 'peer-session', 'ttl_minutes': 90}}]
    previous_dispatcher = cycle.closure._dispatcher_inspect
    monkeypatch.setattr(cycle.closure, '_dispatcher_inspect', lambda executor, cwd, current:
                        (task, events, lease) if current == task_id else previous_dispatcher(executor, cwd, current))
    registration, records = real_lifecycle_owner(layout, peer, 'b/peer')
    history = dict(registration=registration, records=records, comments=[], issue_comments=[], events=events,
                   origin={}, origin_at=None, issue=6619, pr_number=9, branch='b/peer', entry=peer)
    assert registration['owner'] == 'peer-session' and registration['path'] == str(checkout.resolve())
    assert cycle._claimant_history(**history) == []
    foreign = copy.deepcopy(events)
    foreign[0]['payload']['session'] = 'foreign-session'
    with pytest.raises(cycle.CycleError, match='current claimant differs'):
        cycle._claimant_history(**{**history, 'events': foreign})
    return peer
