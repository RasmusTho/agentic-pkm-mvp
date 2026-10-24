"""Exact-request MVR-03 transport; no live hosts, credentials, Docker or DB.

The host controller, SSH request serializer, supervisor, durable journal, worker,
consumer selection, activation and inherited guard are production code. Only
external transport, configuration/credential-file and database ports are fixtures.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.ops import postgres_deploy_host as host
from app.ops import postgres_deploy_linux as linux
from app.ops.bws_secret_admin import SecretCopy
from app.ops.bws_secret_reader import BwsItemAbsent
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.host_secret_controller import HostSecretController
from app.ops.postgres_deploy import (
    AuthorityCutover, DeployJournal, DeployPlan, DeployWorker, PostgresDeployError,
    TestRecoveryRequest as RecoveryRequest,
    deploy_from_host,
)


SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
PASSWORD = 'synthetic-principal-cutover-password'
REPO = Path(__file__).resolve().parents[2]


def _request(plan, identifier, action='prepare', *, bootstrap=False):
    return json.loads(json.dumps({'action': action, 'operation_id': identifier,
                                 'plan': plan.payload(), 'bootstrap': bootstrap}))


@pytest.fixture(params=['dev', 'test'])
def native(tmp_path, monkeypatch, request):
    channel = request.param
    root = tmp_path / 'checkout'
    (root / 'config/deploy').mkdir(parents=True)
    runtime = root / 'runtime.env'
    runtime.write_text('DATABASE_URL=postgresql://app@fixture-db:5432/app_' + channel + '\n')
    (root / 'config/deploy' / (channel + '.env')).write_text('APP_IMAGE_TAG=' + SHA + '\n')
    sources = tmp_path / 'sources'
    sources.mkdir(mode=0o700)
    owner = tmp_path / 'ownership'
    owner.mkdir(mode=0o700)

    class Reader:
        def lookup(self, project, identity):
            if identity == channel + '/postgres.password':
                assert project == 'non-prod'
                return PASSWORD
            raise BwsItemAbsent()

    class Provider:
        def read(self, project, identity):
            try:
                return SecretCopy(str(uuid4()), Reader().lookup(project, identity), '')
            except BwsItemAbsent:
                return None

    class PasswordFile:
        """The Linux root/tmpfs credential-file port, without root or live secrets."""
        def __init__(self, config):
            self.config = config

        def materialize(self, value):
            assert value == PASSWORD
            self.config.password_file.write_text(value)

        def verify(self):
            assert self.config.password_file.read_text() == PASSWORD

    cfg = SimpleNamespace(channel=channel, root=root, runtime_env_file=runtime,
                          uid=os.getuid(), gid=os.getgid(), source_directory=sources,
                          password_file=sources / 'password', reader=Reader,
                          journal=DeployJournal(tmp_path / 'journal', channel))
    controller = HostSecretController(tmp_path / 'host-controller')
    monkeypatch.setattr(host, 'HostSecretController', lambda: controller)
    monkeypatch.setattr(host, '_configured_host_admin', Provider)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _: cfg)
    monkeypatch.setattr(linux, 'PasswordSource', PasswordFile)
    monkeypatch.setattr(linux, 'password_authenticate', lambda env: (
        Path(env['DATABASE_PASSWORD_FILE']).read_text() == PASSWORD
        or pytest.fail('wrong database credential')))
    monkeypatch.setattr(os, 'environ', {'PATH': os.environ['PATH'],
                                      'INSTANCE_OWNERSHIP_HOST_STATE_DIR': str(owner)})
    supervisor = linux.DeploymentSupervisor(cfg)
    state = SimpleNamespace(cfg=cfg, controller=controller, supervisor=supervisor,
                            requests=[], activations=[], commands=[], wrapper=None,
                            real_run=subprocess.run, monkeypatch=monkeypatch, sha=SHA)

    def transport(argv, **kwargs):
        state.commands.append(argv)
        output = ''
        if argv[0] == 'ssh':
            data = json.loads(kwargs['input'])
            state.requests.append(data)
            assert argv[-1] == channel and argv[4] == 'ygg-' + channel
            try:
                output = json.dumps(supervisor.request(data))
            except PostgresDeployError:
                return subprocess.CompletedProcess(argv, 78, '', '')
        elif argv[0] == 'git':
            if 'show' in argv:
                assert argv[-1] == state.sha + ':app/config/database.py'
                output = (REPO / 'app/config/database.py').read_text()
            else:
                assert any(command in argv for command in ('ls-tree', 'rev-parse', 'diff', 'cat-file'))
        elif argv[0] == 'docker':
            assert 'ps' in argv
            output = '[]' if '--format' in argv and 'json' in argv else ''
        elif argv[:2] == ['bash', str(root / 'scripts/deploy_channel.sh')]:
            plan = cfg.journal.bound_plan(cfg.journal.read().operation_id)
            assert argv[2:] == ['deploy', channel, state.sha, '--image-digest', DIGEST,
                                *(['--automatic'] if plan.automatic else [])]
            assert cfg.journal.read().stage == 'activating'
            assert kwargs['pass_fds'] == (supervisor.operation.effects.lock_fd,)
            environment = kwargs['env']
            # This is the first production shell guard, not a mocked admission.
            with patch.dict(os.environ, environment, clear=True):
                linux.inherited_worker_guard(channel)
                linux.inherited_worker_guard(channel, 'run')
            state.activations.append(environment.copy())
            if state.wrapper is not None:
                return state.wrapper(argv, **kwargs)
        else:
            pytest.fail('unexpected external port: ' + repr(argv))
        if not kwargs.get('text'):
            output = output.encode()
        return subprocess.CompletedProcess(argv, 0, output, '' if kwargs.get('text') else b'')

    monkeypatch.setattr(linux.subprocess, 'run', transport)
    yield state
    if supervisor.operation is not None:
        supervisor.operation.activation.set()
        supervisor.operation.thread.join(timeout=3)
        assert not supervisor.operation.thread.is_alive()


def _cli(native, *, cutover=True, identifier=None, automatic=False):
    return [native.cfg.channel, native.sha, '--image-digest', DIGEST, '--existing-secrets-only',
            *(['--principal-cutover'] if cutover else []),
            *(['--automatic'] if automatic else []),
            *(['--operation-id', identifier] if identifier else [])]


def _plan(native, *, cutover=True, automatic=False):
    return DeployPlan(native.cfg.channel, native.sha, tuple(DATABASE_CONSUMERS.values()),
                      (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), image_digest=DIGEST,
                      principal_cutover=cutover, automatic=automatic)


@pytest.mark.parametrize('automatic', [False, True])
def test_native_principal_cutover_is_explicit_and_request_bound(native, tmp_path, monkeypatch, automatic):
    boundaries = {}
    if automatic:
        from app.ops.pg_acceptance_runner import PgAcceptanceRunner
        from tests.deploy.test_postmerge_pg_acceptance import DockerBoundary, _repository
        # Real immutable object export/runner, only Git/Docker transport is isolated.
        with patch.object(subprocess, 'run', native.real_run):
            objects, native.sha = _repository(tmp_path)
        (native.cfg.root / 'config/deploy' / (native.cfg.channel + '.env')).write_text(
            'APP_IMAGE_TAG=' + native.sha + '\n')

        def git_port(_runner, *arguments):
            return native.real_run(['git', '-C', str(objects), *arguments],
                                   capture_output=True, check=True).stdout

        def docker_port(runner, *arguments, **kwargs):
            boundary = boundaries.setdefault(runner.name, DockerBoundary(runner))
            return boundary.command(*arguments, **kwargs)

        monkeypatch.setattr(PgAcceptanceRunner, '_git', git_port)
        monkeypatch.setattr(PgAcceptanceRunner, '_docker', docker_port)
    identifier = str(uuid4())
    assert host.main(_cli(native, identifier=identifier, automatic=automatic)) == 0, (native.requests, native.commands)
    assert [data['action'] for data in native.requests] == ['prepare', 'activate']
    assert all(data['operation_id'] == identifier and data['bootstrap'] is False
               and data['plan']['principal_cutover'] is True for data in native.requests)
    path = native.cfg.journal.directory / (native.cfg.channel + '.request.json')
    retained = json.loads(path.read_text())
    assert retained == {key: value for key, value in native.requests[0].items() if key != 'action'}
    assert path.stat().st_mode & 0o777 == 0o600
    assert native.cfg.journal.bound_plan(identifier) == _plan(native, automatic=automatic)
    assert native.activations[0]['MVR03_PRINCIPAL_CUTOVER'] == '1'
    assert native.cfg.journal.read().stage == 'committed'
    assert 'MVR03_PRINCIPAL_CUTOVER' not in native.supervisor.operation.effects.environment()
    if automatic:
        assert native.cfg.journal.read().pg_acceptance['operation_id'] == identifier
        assert len(boundaries) == 1 and not next(iter(boundaries.values())).containers
        assert all(data['plan']['verification_profile'] == _plan(native, automatic=True).payload()['verification_profile']
                   for data in native.requests)


def test_ambient_principal_cutover_cannot_authorize_native_activation(native, monkeypatch):
    monkeypatch.setenv('MVR03_PRINCIPAL_CUTOVER', '1')
    native.cfg.runtime_env_file.write_text(native.cfg.runtime_env_file.read_text() + 'MVR03_PRINCIPAL_CUTOVER=1\n')
    refused = []

    def wrapper(argv, **kwargs):
        environment = kwargs['env']
        for changed in ({**environment, 'MVR03_PRINCIPAL_CUTOVER': '1'},
                        {**environment, 'BWS_DEPLOY_OPERATION_ID': str(uuid4())},
                        {**environment, 'BWS_DEPLOY_LOCK_FD': '-1'}):
            with patch.dict(os.environ, changed, clear=True), pytest.raises((PostgresDeployError, ValueError, OSError)):
                linux.inherited_worker_guard(native.cfg.channel)
            refused.append(changed)
        return subprocess.CompletedProcess(argv, 0, '', '')

    native.wrapper = wrapper
    assert host.main(_cli(native, cutover=False)) == 0
    assert len(refused) == 3
    assert all('principal_cutover' not in data['plan'] for data in native.requests)
    assert len(native.activations) == 1 and 'MVR03_PRINCIPAL_CUTOVER' not in native.activations[0]
    assert 'MVR03_PRINCIPAL_CUTOVER' not in native.supervisor.operation.effects.environment()


def test_unattended_postmerge_producer_remains_default_off(monkeypatch):
    from scripts import postmerge_dev_test as driver
    candidate = driver.Candidate(SHA, DIGEST, 1, 1, 1)
    commands = []

    def transport(argv, **kwargs):
        commands.append(argv)
        channel = argv[argv.index(SHA) - 1]
        return subprocess.CompletedProcess(argv, 78, json.dumps({
            'operation_id': candidate.operation_id(channel), 'channel': channel,
            'kind': 'deploy', 'stage': 'aborted', 'terminal_result': 'aborted'}), '')

    monkeypatch.setattr(driver.subprocess, 'run', transport)
    for channel in ('dev', 'test'):
        assert driver.native_deploy(channel, candidate)['stage'] == 'aborted'
    assert len(commands) == 2
    assert all('--automatic' in argv and '--principal-cutover' not in argv for argv in commands)


def test_inherited_guard_requires_the_exact_principal_request(native):
    def wrapper(argv, **kwargs):
        environment = kwargs['env']
        for value in (None, '0', 'true', '2'):
            changed = dict(environment)
            if value is None:
                del changed['MVR03_PRINCIPAL_CUTOVER']
            else:
                changed['MVR03_PRINCIPAL_CUTOVER'] = value
            with patch.dict(os.environ, changed, clear=True), pytest.raises(PostgresDeployError):
                linux.inherited_worker_guard(native.cfg.channel)
        with patch.dict(os.environ, {**environment, 'BWS_DEPLOY_TARGET_REVISION': 'c' * 40}, clear=True):
            with pytest.raises(PostgresDeployError):
                linux.inherited_worker_guard(native.cfg.channel)
        return subprocess.CompletedProcess(argv, 0, '', '')

    native.wrapper = wrapper
    assert host.main(_cli(native)) == 0


def test_interrupted_principal_request_cannot_reconcile_or_replay(native):
    identifier = str(uuid4())
    native.wrapper = lambda argv, **kwargs: subprocess.CompletedProcess(argv, 75, '', '')
    assert host.main(_cli(native, identifier=identifier)) == 78
    assert native.cfg.journal.read().stage == 'activating'
    lock = native.cfg.root / 'config/deploy' / (native.cfg.channel + '.env.lock')
    assert lock.is_dir()
    lost = linux.DeploymentSupervisor(native.cfg)
    for action in ('prepare', 'activate', 'join', 'reconcile-failed'):
        assert lost.request(_request(_plan(native), identifier, action)) == {
            'pending': True, 'empty': False, 'ready': False}
        with pytest.raises(PostgresDeployError):
            lost.request(_request(_plan(native, cutover=False), identifier, action))
    assert host.main([*_cli(native, identifier=identifier), '--reconcile-pending']) == 78
    assert host.main(_cli(native, identifier=identifier)) == 78
    assert len(native.activations) == 1 and lock.is_dir()
    assert native.cfg.journal.read().stage == 'activating'


def test_legacy_requests_and_same_id_cutover_binding(native):
    ordinary = _plan(native, cutover=False)
    legacy = {'channel': native.cfg.channel, 'revision': SHA, 'services': ordinary.services,
              'consumers': ordinary.consumers, 'ack_forward_only': False}
    assert replace(ordinary, image_digest=None).payload() == legacy
    assert json.dumps(ordinary.payload(), sort_keys=True) == json.dumps(
        {**legacy, 'image_digest': DIGEST, 'automatic': False}, sort_keys=True)
    assert DeployPlan.from_payload({**ordinary.payload(), 'principal_cutover': False}) == ordinary
    automatic = replace(ordinary, automatic=True)
    wire = json.loads(json.dumps(automatic.payload()))
    assert DeployPlan.from_payload({**wire, 'principal_cutover': False}).payload() == automatic.payload()
    assert set(_plan(native).payload()) - set(ordinary.payload()) == {'principal_cutover'}
    identifier = str(uuid4())
    request = _request(_plan(native), identifier)
    assert native.supervisor.request(request)['ready']
    retained = native.cfg.journal.bound_plan(identifier)
    selected = native.supervisor.operation.effects.select_active_plan(retained)
    assert selected.principal_cutover is True and DeployPlan.from_payload(selected.payload()) == selected
    for action in ('prepare', 'activate', 'join', 'reconcile-failed'):
        with pytest.raises(PostgresDeployError):
            native.supervisor.request(_request(ordinary, identifier, action))
    result = native.supervisor.request({**request, 'action': 'activate'})
    assert result['receipt']['stage'] == 'committed'
    assert native.supervisor.request(request) == result
    assert native.supervisor.request({**request, 'action': 'activate'}) == result
    assert len(native.activations) == 1
    # A new supervisor sees only retained terminal truth; it cannot replay.
    assert linux.DeploymentSupervisor(native.cfg).request(request) == result
    assert len(native.activations) == 1
    with pytest.raises(PostgresDeployError):
        DeployWorker(native.cfg.journal, native.supervisor.operation.effects).run(
            identifier, replace(retained, revision='c' * 40))


def test_principal_cutover_rejects_unsupported_request_modes(native, monkeypatch):
    plan = _plan(native)
    for changed in (replace(plan, channel='prod'),
                    replace(plan, image_digest=None), replace(plan, revision='main'),
                    replace(plan, promotion_plan='/synthetic/plan'),
                    replace(plan, authority_cutover=AuthorityCutover('binding', '/vault', '/owner'))):
        with pytest.raises(PostgresDeployError):
            native.supervisor.request(_request(changed, str(uuid4())))
    for malformed in (None, 0, 1, 'true', 'false', [], {}, {'enabled': True}):
        data = _request(plan, str(uuid4()))
        data['plan']['principal_cutover'] = malformed
        with pytest.raises(PostgresDeployError):
            native.supervisor.request(data)
    with pytest.raises(PostgresDeployError):
        native.supervisor.request(_request(plan, str(uuid4()), bootstrap=True))
    with pytest.raises(PostgresDeployError):
        deploy_from_host(None, None, plan, qualified=lambda: pytest.fail('must not qualify'))
    selected = AuthorityCutover('binding', '/synthetic/vault', '/synthetic/ownership')
    recovery = RecoveryRequest(str(uuid4()), replace(plan, channel='test', automatic=True), selected)
    with pytest.raises(PostgresDeployError):
        RecoveryRequest.from_payload(recovery.payload())
    ordinary = replace(recovery.plan, principal_cutover=False)
    compatible = RecoveryRequest(str(uuid4()), ordinary, selected, str(uuid4()), ordinary)
    compatible.validate()
    for validate in (compatible.validate_failed_plan, compatible.validate_source_plan):
        with pytest.raises(PostgresDeployError):
            validate(recovery.plan)
    monkeypatch.setattr(host, 'HostSecretController', lambda: pytest.fail('must refuse before admission'))
    for extra in (['--promotion-plan', '/plan'], ['--persist-source-identity'],
                  ['--diagnose-source-identity'], ['--current-state-source'], ['--prove-never-admitted'],
                  ['--preflight-source-persistence-admission'], ['--restore-operator-source-identity'],
                  ['--resume-unattempted-operator-restoration'], ['--reconcile-operator-unknown-cleanup'],
                  ['--prove-source-persistence-never-admitted'], ['--recover-test-source'],
                  ['--reconstruct-missing-instance-state'], ['--failed-operation-id', str(uuid4())],
                  ['--authority-cutover-binding', 'binding'], ['--source-producer-kind', 'registry']):
        assert host.main([*_cli(native), *extra]) == 78
    args = _cli(native)
    assert host.main(['prod', *args[1:]]) == 78
    assert host.main([value for value in args if value != '--existing-secrets-only']) == 78
    assert host.main([*args[:2], '--principal-cutover', '--existing-secrets-only']) == 78
    assert native.requests == [] and native.activations == []


@pytest.mark.parametrize('fault', ['incomplete', 'racing', 'clean', 'tampered-clean', 'post-role'])
def test_native_cutover_reuses_existing_stopped_window_and_failure_fence(native, tmp_path, monkeypatch, fault):
    from app.instance.principal_fence import principal_floor_recorded
    from tests.deploy._principal_cutover_harness import NativeShellBoundary

    boundary = NativeShellBoundary(native, tmp_path, monkeypatch, fault)
    native.wrapper = boundary.run
    identifier = str(uuid4())
    try:
        assert host.main(_cli(native, identifier=identifier)) == 78
        assert not boundary.errors, boundary.errors
        assert 'deployment-begin' in boundary.events, (boundary.events, boundary.output)
        assert 'writer-snapshot' in boundary.events, (boundary.events, boundary.output)
        assert boundary.events.index('stop') < boundary.events.index('writer-snapshot')
        if fault in {'incomplete', 'racing'}:
            assert 'principal-cutover' not in boundary.events
            assert not principal_floor_recorded(boundary.runtime.registry)
        else:
            assert boundary.events.index('deployment-prove') < boundary.events.index('principal-cutover')
            assert boundary.events.index('validate-legacy-owners') < boundary.events.index('principal-cutover')
            assert 'role-write' in boundary.events, '\n'.join(str(row) for row in boundary.messages if row[2])
            verified = dict(boundary.results)['principal-verify-cutover-clean-failure']
            assert (verified == 0) is (fault == 'clean')
            assert ('deployment-release' in boundary.events) is (fault == 'clean')
            assert principal_floor_recorded(boundary.runtime.registry) is (fault == 'post-role')
            assert (boundary.store.load() is not None) is (fault == 'post-role')
            fence = boundary.runtime.ledger.root / ('deployment-' + native.cfg.channel + '-restart-fence.json')
            assert fence.exists() is (fault != 'clean')
            if fault != 'clean':
                from app.instance.runtime import _preflight_runtime
                from app.instance.vault_registry import RegistryError
                with pytest.raises(RegistryError, match='deployment lease|restart.*fenced'):
                    _preflight_runtime(channel=native.cfg.channel,
                        instance_state_root=boundary.runtime.layout.root.parent,
                        host_global_root=boundary.runtime.ledger.root, consumer='api')
        assert native.cfg.journal.read().stage == 'activating'
        assert (native.cfg.root / 'config/deploy' / (native.cfg.channel + '.env.lock')).is_dir()
        assert host.main([*_cli(native, identifier=identifier), '--reconcile-pending']) == 78
        assert len(native.activations) == 1
    finally:
        boundary.close()
