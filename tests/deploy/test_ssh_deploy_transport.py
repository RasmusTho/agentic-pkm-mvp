"""The normal HOST transport uses local fixture children, never SSH or credentials."""
from contextlib import contextmanager
from dataclasses import replace
import json
import subprocess
import sys
import time
import traceback
from uuid import uuid4

import pytest

from app.ops import postgres_deploy_linux as linux
from app.ops.postgres_deploy import (
    AuthorityCutover, DeployJournal, DeployPlan, PostgresDeployError,
)


_POPEN = subprocess.Popen
_ACTIONS = ('prepare', 'activate', 'join', 'reconcile-failed', 'reconcile-unknown', 'prove-absence')
_PRIVATE = 'fixture-private-payload'


@contextmanager
def _peer(monkeypatch, script, *, channel='test', configure=None):
    children, calls, resources = [], [], []

    def launch(argv, **kwargs):
        assert argv == [
            'ssh', '-o', 'BatchMode=yes', '--', 'ygg-' + channel,
            'sudo', '-n', '/usr/local/libexec/yggdrasil-bws-deploy', 'rpc', channel,
        ]
        calls.append(argv)
        child = _POPEN([sys.executable, '-I', '-c', script], **kwargs)
        children.append(child)
        resources.append((child.kill, child.wait, (child.stdin, child.stdout, child.stderr)))
        if configure is not None:
            configure(child)
        return child

    def unbounded(*_args, **_kwargs):
        pytest.fail('normal HOST request reached unbounded subprocess.run')

    monkeypatch.setattr(linux.subprocess, 'Popen', launch)
    monkeypatch.setattr(linux.subprocess, 'run', unbounded)
    try:
        yield children, calls
    finally:
        for child, (kill, wait, streams) in zip(children, resources):
            if child.poll() is None:
                kill()
            wait(timeout=2)
            for stream in streams:
                if stream is not None:
                    stream.close()


def _invoke(action, operation_id, plan):
    remote = linux.SshDeployRemote('ygg-' + plan.channel)
    if action == 'prepare':
        return remote.prepare(operation_id, plan, bootstrap=True)
    return getattr(remote, action.replace('-', '_'))(operation_id, plan)


def _fence(operation_id, plan):
    return {
        'contract': 'native-unknown-deploy-fence.v1',
        'operation_id': operation_id, 'channel': plan.channel,
        'candidate_sha': plan.revision, 'image_digest': plan.image_digest or '',
        'plan_sha256': DeployJournal.plan_fingerprint(plan), 'outcome': 'unknown',
        'native_worker_quiescent_at_fence': True, 'native_thread_absent_at_fence': True,
        'native_channel_lock_acquired_at_fence': True,
        'native_owned_one_offs_quiescent_at_fence': True, 'native_replay_fence_durable': True,
    }


def _reply(raw, *, returncode=0, stderr=b''):
    stderr_expression = (
        f'{stderr[:1]!r} * {len(stderr)}'
        if stderr and stderr == stderr[:1] * len(stderr) else repr(stderr)
    )
    return (
        'import os, sys\n'
        'sys.stdin.buffer.read()\n'
        f'os.write(1, {raw!r})\n'
        f'os.write(2, {stderr_expression})\n'
        f'sys.exit({returncode})\n'
    )


@pytest.mark.parametrize('action', _ACTIONS)
@pytest.mark.parametrize('fault', [
    'oversized-input', 'blocked-input', 'stalled', 'stdout-overflow', 'stderr-overflow',
    'continuous-stdout', 'continuous-stderr', 'exited-with-open-output',
])
def test_normal_request_enforces_finite_transport_limits(monkeypatch, action, fault):
    monkeypatch.setattr(linux, '_NORMAL_SSH_EXCHANGE_SECONDS', 0.3, raising=False)
    monkeypatch.setattr(linux, '_NORMAL_SSH_CLEANUP_SECONDS', 0.2, raising=False)
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',))
    if fault in {'oversized-input', 'blocked-input'}:
        plan = replace(plan, authority_cutover=AuthorityCutover(
            'fixture', '/' + 'x' * (65536 if fault == 'oversized-input' else 60000), '/owned',
        ))
    script = 'import time; time.sleep(10)'
    if fault.endswith('-overflow'):
        descriptor = 1 if fault == 'stdout-overflow' else 2
        script = f'import os; os.write({descriptor}, b"x" * 65537)'
    elif fault.startswith('continuous-'):
        descriptor = 1 if fault == 'continuous-stdout' else 2
        script = f'import os, time\nwhile True:\n os.write({descriptor}, b" "); time.sleep(.001)'
    elif fault == 'exited-with-open-output':
        script = 'import os, time\nif os.fork() == 0:\n time.sleep(.6); os._exit(0)\nos._exit(0)'
    written = []

    def track_input(child):
        if fault == 'blocked-input':
            original_write = linux.os.write
            descriptor = child.stdin.fileno()

            def write(fd, data):
                count = original_write(fd, data)
                if fd == descriptor:
                    written.append(count)
                return count

            monkeypatch.setattr(linux.os, 'write', write)

    with _peer(monkeypatch, script, configure=track_input) as (children, calls):
        started = time.monotonic()
        with pytest.raises(PostgresDeployError) as failure:
            _invoke(action, str(uuid4()), plan)
        assert time.monotonic() - started < 1.5
        assert len(calls) == (0 if fault == 'oversized-input' else 1)
        if fault == 'blocked-input':
            assert 0 < sum(written) < 60000
        if action == 'reconcile-unknown':
            assert failure.value.missing_predicate == 'native_rpc_returns_fence_evidence'
        for child in children:
            assert child.poll() is not None
            assert all(stream.closed for stream in (child.stdin, child.stdout, child.stderr))


@pytest.mark.parametrize('action', _ACTIONS)
@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_normal_request_preserves_protocol_and_refusal_semantics(monkeypatch, tmp_path, action, channel):
    operation_id = str(uuid4())
    plan = DeployPlan(channel, 'a' * 40, ('db',), ('postgres-db',),
                      image_digest='sha256:' + 'b' * 64, automatic=True)
    if action == 'prepare':
        # Bootstrap remains an exact input; automatic deployment itself uses False.
        plan = replace(plan, image_digest=None, automatic=False)
        response = {'ready': True, 'empty': True}
    elif action == 'reconcile-unknown':
        response = _fence(operation_id, plan)
    elif action == 'prove-absence':
        response = {
            'contract': 'native-deploy-operation-absence.v1', 'operation_id': operation_id,
            'channel': channel, 'candidate_sha': plan.revision, 'image_digest': plan.image_digest,
            'native_operation_absent': True, 'native_worker_absent': True,
            'native_lock_absent': True, 'native_request_absent': True,
        }
    else:
        # Manual receipts preserve the legacy shape without automatic qualification.
        plan = replace(plan, image_digest=None, automatic=False, ack_forward_only=True)
        stage = 'failed' if action == 'reconcile-failed' else 'committed'
        response = {'receipt': {
            'operation_id': operation_id, 'channel': channel, 'kind': 'deploy',
            'stage': stage, 'terminal_result': stage,
        }}
    wire = tmp_path / 'request.json'
    script = (
        'import pathlib, sys\n'
        f'pathlib.Path({str(wire)!r}).write_bytes(sys.stdin.buffer.read())\n'
        f'sys.stdout.write({json.dumps(response)!r})\n'
    )
    with _peer(monkeypatch, script, channel=channel) as (_children, calls):
        result = _invoke(action, operation_id, plan)
        assert result is not None
        assert len(calls) == 1
        assert json.loads(wire.read_bytes()) == {
            'action': action, 'operation_id': operation_id,
            'plan': json.loads(json.dumps(plan.payload())), 'bootstrap': action == 'prepare',
        }


@pytest.mark.parametrize('action', ['prepare', 'reconcile-unknown'])
@pytest.mark.parametrize('raw,returncode,predicate', [
    (b'', 0, None), (b'{', 0, None), (b'[]', 0, None), (b'{}\n{}', 0, None),
    (b'\xff', 0, None), (b'{"ready":true}', 1, None),
    (b'{"refused":true,"missing_predicate":"worker_is_quiescent"}', 78, 'worker_is_quiescent'),
    (b'{"refused":true,"missing_predicate":"worker_is_quiescent"}', 0, 'worker_is_quiescent'),
    (b'{"refused":true,"missing_predicate":"worker_is_quiescent","extra":true}', 78, None),
    (b'{"refused":1,"missing_predicate":"worker_is_quiescent"}', 78, None),
    (b'{"refused":true,"missing_predicate":"fixture-private-payload"}', 78, None),
    (b'{"refused":true}', 0, None),
])
def test_normal_request_rejects_incomplete_or_failed_protocol(monkeypatch, action, raw, returncode, predicate):
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',))
    with _peer(monkeypatch, _reply(raw, returncode=returncode, stderr=_PRIVATE.encode())):
        with pytest.raises(PostgresDeployError) as failure:
            _invoke(action, str(uuid4()), plan)
        rendered = ''.join(traceback.format_exception(failure.value))
        assert _PRIVATE not in rendered
        if action == 'reconcile-unknown':
            assert failure.value.missing_predicate == (predicate or 'native_rpc_returns_fence_evidence')


def test_normal_request_accepts_guest_byte_envelope(monkeypatch):
    # Match the existing guest line limit, including the final newline.
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',),
                      authority_cutover=AuthorityCutover('fixture', '/x', '/owned'))
    operation_id = str(uuid4())
    request = {'action': 'prepare', 'operation_id': operation_id, 'plan': plan.payload(), 'bootstrap': True}
    length = len((json.dumps(request) + '\n').encode())
    plan = replace(plan, authority_cutover=replace(plan.authority_cutover, root='/x' + 'x' * (65536 - length)))
    response = {'ready': True, 'empty': False, 'padding': ''}
    response['padding'] = 'x' * (65536 - len((json.dumps(response) + '\n').encode()))
    raw = (json.dumps(response) + '\n').encode()
    assert len(raw) == 65536
    with _peer(monkeypatch, _reply(raw, stderr=b'x' * 65536)):
        assert _invoke('prepare', operation_id, plan) is False


@pytest.mark.parametrize('tail', ['stderr-overflow', 'stdout-overflow', 'missing-exit'])
def test_normal_request_waits_for_complete_exchange(monkeypatch, tail):
    monkeypatch.setattr(linux, '_NORMAL_SSH_EXCHANGE_SECONDS', 0.15)
    operation_id = str(uuid4())
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',))
    raw = (json.dumps(_fence(operation_id, plan)) + '\n').encode()
    script = ('import os, sys, time\n'
              'sys.stdin.buffer.read()\n'
              f'os.write(1, {raw!r})\n')
    if tail == 'missing-exit':
        script += 'os.close(1); os.close(2); time.sleep(10)'
    else:
        script += f'os.write({2 if tail == "stderr-overflow" else 1}, b" " * 65537)'
    with _peer(monkeypatch, script):
        with pytest.raises(linux.UnknownDeployFenceRefused) as failure:
            _invoke('reconcile-unknown', operation_id, plan)
        assert failure.value.missing_predicate == 'native_rpc_returns_fence_evidence'


@pytest.mark.parametrize('fault', [
    'launch', 'selector-create', 'second-register', 'set-blocking', 'write',
    'read-stdout', 'read-stderr', 'select', 'close-stdout', 'selector-close',
    'kill', 'reap',
])
def test_normal_request_cleanup_faults_preserve_unknown(monkeypatch, fault):
    monkeypatch.setattr(linux, '_NORMAL_SSH_EXCHANGE_SECONDS', 0.15)
    monkeypatch.setattr(linux, '_NORMAL_SSH_CLEANUP_SECONDS', 0.1)
    plan = DeployPlan('test', 'a' * 40, ('db',), ('postgres-db',))
    operation_id = str(uuid4())
    selector_factory = linux.selectors.DefaultSelector
    real_read, real_write = linux.os.read, linux.os.write
    streams = []
    cleanup_waits = []

    def fail(*_args, **_kwargs):
        raise OSError(_PRIVATE)

    class FaultSelector:
        def __init__(self):
            self.inner = selector_factory()
            self.registrations = 0

        def register(self, *args):
            self.registrations += 1
            if fault == 'second-register' and self.registrations == 2:
                fail()
            return self.inner.register(*args)

        def get_map(self):
            return self.inner.get_map()

        def unregister(self, *args):
            return self.inner.unregister(*args)

        def select(self, *args):
            if fault == 'select':
                fail()
            return self.inner.select(*args)

        def close(self):
            self.inner.close()
            if fault == 'selector-close':
                fail()

    def configure(child):
        streams.extend((child.stdin, child.stdout, child.stderr))
        if fault == 'set-blocking':
            monkeypatch.setattr(linux.os, 'set_blocking', fail)
        elif fault == 'write':
            descriptor = child.stdin.fileno()
            monkeypatch.setattr(linux.os, 'write', lambda fd, data: fail() if fd == descriptor else real_write(fd, data))
        elif fault.startswith('read-'):
            selected = child.stdout if fault == 'read-stdout' else child.stderr
            descriptor = selected.fileno()
            monkeypatch.setattr(linux.os, 'read', lambda fd, count: fail() if fd == descriptor else real_read(fd, count))
        elif fault == 'close-stdout':
            class CloseFailure:
                def fileno(self):
                    return child.stdout_descriptor

                def close(self):
                    streams[1].close()
                    fail()

            child.stdout_descriptor = child.stdout.fileno()
            child.stdout = CloseFailure()
        elif fault == 'kill':
            kill = child.kill

            def failed_kill():
                kill()
                fail()

            monkeypatch.setattr(child, 'kill', failed_kill)
        elif fault == 'reap':
            def failed_wait(*, timeout):
                cleanup_waits.append(timeout)
                raise subprocess.TimeoutExpired('fixture', timeout)

            monkeypatch.setattr(child, 'wait', failed_wait)

    # Close/selector cleanup failures must refuse even an otherwise valid fence.
    script = _reply((json.dumps(_fence(operation_id, plan)) + '\n').encode(), stderr=b'x')
    if fault in {'kill', 'reap'}:
        script = 'import time; time.sleep(10)'
    with _peer(monkeypatch, script, configure=configure) as (children, calls):
        monkeypatch.setattr(linux.selectors, 'DefaultSelector', fail if fault == 'selector-create' else FaultSelector)
        if fault == 'launch':
            monkeypatch.setattr(linux.subprocess, 'Popen', fail)
        started = time.monotonic()
        with pytest.raises(linux.UnknownDeployFenceRefused) as failure:
            _invoke('reconcile-unknown', operation_id, plan)
        assert time.monotonic() - started < 1.0
        assert failure.value.missing_predicate == 'native_rpc_returns_fence_evidence'
        assert _PRIVATE not in ''.join(traceback.format_exception(failure.value))
        assert len(calls) == (0 if fault == 'launch' else 1)
        assert all(stream.closed for stream in streams)
        if fault != 'reap':
            assert all(child.poll() is not None for child in children)
        else:
            assert len(cleanup_waits) == 1
            assert 0 <= cleanup_waits[0] <= 0.1


def test_transport_preserves_primary_failure_when_cleanup_also_fails(monkeypatch):
    primary = PostgresDeployError()

    def configure(child):
        kill = child.kill

        def failed_kill():
            kill()
            raise OSError(_PRIVATE)

        monkeypatch.setattr(child, 'kill', failed_kill)

    def fail_selector():
        raise primary

    with _peer(monkeypatch, 'import time; time.sleep(10)', configure=configure):
        monkeypatch.setattr(linux.selectors, 'DefaultSelector', fail_selector)
        with pytest.raises(PostgresDeployError) as failure:
            linux._normal_ssh_exchange(['ssh', '-o', 'BatchMode=yes', '--', 'ygg-test',
                'sudo', '-n', '/usr/local/libexec/yggdrasil-bws-deploy', 'rpc', 'test'], b'{}\n')
        assert failure.value is primary


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('outcome', ['timeout', 'stdout-overflow', 'stderr-overflow', 'partial', 'refusal', 'wrong-fence', 'fenced'])
def test_host_reconcile_transport_failure_keeps_original_pending(monkeypatch, tmp_path, capsys, channel, outcome):
    from app.ops import postgres_deploy_host as host
    from app.ops.host_secret_controller import HostSecretController, HostSecretOperation
    from app.ops.host_secret_contract import DATABASE_CONSUMERS

    monkeypatch.setattr(linux, '_NORMAL_SSH_EXCHANGE_SECONDS', 0.15)
    controller = HostSecretController(tmp_path / 'controller')
    plan = DeployPlan(channel, 'a' * 40, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'))
    with controller.deploy_operation(channel, allow_bootstrap=False) as (operation, _resumed):
        operation_id = operation.operation_id
        operation.prepare_mutation()
    journal_path = controller.directory / 'operations.jsonl'
    journal_before = journal_path.read_bytes()
    finish = HostSecretOperation.finish
    finished = []

    def checked_finish(operation, evidence):
        finished.append(evidence)
        assert outcome == 'fenced'
        return finish(operation, evidence)

    monkeypatch.setattr(HostSecretOperation, 'finish', checked_finish)
    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    wire = tmp_path / 'request.json'
    expected = _fence(operation_id, plan)
    if outcome == 'wrong-fence':
        expected = {**expected, 'operation_id': str(uuid4())}
    response = (json.dumps(expected) + '\n').encode()
    if outcome == 'partial':
        response = response[:-8]
    elif outcome == 'refusal':
        response = b'{"refused":true,"missing_predicate":"worker_is_quiescent"}\n'
    script = (
        'import os, pathlib, sys, time\n'
        f'pathlib.Path({str(wire)!r}).write_bytes(sys.stdin.buffer.read())\n'
    )
    if outcome == 'timeout':
        script += 'time.sleep(10)'
    elif outcome.endswith('-overflow'):
        script += f'os.write({1 if outcome == "stdout-overflow" else 2}, b"x" * 65537)'
    else:
        script += f'os.write(1, {response!r}); sys.exit({78 if outcome == "refusal" else 0})'
    with _peer(monkeypatch, script, channel=channel) as (_children, calls):
        argv = [channel, plan.revision, '--existing-secrets-only', '--reconcile-unknown-pending',
                '--operation-id', operation_id]
        assert host.main(argv) == (0 if outcome == 'fenced' else 78)
        assert len(calls) == 1
        assert json.loads(wire.read_bytes()) == {
            'action': 'reconcile-unknown', 'operation_id': operation_id,
            'plan': json.loads(json.dumps(plan.payload())), 'bootstrap': False,
        }
        output = capsys.readouterr()
        assert _PRIVATE not in output.out + output.err
        if outcome == 'fenced':
            assert len(finished) == 1
            assert json.loads(output.out)['host_operation_reconciled'] is True
        else:
            assert not finished
            assert journal_path.read_bytes() == journal_before
            with controller._locked_journal() as descriptor:
                pending = controller._pending(descriptor)
                assert pending['operation_id'] == operation_id
                assert pending['allow_bootstrap'] is False
                assert pending['target'] == channel
