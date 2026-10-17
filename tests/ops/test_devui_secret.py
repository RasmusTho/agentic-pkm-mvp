from __future__ import annotations

from contextlib import nullcontext
from io import StringIO
import json
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from app.ops import devui_secret
from app.ops.bws_secret_admin import (
    BwsAdminConfig, BwsSecretAdmin, DEVUI_IDENTITY, SecretAdminError, SecretCopy,
)
from app.ops.host_secret_controller import HostSecretAdmissionError, HostSecretController
from app.ops.secret_admin import SecretAdmin, main

TOKEN = 'github_pat_fake_devui_canary_12345678901234567890'
OLD = 'ghp_old_devui_canary_12345678901234567890'


class Provider:
    def __init__(self):
        self.values = {('non-prod', 'shared/github.token'): SecretCopy(str(uuid4()), OLD, '')}
        self.calls = []

    def read(self, project, identity):
        self.calls.append(('read', project, identity))
        return self.values.get((project, identity))

    def put(self, project, identity, previous, value, note):
        self.calls.append(('put', project, identity))
        copy = SecretCopy(previous.item_id if previous else str(uuid4()), value, note)
        self.values[project, identity] = copy
        return copy


@pytest.fixture
def setup(tmp_path):
    provider = Provider()
    controller = HostSecretController(tmp_path / 'controller')
    return SecretAdmin(provider, controller=controller), provider, controller


def test_devui_import_is_separate_and_keeps_prior_consumer_unchanged(setup, capsys):
    admin, provider, controller = setup
    assert main(['devui', 'import', '--stdin'], admin=admin, stdin=StringIO(TOKEN)) == 0
    assert {identity for _, _, identity in provider.calls} == {DEVUI_IDENTITY}
    assert provider.values['non-prod', DEVUI_IDENTITY].value == TOKEN
    assert provider.values['non-prod', 'shared/github.token'].value == OLD
    history = (controller.directory / 'secret-history.jsonl').read_text()
    assert '"previous_state": "absent"' in history
    assert TOKEN not in str(capsys.readouterr())


@pytest.mark.parametrize('value', [TOKEN + '\n', 'malformed', TOKEN + '\nmalicious: yes'])
def test_devui_import_rejects_invalid_input_before_provider_access(setup, value, capsys):
    admin, provider, _ = setup
    assert main(['devui', 'import', '--stdin'], admin=admin, stdin=StringIO(value)) == 1
    assert provider.calls == []
    assert TOKEN not in str(capsys.readouterr())


def test_devui_store_scope_cannot_target_prod_or_alias_shared_token():
    cfg = BwsAdminConfig(str(uuid4()), str(uuid4()), str(uuid4()))
    provider = BwsSecretAdmin(cfg)
    assert provider._scope('non-prod', DEVUI_IDENTITY) == cfg.non_prod_project_id
    for project, identity in [('prod', DEVUI_IDENTITY), ('non-prod', 'dev/devui.github-token'),
                              ('prod', 'shared/devui.github-token')]:
        with pytest.raises(SecretAdminError):
            provider._scope(project, identity)


def receipt(operation_id, result='committed'):
    return dict(operation_id=operation_id, kind='deploy', target='bob-1', result=result,
                source='remote-terminal', container_id='abc',
                github_reads='passed' if result == 'committed' else 'failed')


def test_devui_apply_holds_controller_and_reads_durable_receipt(setup, monkeypatch, capsys):
    admin, provider, controller = setup
    provider.values['non-prod', DEVUI_IDENTITY] = SecretCopy(str(uuid4()), TOKEN, '')
    calls = []
    def remote(action, operation_id='-', value=None):
        calls.append((action, operation_id, value))
        with pytest.raises(HostSecretAdmissionError):
            with controller.admit('check', 'dev'):
                pass
        return receipt(operation_id)
    monkeypatch.setattr(devui_secret, '_remote', remote)
    assert main(['devui', 'apply'], admin=admin) == 0
    assert [c[0] for c in calls] == ['apply', 'receipt']
    assert calls[0][2] == TOKEN and calls[1][2] is None
    assert TOKEN not in str(capsys.readouterr())
    with controller.admit('check', 'dev') as op:
        from app.ops.host_secret_controller import TerminalEvidence
        op.finish(TerminalEvidence(op.operation_id, op.kind, op.target, 'committed', 'read-complete'))


def test_missing_devui_token_does_not_poison_controller(setup):
    admin, _, controller = setup
    assert main(['devui', 'apply'], admin=admin) == 1
    assert not (controller.directory / 'operations.jsonl').read_text()


def test_lost_ssh_outcome_stays_pending_and_reconcile_does_not_resend(setup, monkeypatch):
    admin, provider, controller = setup
    provider.values['non-prod', DEVUI_IDENTITY] = SecretCopy(str(uuid4()), TOKEN, '')
    def unavailable(*args):
        raise SecretAdminError()
    monkeypatch.setattr(devui_secret, '_remote', unavailable)
    assert main(['devui', 'apply'], admin=admin) == 1
    with pytest.raises(HostSecretAdmissionError):
        with controller.admit('check', 'dev'):
            pass
    calls = []
    def readback(action, operation_id='-', value=None):
        calls.append((action, value))
        return receipt(operation_id)
    monkeypatch.setattr(devui_secret, '_remote', readback)
    assert main(['devui', 'reconcile'], admin=admin) == 0
    assert calls == [('receipt', None)]


def test_known_remote_abort_clears_pending_without_claiming_success(setup, monkeypatch):
    admin, provider, _ = setup
    provider.values['non-prod', DEVUI_IDENTITY] = SecretCopy(str(uuid4()), TOKEN, '')
    monkeypatch.setattr(devui_secret, '_remote', lambda action, operation_id, *args:
                        receipt(operation_id, 'aborted'))
    assert main(['devui', 'apply'], admin=admin) == 1
    assert main(['devui', 'check'], admin=admin) == 0


def test_ssh_value_uses_stdin_only_and_errors_are_redacted(monkeypatch, capsys):
    seen = []
    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return NS(returncode=1, stdout=TOKEN, stderr=TOKEN)
    monkeypatch.setattr(devui_secret.subprocess, 'run', run)
    with pytest.raises(SecretAdminError):
        devui_secret._remote('apply', str(uuid4()), TOKEN)
    argv, kwargs = seen[0]
    assert TOKEN not in str(argv) and TOKEN not in str(kwargs['env'])
    assert kwargs['input'] == TOKEN
    assert TOKEN not in str(capsys.readouterr())


def test_rotate_preflights_before_hidden_input_and_refuses_echo_fallback(setup, monkeypatch):
    import getpass
    import os
    import warnings
    admin, provider, _ = setup
    calls = []
    actual_open = os.open
    monkeypatch.setattr(devui_secret.os, 'open', lambda p, *a, **kw:
                        actual_open(os.devnull, os.O_RDWR) if p == '/dev/tty'
                        else actual_open(p, *a, **kw))
    def remote(*args):
        calls.append('preflight')
        return {'status': 'ready'}
    def hidden(*args):
        assert calls == ['preflight']
        warnings.warn('terminal cannot disable echo', getpass.GetPassWarning)
        raise AssertionError('must not read echoed input')
    monkeypatch.setattr(devui_secret, '_remote', remote)
    monkeypatch.setattr(getpass, 'getpass', hidden)
    assert main(['devui', 'rotate'], admin=admin) == 1
    assert not any(call[0] == 'put' for call in provider.calls)


def remote_namespace():
    namespace = {}
    # Load the exact deployed functions without executing its SSH main/lock.
    exec(devui_secret.REMOTE.split('\ntry:\n    lock =')[0], namespace)
    return namespace


def hosts():
    return ('github.com:\n    users:\n        RasmusTho:\n            oauth_token: ' + OLD
            + '\n        Other:\n            oauth_token: unrelated\n    git_protocol: https\n'
            + '    oauth_token: ' + OLD + '\n    user: RasmusTho\n'
            + 'other.example:\n    oauth_token: unrelated\n').encode()


def test_remote_updates_both_active_entries_and_preserves_other_accounts():
    namespace = remote_namespace()
    assert namespace['updated'](hosts(), TOKEN) == hosts().replace(OLD.encode(), TOKEN.encode())
    with pytest.raises(ValueError):
        namespace['updated'](hosts().replace(b'user: RasmusTho', b'user: Other'), TOKEN)


@pytest.mark.parametrize('failed_barrier', [None, 1, 2])
def test_receipt_readback_establishes_both_durable_barriers(tmp_path, monkeypatch,
                                                          capsys, failed_barrier):
    ns = remote_namespace()
    operation_id = str(uuid4())
    path = tmp_path / ('devui-github-token-' + operation_id + '.json')
    path.write_text(json.dumps(receipt(operation_id)))
    path.chmod(0o600)
    ns.update(RECEIPTS=tmp_path, preflight=lambda: 'same-container')
    monkeypatch.setattr(ns['sys'], 'argv', ['remote', 'receipt', operation_id])
    actual_fstat = ns['os'].fstat
    def fstat(fd):
        s = actual_fstat(fd)
        return NS(st_mode=s.st_mode, st_uid=0, st_nlink=s.st_nlink, st_size=s.st_size)
    monkeypatch.setattr(ns['os'], 'fstat', fstat)
    barriers = []
    def fsync(fd):
        barriers.append(fd)
        if len(barriers) == failed_barrier:
            raise OSError('injected durability failure')
    monkeypatch.setattr(ns['os'], 'fsync', fsync)
    if failed_barrier:
        with pytest.raises(OSError):
            ns['main']()
        assert not capsys.readouterr().out
    else:
        ns['main']()
        assert len(barriers) == 2
        assert json.loads(capsys.readouterr().out)['operation_id'] == operation_id


@pytest.mark.parametrize('read_fails', [False, True])
def test_remote_real_file_activation_preserves_modes_and_rolls_back(tmp_path, monkeypatch,
                                                                  capsys, read_fails):
    ns = remote_namespace()
    base = tmp_path / 'devui-gh'
    base.mkdir()
    path = base / 'hosts.yml'
    path.write_bytes(hosts())
    path.chmod(0o640)
    before = path.stat()
    receipts = tmp_path / 'receipts'
    receipts.mkdir()
    operation_id = str(uuid4())
    ns.update(BASE=base, HOSTS=path, RECEIPTS=receipts, preflight=lambda: 'same-container')
    def docker(*args):
        assert args[:3] == ('exec', 'builderops-devui-devui-1', 'gh')
        if read_fails:
            raise RuntimeError(TOKEN)
        return b'object'
    ns['docker'] = docker
    monkeypatch.setattr(ns['urllib'].request, 'urlopen', lambda *a, **kw: nullcontext(NS(status=200)))
    monkeypatch.setattr(ns['sys'], 'argv', ['remote', 'apply', operation_id])
    monkeypatch.setattr(ns['sys'], 'stdin', StringIO(TOKEN))
    ns['main']()
    assert path.stat().st_mode == before.st_mode
    assert (path.stat().st_uid, path.stat().st_gid) == (before.st_uid, before.st_gid)
    assert path.read_bytes() == (hosts() if read_fails else hosts().replace(OLD.encode(), TOKEN.encode()))
    saved = json.loads((receipts / ('devui-github-token-' + operation_id + '.json')).read_text())
    assert saved['result'] == ('aborted' if read_fails else 'committed')
    assert TOKEN not in str(capsys.readouterr()) and OLD not in json.dumps(saved)
    assert not list(base.glob('.hosts-*'))
