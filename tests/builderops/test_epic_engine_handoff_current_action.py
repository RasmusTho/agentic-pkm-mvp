"""Current task authority across interrupted synthetic quota continuations."""
import json
import subprocess

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_engine_handoff import CONTRACT, Harness, ISSUE, _git

OLD = "Review parser behavior and run test_parser_v1"
NEW = "Review router behavior and run test_router_v2"


def test_ordinary_handoff_after_interruption_uses_current_task_in_compact_context(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    assert h.main('worker-create','--worker','w-a','--issue',str(ISSUE),'--branch','b/a','--next-action',OLD) == 0
    capsys.readouterr()
    h.failure()
    h.engine.refuse_stop = True
    assert h.tick(capsys)[ISSUE]['handoff']['state'] == 'held'
    assert h.main('worker-create','--worker','w-a','--issue',str(ISSUE),'--branch','b/a','--next-action',NEW) == 0
    capsys.readouterr()
    h.engine.refuse_stop = False
    assert h.tick(capsys)[ISSUE]['handoff']['state'] == 'continued'
    prompt = h.posts()[-1][3]['initial_message']['content'][0]['text']
    context = json.loads(prompt.split('Compact controller records (unknown means not established):\n', 1)[1])
    print('ORDINARY_CONTINUATION='+json.dumps({'current_task':h.mapping()['next_action'],
          'context_task':context['next_action'],'old_in_prompt':OLD in prompt,'new_in_prompt':NEW in prompt}))
    assert NEW in prompt and context['next_action'] == NEW


@pytest.mark.parametrize('update_after_reservation', [False, True], ids=['unchanged-positive', 'new-task-after-interruption'])
def test_real_one_shot_review_cycle_uses_current_task_after_interrupted_handoff(tmp_path, capsys, monkeypatch, update_after_reservation):
    from app.builderops import openhands_pr_cycle as cycle
    h = Harness(tmp_path, capsys, start_conversation=False)
    h.server.react = False
    assert h.main('worker-create', '--worker', 'w-a', '--issue', str(ISSUE), '--branch', 'b/a', '--next-action', OLD) == 0
    capsys.readouterr()
    head = _git(h.layout.checkout('w-a'), 'rev-parse', 'HEAD')
    def fetch(path, timeout):
        if '/pulls?' in path:
            data = [{'number': 44}]
        elif '/pulls/44/reviews' in path:
            data = []
        elif '/pulls/44' in path:
            data = {'number':44, 'state':'open', 'body':'Governing-Issue: #6617', 'draft':False,
                    'labels':[], 'head':{'sha':head,'repo':{'full_name':cycle.completion.REPOSITORY}},
                    'base':{'sha':'b'*40,'ref':'main'}}
        elif '/issues/6617' in path:
            data = {'number':ISSUE,'state':'open','body':CONTRACT,'title':'Implement the slice','labels':[]}
        else:
            raise AssertionError(path)
        return 200, json.dumps(data).encode()
    def docker_read(argv, *, timeout):
        assert argv[:2] == ['docker','inspect']
        row = {'Id':h.mapping()['container_id'], 'Name':'/'+h.layout.container_name('w-a'),
               'State':{'Running':True}, 'Config':{'Labels':{ew.LABEL_EPIC:'6615',ew.LABEL_WORKER:'w-a'}}}
        return subprocess.CompletedProcess(argv,0,json.dumps([row]),'')
    inspect = ew.inspect_checkout
    monkeypatch.setattr(cycle,'_command',docker_read)
    monkeypatch.setattr(cycle,'_worker_runner',h.engine)
    monkeypatch.setattr(cycle,'_review_context',lambda pr: (
        {'files_digest':'synthetic','closing_issue_hashes':{},'check_config_digest':'synthetic'},
        {'diff':'synthetic diff','issues':{},'paths':['README.md']}))
    monkeypatch.setattr(ew,'inspect_checkout',lambda layout,worker,**kw: inspect(layout,worker,runner=h.engine))
    admission = [{'number':44,'head_sha':head,'worker':'w-a','engine':'claude-code',
                  'model':'claude-sonnet-5-5','native_session_owned':True,
                  'test_venv':'/synthetic/venv','verify_targets':['tests/example.py::test_step']}]
    first = cycle.advance(h.layout,admission,fetch=fetch,http=h.server)
    assert first['results'][0]['action'] == 'independent-review'
    operation = first['results'][0]['operation_id']
    h.old_conversation = h.mapping()['conversation']['id']
    h.server.streams[h.old_conversation] = []
    h.failure()
    checkpoint = ew._checkpoint
    def interrupt(*args, **kwargs):
        raise ew.EpicWorkspaceError('synthetic checkpoint interruption')
    monkeypatch.setattr(ew, '_checkpoint', interrupt)
    second = cycle.advance(h.layout,admission,fetch=fetch,http=h.server,codex_home=h.codex)
    assert second['results'][0]['engine_handoff']['state'] == 'held'
    assert h.mapping()['state'] == 'stopped_verified'
    if update_after_reservation:
        assert h.main('worker-create','--worker','w-a','--issue',str(ISSUE),'--branch','b/a','--next-action',NEW) == 0
        capsys.readouterr()
        assert h.mapping()['next_action'] == NEW
    monkeypatch.setattr(ew, '_checkpoint', checkpoint)
    third = cycle.advance(h.layout,admission,fetch=fetch,http=h.server,codex_home=h.codex)
    assert third['results'][0]['engine_handoff']['state'] == 'awaiting_pr_cycle'
    # A queued worker-create cannot change the task between context construction and create.
    from app.builderops import epic_engine_handoff
    original_context = epic_engine_handoff.continuation_context
    locked = []
    def context_under_lock(layout, worker, handoff):
        with pytest.raises(ew.LifecycleBusy):
            ew.create_worker(layout, worker, issue=ISSUE, branch='b/a', next_action='queued action', runner=h.engine)
        locked.append(True)
        return original_context(layout, worker, handoff)
    monkeypatch.setattr(epic_engine_handoff, 'continuation_context', context_under_lock)
    fourth = cycle.advance(h.layout,admission,fetch=fetch,http=h.server,codex_home=h.codex)
    assert locked == [True]
    assert fourth['results'][0]['action'] == 'reconcile'
    assert h.mapping()['conversation']['operation_id'] == operation
    assert h.mapping()['conversation']['engine'] == 'codex' and h.server.absence_at_successor == [True]
    prompt = h.posts()[-1][3]['initial_message']['content'][0]['text']
    wanted = NEW if update_after_reservation else OLD
    print('PR_CONTINUATION='+json.dumps({'updated':update_after_reservation,'current_task':h.mapping()['next_action'],
          'saved_task':h.mapping()['engine_handoff']['context']['next_action'],
          'old_in_prompt':OLD in prompt,'new_in_prompt':NEW in prompt,
          'posts':len(h.posts()),'owner':h.mapping()['lifecycle_owner'],
          'same_operation':h.mapping()['conversation']['operation_id']==operation}))
    assert wanted in prompt
    if update_after_reservation:
        assert OLD not in prompt


def test_explicit_task_equal_to_diagnostic_supersedes_saved_task(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    ew._mutate_mapping(h.layout, 'w-a', lambda mapping: ew._set_coordination_action(mapping, NEW))
    assert h.main('worker-create', '--worker', 'w-a', '--issue', str(ISSUE), '--branch', 'b/a', '--next-action', NEW) == 0
    capsys.readouterr()
    assert ew._continuation_task_action(h.mapping()) == NEW
    h.failure()
    assert h.tick(capsys)[ISSUE]['handoff']['state'] == 'continued'
    assert NEW in h.posts()[-1][3]['initial_message']['content'][0]['text']


def test_legacy_pending_task_update_is_current_authority(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    assert h.main('worker-create', '--worker', 'w-a', '--issue', str(ISSUE), '--branch', 'b/a', '--next-action', OLD) == 0
    capsys.readouterr()
    h.failure()
    h.engine.refuse_stop = True
    assert h.tick(capsys)[ISSUE]['handoff']['state'] == 'held'
    ew._mutate_mapping(h.layout, 'w-a', lambda mapping: mapping.pop('coordination_continuation', None))
    assert h.main('worker-create', '--worker', 'w-a', '--issue', str(ISSUE), '--branch', 'b/a', '--next-action', NEW) == 0
    capsys.readouterr()
    h.engine.refuse_stop = False
    assert h.tick(capsys)[ISSUE]['handoff']['state'] == 'continued'
    prompt = h.posts()[-1][3]['initial_message']['content'][0]['text']
    assert NEW in prompt and OLD not in prompt


@pytest.mark.parametrize('changed', ['owner', 'stop_generation', 'handoff'])
def test_stale_continuation_context_rejects_changed_authority(tmp_path, capsys, changed):
    from app.builderops import epic_engine_handoff as handoff_module
    h = Harness(tmp_path, capsys)
    h.failure()
    assert h.tick(capsys)[ISSUE]['handoff']['state'] == 'continued'
    handoff = h.mapping()['engine_handoff']
    if changed == 'owner':
        ew._record_worker(h.layout, ISSUE, lifecycle_owner='different-owner')
    elif changed == 'stop_generation':
        ew._record_worker(h.layout, ISSUE, stop_id='different-stop')
    else:
        ew._mutate_mapping(h.layout, 'w-a', lambda mapping: mapping['engine_handoff'].update(status='different'))
    with pytest.raises(ew.TakeoverRefused):
        handoff_module.continuation_context(h.layout, 'w-a', handoff)
    assert len(h.posts()) == 2
