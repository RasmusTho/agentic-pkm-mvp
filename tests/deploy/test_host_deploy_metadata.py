"""Host call-site proof with the actual finite remote reader and local files."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.ops import postgres_deploy_host as host
from app.ops.host_secret_controller import HostSecretController
from app.ops.postgres_deploy import DeployReceipt


ORGANIZATION = '11111111-1111-4111-8111-111111111111'
NON_PROD = '22222222-2222-4222-8222-222222222222'
PROD = '33333333-3333-4333-8333-333333333333'
OTHER = '44444444-4444-4444-8444-444444444444'
METADATA = {
    'BWS_ORGANIZATION_ID': ORGANIZATION,
    'BWS_NON_PROD_PROJECT_ID': NON_PROD,
    'BWS_PROD_PROJECT_ID': PROD,
}
SECRET_CANARY = 'fake-token-must-stay-private'
RUNTIME_CANARY = 'fake-password-must-stay-private'


@pytest.fixture
def entrypoint(tmp_path, monkeypatch):
    """Replace only transport and effect admission; execute the sent reader."""
    native_run = subprocess.run
    root = tmp_path / 'vm'
    directory = root / 'etc/yggdrasil/bws-deploy'
    directory.mkdir(parents=True, mode=0o700)
    sources = {}
    for channel in ('dev', 'test', 'prod'):
        sources[channel] = directory / (channel + '.json')
        sources[channel].write_text(json.dumps({
            'root': '/installed-checkout', 'data_directory': '/installed-data',
            'uid': 1000, 'gid': 1000, 'organization_id': ORGANIZATION,
            'project_id': PROD if channel == 'prod' else NON_PROD,
            # Success must not open or export this unrelated runtime env.
            'runtime_env_file': '/never-open-' + RUNTIME_CANARY,
        }))
        sources[channel].chmod(0o600)
    for key in METADATA:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('BWS_ACCESS_TOKEN', SECRET_CANARY)
    controller = HostSecretController(tmp_path / 'controller')
    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    state = SimpleNamespace(root=root, directory=directory, sources=sources,
                            calls=[], admissions=[], events=[], failure=None)

    def ssh(argv, **kwargs):
        channel = argv[-1]
        assert channel in sources
        assert argv[0] == '/usr/bin/ssh'
        assert argv[-10:] == ['--', 'ygg-' + channel, 'sudo', '-n',
                              '/usr/bin/python3', '-I', '-S', '-B', '-', channel]
        for option in ('BatchMode=yes', 'StrictHostKeyChecking=yes',
                       'ConnectTimeout=10', 'ConnectionAttempts=1',
                       'ClearAllForwardings=yes', 'PermitLocalCommand=no'):
            assert option in argv
        assert kwargs['capture_output'] is True and kwargs['check'] is False
        assert kwargs['text'] is True and kwargs['timeout'] == 20
        assert 'BWS_ACCESS_TOKEN' not in kwargs['env']
        assert not any(key in kwargs['env'] for key in METADATA)
        assert SECRET_CANARY not in kwargs['input'] and RUNTIME_CANARY not in kwargs['input']
        state.calls.append((argv, kwargs))
        state.events.append('read:' + channel)
        if state.failure == 'unavailable':
            raise FileNotFoundError(SECRET_CANARY)
        if state.failure == 'timeout':
            raise subprocess.TimeoutExpired(argv, 20, output=SECRET_CANARY, stderr=RUNTIME_CANARY)
        if state.failure == 'ssh-error':
            return subprocess.CompletedProcess(argv, 255, SECRET_CANARY, RUNTIME_CANARY)
        # Only UID is simulated because these tests do not require root. Every
        # path/type/mode/link/size/read/JSON check uses the real sent program and
        # real files. Map its canonical filesystem root to this isolated VM.
        bridge = f'''
import json, os, stat, sys
from types import SimpleNamespace
from uuid import UUID
native_open, native_fstat = os.open, os.fstat
def vm_open(path, flags, *args, **kwargs):
    return native_open({str(root)!r} if path == '/' else path, flags, *args, **kwargs)
def vm_fstat(descriptor):
    info = native_fstat(descriptor)
    uid = 1000 if {state.failure == 'owner'!r} and stat.S_ISREG(info.st_mode) else 0
    size = 1 if {state.failure == 'oversize-after-stat'!r} and stat.S_ISREG(info.st_mode) else info.st_size
    return SimpleNamespace(st_mode=info.st_mode, st_uid=uid, st_nlink=info.st_nlink, st_size=size)
os.open, os.fstat = vm_open, vm_fstat
'''
        result = native_run([sys.executable, '-I', '-S', '-B', '-', channel],
                            input=bridge + kwargs['input'], capture_output=True,
                            text=True, timeout=5, check=False)
        if state.failure == 'extra-output':
            result.stdout += SECRET_CANARY
        if state.failure == 'extra-field':
            result.stdout = json.dumps({'organization_id': ORGANIZATION, 'project_id': NON_PROD,
                                        'token': SECRET_CANARY})
        if state.failure == 'duplicate-output':
            result.stdout = '{"organization_id":"' + ORGANIZATION + '","project_id":"' + NON_PROD + '","project_id":"' + OTHER + '"}'
        if state.failure == 'stderr-output':
            result.stderr = SECRET_CANARY
        return result

    def admit(admin, remote, plan, *, qualified, allow_bootstrap):
        assert admin.provider._client is None  # Metadata bootstrap never contacts BWS.
        plan.validate()
        state.admissions.append((admin, remote, plan, allow_bootstrap))
        state.events.append('admitted')
        return DeployReceipt('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', plan.channel,
                             'deploy', 'committed', 'committed')

    monkeypatch.setattr(subprocess, 'run', ssh)
    monkeypatch.setattr(host, 'deploy_from_host', admit)
    return state


def invoke(channel='test'):
    return host.main([channel, 'a' * 40, '--existing-secrets-only', '--ack-forward-only'])


def assert_refusal(entrypoint, capsys):
    output = capsys.readouterr()
    assert output.out == ''
    assert output.err == 'database deployment refused; inspect value-free operation status\n'
    assert not entrypoint.admissions
    assert not (entrypoint.root.parent / 'controller').exists()
    for value in (*METADATA.values(), SECRET_CANARY, RUNTIME_CANARY, '/installed-checkout'):
        assert value not in output.out + output.err


@pytest.mark.parametrize('channel', ('dev', 'test', 'prod'))
def test_host_entrypoint_recovers_installed_metadata(entrypoint, capsys, channel):
    environment_before = dict(os.environ)
    assert invoke(channel) == 0
    assert entrypoint.events == ['read:dev', 'read:test', 'read:prod', 'admitted']
    admin, remote, plan, allow_bootstrap = entrypoint.admissions[0]
    config = admin.provider.config
    assert (config.organization_id, config.non_prod_project_id, config.prod_project_id) == (
        ORGANIZATION, NON_PROD, PROD)
    assert remote.host == 'ygg-' + channel and plan.channel == channel
    assert plan.ack_forward_only is True and allow_bootstrap is False
    assert os.environ == environment_before
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out)['terminal_result'] == 'committed'
    assert not any(value in output.out for value in (*METADATA.values(), SECRET_CANARY, RUNTIME_CANARY))


@pytest.mark.parametrize('scenario', ('complete', 'partial-match', 'partial-conflict',
                                     'invalid-complete', 'invalid-partial'))
def test_explicit_metadata_preserves_route_and_rejects_partial_conflict(
    entrypoint, monkeypatch, capsys, scenario,
):
    if 'complete' in scenario:
        for key, value in METADATA.items():
            monkeypatch.setenv(key, value)
    else:
        monkeypatch.setenv('BWS_ORGANIZATION_ID', ORGANIZATION)
    if scenario == 'partial-conflict':
        monkeypatch.setenv('BWS_NON_PROD_PROJECT_ID', OTHER)
    if scenario.startswith('invalid'):
        monkeypatch.setenv('BWS_ORGANIZATION_ID', SECRET_CANARY)
    before = dict(os.environ)
    expected = 0 if scenario in {'complete', 'partial-match'} else 78
    assert invoke() == expected
    assert os.environ == before
    if scenario in {'complete', 'invalid-complete', 'invalid-partial'}:
        assert entrypoint.calls == []
    else:
        assert len(entrypoint.calls) == 3
    if expected:
        assert_refusal(entrypoint, capsys)
    else:
        assert len(entrypoint.admissions) == 1


@pytest.mark.parametrize('failure', (
    'owner', 'permissions', 'symlink', 'directory', 'fifo', 'hardlink',
    'parent-symlink', 'parent-writable', 'missing-file', 'oversize', 'oversize-after-stat',
    'malformed', 'duplicate-json',
    'missing-field', 'secret-field', 'non-object', 'invalid-uuid', 'different-organization',
    'different-test-project', 'same-prod-project', 'organization-is-project',
    'unavailable', 'timeout', 'ssh-error', 'extra-output', 'extra-field',
    'duplicate-output', 'stderr-output',
))
def test_metadata_bootstrap_refuses_untrusted_or_inconsistent_sources_value_free(
    entrypoint, capsys, failure,
):
    entrypoint.failure = failure
    path = entrypoint.sources['dev']
    if failure == 'permissions':
        path.chmod(0o640)
    elif failure in {'symlink', 'directory', 'fifo'}:
        target = path.with_suffix('.original')
        path.rename(target)
        if failure == 'symlink':
            path.symlink_to(target)
        elif failure == 'directory':
            path.mkdir(mode=0o600)
        else:
            os.mkfifo(path, mode=0o600)
    elif failure == 'hardlink':
        os.link(path, path.with_suffix('.link'))
    elif failure == 'parent-symlink':
        target = entrypoint.directory.with_name('original')
        entrypoint.directory.rename(target)
        entrypoint.directory.symlink_to(target, target_is_directory=True)
    elif failure == 'parent-writable':
        entrypoint.directory.chmod(0o722)
    elif failure == 'missing-file':
        path.unlink()
    elif failure in {'oversize', 'oversize-after-stat', 'malformed', 'duplicate-json', 'non-object'}:
        path.write_text({
            'oversize': SECRET_CANARY * 4096, 'oversize-after-stat': SECRET_CANARY * 4096,
            'malformed': SECRET_CANARY,
            'duplicate-json': '{"organization_id":"' + ORGANIZATION + '","organization_id":"' + OTHER + '"}',
            'non-object': '["' + SECRET_CANARY + '"]',
        }[failure])
    elif failure in {'missing-field', 'secret-field', 'invalid-uuid', 'different-organization',
                     'different-test-project', 'same-prod-project', 'organization-is-project'}:
        channel = {'different-organization': 'test', 'different-test-project': 'test',
                   'same-prod-project': 'prod'}.get(failure, 'dev')
        path = entrypoint.sources[channel]
        data = json.loads(path.read_text())
        if failure == 'missing-field':
            del data['project_id']
        elif failure == 'secret-field':
            data['token'] = SECRET_CANARY
        elif failure == 'invalid-uuid':
            data['organization_id'] = SECRET_CANARY
        elif failure == 'different-organization':
            data['organization_id'] = OTHER
        else:
            data['project_id'] = {
                'different-test-project': OTHER, 'same-prod-project': NON_PROD,
                'organization-is-project': ORGANIZATION,
            }[failure]
        path.write_text(json.dumps(data))
    before = dict(os.environ)
    assert invoke() == 78
    assert entrypoint.calls  # Refusal must exercise the production metadata route.
    assert os.environ == before
    assert_refusal(entrypoint, capsys)
