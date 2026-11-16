"""Stopped-source candidate binding through the PR cycle with isolated ports."""
from pathlib import Path

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from app.builderops.publication import CommandResult
from tests.builderops.test_openhands_pr_cycle import HEAD, fetch
from tests.builderops.test_openhands_pr_cycle_repair_author import repair_setup

CANDIDATE = 'd' * 40
TREE = 'b' * 40


def setup_candidate(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path / 'worker', monkeypatch)
    host = (tmp_path / 'publisher').resolve()
    host.mkdir()
    registration = {'path': str(host), 'branch': 'codex/example', 'owner': 'builder-session-6618',
                    'generation': '1' * 32, 'registration_epoch': '2' * 32, 'expires_at': 9999999999}
    authority = {'owner': {'lease_id': 'synthetic-lease'}, 'claim_issue': 6618,
                 'head_sha': HEAD, 'branch': 'codex/example', 'worktree_owner': registration}
    monkeypatch.setattr(cycle, 'native_authority', lambda *args, **kwargs: dict(authority))
    config[0]['owner_worktree'] = str(host)
    assert binding_tick(layout, config, server)['action'] == 'repair-author'
    author = cycle._mapping(layout, 'reviewer')['conversation']
    server.conversations[author['id']]['execution_status'] = 'finished'
    monkeypatch.setattr(cycle, 'native_execution_proof', lambda layout, worker, op, admission, **kwargs: {
        'operation_id': op, 'conversation_id': author['id'], 'container_id': 'e' * 64,
        'engine': admission['engine'], 'model': admission['model']})
    def stop(layout, worker, **kwargs):
        mapping = cycle._mapping(layout, worker)
        stop_id = kwargs['stop_intent']['stop_id']
        checkpoint = {'ref': 'refs/checkpoints/ckpt-0001', 'status': 'preserved', 'tree': TREE,
                      'ignored_count': 0, 'branch': mapping['branch']}
        work = {'stop_id': stop_id, 'present': True, 'readable': True, 'unique_work': True,
                'branch': mapping['branch'], 'head': HEAD, 'checkpoint': checkpoint}
        ew._record_worker(layout, 6618, state='stopped_verified', stop_id=stop_id, work_at_stop=work,
                          checkpoints=[checkpoint], conversation={**mapping['conversation'], 'status': ew.CONVERSATION_ENDED})
    monkeypatch.setattr(ew, 'stop_worker', stop)
    class GitPort:
        def __init__(self, **kwargs):
            self.calls = []
        def run(self, argv, *, cwd, input_text=None):
            args = tuple(argv)
            self.calls.append(args)
            assert Path(cwd) == host
            if args == ('git', 'rev-parse', '--show-toplevel'):
                output = str(host)
            elif args == ('git', 'branch', '--show-current'):
                output = 'codex/example'
            elif args == ('git', 'rev-parse', 'HEAD'):
                output = CANDIDATE
            elif args == ('git', 'rev-parse', 'HEAD^{tree}'):
                output = TREE
            elif args[:3] == ('git', 'merge-base', '--is-ancestor'):
                output = ''
            elif args[:2] in (('git', 'diff'), ('git', 'ls-files')):
                output = ''
            else:
                raise AssertionError(args)
            return CommandResult(args, 0, output + ('\n' if output else ''), '')
    port = GitPort()
    monkeypatch.setattr(cycle, 'SubprocessExecutor', lambda **kwargs: port)
    config[0]['repair_publication'] = {'candidate_head': CANDIDATE}
    return layout, config, server, authority, port


def get_receipt(layout):
    return next(r for r in ew._load_state(layout)['compact_receipts'] if r.get('repair_operation'))


def binding_tick(layout, config, server):
    # These legacy fixtures exercise binding/rebinding an explicitly prepared publisher
    # candidate, not the later automatic reviewer (covered by candidate_dispatch_v2).
    # advance() now resumes that reviewer once repair_candidate exists; call the real
    # original binding consumer so it re-observes publisher drift and invalidates old data.
    pr = cycle.observation.collect(fetch)["observations"][1]
    with cycle._single_advancement(layout):
        try:
            return cycle._advance_one(layout, pr, config[0], http=server)
        except cycle.CycleError as exc:
            return {"action": "wait", "reason": str(exc)}


def test_candidate_is_bound_to_stopped_tree_and_waits_for_review(tmp_path, monkeypatch):
    layout, config, server, _, port = setup_candidate(tmp_path, monkeypatch)
    row = binding_tick(layout, config, server)
    assert row['action'] == 'awaiting-candidate-review', row
    receipt = get_receipt(layout)
    assert receipt['repair_candidate']['candidate_head'] == CANDIDATE
    assert receipt['repair_candidate']['tree'] == TREE
    assert receipt['repair_candidate']['stop_id'] == receipt['repair_stop_intent']['stop_id']
    assert not any(call[:2] in (('git', 'push'), ('gh', 'pr')) for call in port.calls)
    again = binding_tick(layout, config, server)
    assert again['action'] == 'awaiting-candidate-review'
    assert len([c for c in server.calls if c[0] == 'POST']) == 2


@pytest.mark.parametrize('changed', ['tree', 'owner', 'head'])
def test_changed_candidate_or_authority_holds_without_effect(tmp_path, monkeypatch, changed):
    layout, config, server, authority, port = setup_candidate(tmp_path, monkeypatch)
    if changed == 'owner':
        authority['owner'] = {'lease_id': 'another-lease'}
    elif changed == 'head':
        config[0]['repair_publication']['candidate_head'] = 'c' * 40
    else:
        original = port.run
        def run(argv, **kwargs):
            if tuple(argv) == ('git', 'rev-parse', 'HEAD^{tree}'):
                return CommandResult(tuple(argv), 0, 'c' * 40 + '\n', '')
            return original(argv, **kwargs)
        port.run = run
    row = binding_tick(layout, config, server)
    assert row['action'] == 'wait'
    assert 'repair_candidate' not in get_receipt(layout)
    assert not any(call[:2] in (('git', 'push'), ('gh', 'pr')) for call in port.calls)


def test_prior_candidate_observation_is_invalidated_when_head_drifts(tmp_path, monkeypatch):
    layout, config, server, _, _ = setup_candidate(tmp_path, monkeypatch)
    assert binding_tick(layout, config, server)['action'] == 'awaiting-candidate-review'
    config[0]['repair_publication']['candidate_head'] = 'c' * 40
    assert binding_tick(layout, config, server)['action'] == 'wait'
    assert 'repair_candidate' not in get_receipt(layout)
