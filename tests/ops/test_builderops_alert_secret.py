from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import builderops_alert_secret as alerts
from app.ops import builderops_probe_secret as bridge
from app.ops.bws_secret_admin import SecretAdminError, SecretCopy
from app.ops.host_secret_controller import HostSecretAdmissionError, HostSecretController
from app.ops.secret_admin import SecretAdmin, main

WEBHOOK = 'https://discord.com/api/webhooks/123456/fake_bounded_test_webhook'


@pytest.fixture
def admin(tmp_path):
    class Provider:
        calls = []

        def read(self, project, identity):
            self.calls.append((project, identity))
            return SecretCopy('fake-item-id', WEBHOOK, '')

    return SecretAdmin(Provider(), controller=HostSecretController(tmp_path / 'controller'))


def receipt(operation_id, result='committed'):
    return dict(schema='builderops_alert_handoff.v1', operation_id=operation_id,
                kind='deploy', target='bob-1', result=result, source='remote-terminal',
                engine_id='799a3d86-54f6-4208-b71a-36ae3eee61b6',
                consumer='heimdal-builderops-alerts')


def test_apply_uses_only_existing_shared_identity_and_exact_durable_receipt(admin, monkeypatch, capsys):
    calls = []

    def remote(action, operation_id='-', value=None):
        calls.append((action, operation_id, value))
        with pytest.raises(HostSecretAdmissionError):
            with admin.controller.admit('check', 'dev'):
                pass
        return receipt(operation_id)

    monkeypatch.setattr(alerts, 'remote', remote)
    assert main(['builderops-alerts', 'apply'], admin=admin) == 0
    assert admin.provider.calls == [('non-prod', 'shared/discord.webhook')]
    assert [call[0] for call in calls] == ['apply', 'receipt']
    assert calls[0][2] == WEBHOOK and calls[1][2] is None
    assert WEBHOOK not in str(capsys.readouterr())
    assert WEBHOOK not in (admin.controller.directory / 'operations.jsonl').read_text()


def test_unknown_handoff_cannot_resend_and_reconcile_reads_only_receipt(admin, monkeypatch):
    def unavailable(*args):
        raise SecretAdminError()

    monkeypatch.setattr(alerts, 'remote', unavailable)
    assert main(['builderops-alerts', 'apply'], admin=admin) == 1
    assert main(['builderops-alerts', 'apply'], admin=admin) == 1
    calls = []

    def recovered(action, operation_id='-', value=None):
        calls.append((action, value))
        return receipt(operation_id)

    monkeypatch.setattr(alerts, 'remote', recovered)
    assert main(['builderops-alerts', 'reconcile'], admin=admin) == 0
    assert calls == [('receipt', None)]


@pytest.mark.parametrize('field,value', [('target', 'prod'), ('consumer', 'heimdal-external-alerts'),
                                        ('engine_id', 'wrong'), ('operation_id', 'foreign'),
                                        ('source', 'ssh-success')])
def test_terminal_refuses_foreign_or_unbound_receipt(field, value):
    data = receipt('operation')
    data[field] = value
    with pytest.raises(SecretAdminError):
        alerts.terminal(data, 'operation')


def test_ssh_carries_webhook_only_on_stdin(monkeypatch):
    def run(arguments, **kwargs):
        assert WEBHOOK not in str(arguments)
        assert WEBHOOK not in str(kwargs.get('env'))
        assert kwargs['input'] == WEBHOOK
        assert 'bob-1-builder-system' in arguments
        assert 'StrictHostKeyChecking=yes' in arguments
        assert 'ClearAllForwardings=yes' in arguments
        assert 'ForwardAgent=no' in arguments
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(receipt('operation')))

    monkeypatch.setattr(alerts.subprocess, 'run', run)
    assert alerts.remote('apply', 'operation', WEBHOOK)['target'] == 'bob-1'


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    directory = tmp_path / 'runtime'
    directory.mkdir(mode=0o700)
    credential = tmp_path / 'credential'
    credential.write_text(WEBHOOK)
    credential.chmod(0o400)
    monkeypatch.setattr(bridge, 'CREDENTIAL', credential)
    monkeypatch.setattr(bridge, 'DIRECTORY', directory)
    monkeypatch.setattr(bridge, 'RUNTIME', directory / 'alerts.env')
    return credential, directory / 'alerts.env'


def test_runtime_bridge_writes_only_expected_binding_and_cleans_it(runtime):
    _, target = runtime
    bridge.materialize()
    assert target.read_text() == 'DISCORD_WEBHOOK=' + WEBHOOK + '\n'
    assert target.stat().st_mode & 0o777 == 0o600
    bridge.cleanup()
    assert not target.exists()


@pytest.mark.parametrize('mode', [0o600, 0o644, 0o640])
def test_runtime_bridge_rejects_overbroad_credential_before_file_effect(runtime, mode):
    credential, target = runtime
    credential.chmod(mode)
    with pytest.raises(ValueError):
        bridge.materialize()
    assert not target.exists()


def test_runtime_bridge_refuses_linked_input_and_output(runtime, tmp_path):
    credential, target = runtime
    sibling = tmp_path / 'hardlink'
    os.link(credential, sibling)
    with pytest.raises(ValueError):
        bridge.materialize()
    sibling.unlink()
    victim = tmp_path / 'victim'
    victim.write_text('preserve')
    target.symlink_to(victim)
    with pytest.raises(ValueError):
        bridge.materialize()
    with pytest.raises(ValueError):
        bridge.cleanup()
    assert victim.read_text() == 'preserve'


@pytest.mark.parametrize('value', [WEBHOOK + '\n', WEBHOOK + '?token=extra',
                                   'http://discord.com/api/webhooks/1/fake',
                                   'https://discord.com@evil.test/api/webhooks/1/fake'])
def test_runtime_bridge_refuses_malformed_credential_without_runtime_effect(runtime, value):
    credential, target = runtime
    credential.chmod(0o600)
    credential.write_text(value)
    credential.chmod(0o400)
    with pytest.raises(ValueError):
        bridge.materialize()
    assert not target.exists()


def test_service_and_plan_bind_the_standalone_bridge():
    unit = Path('config/systemd/yggdrasil-builderops-probe.service').read_text()
    assert 'LoadCredentialEncrypted=builderops-discord:/etc/yggdrasil/credentials/builderops-discord.cred' in unit
    assert 'ExecStartPre=/usr/bin/python3 -B -m app.ops.builderops_probe_secret materialize' in unit
    assert 'ExecStopPost=/usr/bin/python3 -B -m app.ops.builderops_probe_secret cleanup' in unit
    assert 'app/ops/builderops_probe_secret.py' in Path('scripts/plan_builderops_probe.py').read_text()
    # No Product secret/bootstrap imports are required by the standalone package.
    assert 'host_secret_bootstrap' not in Path(bridge.__file__).read_text()


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    """Execute the actual assembled receiver; substitute host/effect ports only."""
    namespace = {}
    exec(alerts.REMOTE.split('\ntry:\n    main()')[0], namespace)
    directory = tmp_path / 'credentials'
    directory.mkdir(mode=0o700)
    receipts = tmp_path / 'receipts'
    receipts.mkdir()
    lock = tmp_path / 'deployment.lock'
    lock.touch(mode=0o600)
    namespace.update(DIRECTORY=directory, TARGET=directory / 'webhook.cred',
                     RECEIPTS=receipts, LOCK=lock, preflight=lambda: None,
                     private=lambda *args, **kwargs: None)
    real_fstat = os.fstat

    class HostOS:
        def __getattr__(self, name):
            return getattr(os, name)

        def fstat(self, descriptor):
            info = real_fstat(descriptor)
            return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink, st_uid=0)

    namespace['os'] = HostOS()
    calls = []

    def command(arguments, **kwargs):
        calls.append(arguments)
        assert WEBHOOK not in str(arguments)
        if 'encrypt' in arguments:
            assert kwargs['input'] == WEBHOOK.encode()
            return SimpleNamespace(stdout=b'encrypted-test-ciphertext')
        assert kwargs['input'] == b'encrypted-test-ciphertext'
        return SimpleNamespace(stdout=b'')

    monkeypatch.setattr(namespace['subprocess'], 'run', command)
    monkeypatch.setattr(namespace['sys'], 'stdin', SimpleNamespace(buffer=BytesIO(WEBHOOK.encode())))
    operation_id = str(uuid4())
    monkeypatch.setattr(namespace['sys'], 'argv', ['receiver', 'apply', operation_id])
    return namespace, operation_id, calls


def test_assembled_receiver_persists_ciphertext_and_operation_bound_receipt(receiver, capsys):
    namespace, operation_id, calls = receiver
    namespace['main']()
    assert namespace['TARGET'].read_bytes() == b'encrypted-test-ciphertext'
    stored = json.loads((namespace['RECEIPTS'] / f'builderops-alerts-{operation_id}.json').read_text())
    assert stored == receipt(operation_id)
    assert len(calls) == 2
    assert WEBHOOK not in str(capsys.readouterr())


def test_assembled_receiver_compensates_postreplacement_failure(receiver, capsys):
    namespace, operation_id, _ = receiver
    target = namespace['TARGET']
    target.write_bytes(b'previous-encrypted-source')
    actual_replace = namespace['replace']
    attempted = False

    def fail_after_target_replacement(path, raw, mode):
        nonlocal attempted
        actual_replace(path, raw, mode)
        if path == target and not attempted:
            attempted = True
            raise OSError('injected postreplacement validation failure')

    namespace['replace'] = fail_after_target_replacement
    namespace['main']()
    assert target.read_bytes() == b'previous-encrypted-source'
    stored = json.loads((namespace['RECEIPTS'] / f'builderops-alerts-{operation_id}.json').read_text())
    assert stored == receipt(operation_id, 'aborted')
    assert WEBHOOK not in str(capsys.readouterr())


def test_assembled_receiver_syncs_new_credential_directory_before_terminal_receipt(receiver):
    namespace, operation_id, _ = receiver
    namespace['DIRECTORY'].rmdir()
    synced = []
    original = namespace['sync_directory']

    def observe(path):
        synced.append(path)
        original(path)

    namespace['sync_directory'] = observe
    namespace['main']()
    assert synced == [namespace['DIRECTORY'].parent, namespace['DIRECTORY'], namespace['RECEIPTS']]
    assert (namespace['RECEIPTS'] / f'builderops-alerts-{operation_id}.json').exists()


def test_first_install_compensation_syncs_removal_before_aborted_receipt(receiver):
    namespace, operation_id, _ = receiver
    actual = namespace['replace']
    events = []
    sync = namespace['sync_directory']

    def observe_sync(path):
        events.append(('sync', path, namespace['TARGET'].exists()))
        sync(path)

    def fail_after_target_replacement(path, raw, mode):
        actual(path, raw, mode)
        if path == namespace['TARGET']:
            raise ValueError('injected post-replacement validation refusal')
        events.append(('receipt', path, namespace['TARGET'].exists()))

    namespace.update(replace=fail_after_target_replacement, sync_directory=observe_sync)
    namespace['main']()
    assert not namespace['TARGET'].exists()
    assert ('sync', namespace['DIRECTORY'], False) in events
    assert events.index(('sync', namespace['DIRECTORY'], False)) < len(events) - 1
    data = json.loads((namespace['RECEIPTS'] / f'builderops-alerts-{operation_id}.json').read_text())
    assert data['result'] == 'aborted'


@pytest.mark.parametrize('point', ['created-directory', 'removed-credential'])
def test_failed_namespace_durability_cannot_write_terminal_receipt(receiver, point):
    namespace, operation_id, _ = receiver
    target = namespace['TARGET']
    actual_replace = namespace['replace']
    actual_sync = namespace['sync_directory']
    if point == 'created-directory':
        namespace['DIRECTORY'].rmdir()
    else:
        def fail_after_target(path, raw, mode):
            actual_replace(path, raw, mode)
            if path == target: raise ValueError('compensate first install')
        namespace['replace'] = fail_after_target

    def fail_sync(path):
        if ((point == 'created-directory' and path == namespace['DIRECTORY'].parent)
            or (point == 'removed-credential' and path == namespace['DIRECTORY'] and not target.exists())):
            raise namespace['DurabilityError']()
        actual_sync(path)

    namespace['sync_directory'] = fail_sync
    with pytest.raises(namespace['DurabilityError']):
        namespace['main']()
    assert not (namespace['RECEIPTS'] / f'builderops-alerts-{operation_id}.json').exists()
