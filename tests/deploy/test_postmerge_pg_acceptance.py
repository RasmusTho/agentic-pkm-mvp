from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml

from app.ops import pg_acceptance as profile
from app.ops import pg_acceptance_runner as runner_module
from app.ops import postgres_deploy_linux as linux
from app.ops.postgres_deploy import DeployJournal, DeployPlan, DeployReceipt, DeployWorker, PostgresDeployError
from scripts import postmerge_dev_test as driver

ROOT = Path(__file__).resolve().parents[2]
DIGEST = 'sha256:' + 'b' * 64
IMAGE_ID = 'sha256:' + 'c' * 64


def _result(sha, channel, operation_id):
    return {**profile.identity(sha, DIGEST, channel, operation_id), 'result': 'passed',
            'selected': len(profile.SELECTORS) + 100, 'passed': len(profile.SELECTORS) + 100,
            'resource_tree': 'd' * 40, 'app_image_id': IMAGE_ID, 'report_hash': 'e' * 64}


def _repository(tmp_path):
    root = tmp_path / 'repository'
    root.mkdir()
    for name in runner_module.RESOURCE_PATHS:
        path = root / name
        if name in {'tests', 'docs', 'golden', '.github', '.codex'}:
            path.mkdir()
            (path / 'fixture.txt').write_text('exact resource')
        else:
            path.write_text('exact resource')
    for selector in profile.SELECTORS:
        path = root / selector.split('::')[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# exact selected test\n')
    (root / 'tests/conftest.py').write_text('# exact fixture\n')
    for name in runner_module.BAKED_PACKAGES:
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        (path / '__init__.py').write_text("IDENTITY = 'candidate-image'\n")
    def git(*arguments):
        return subprocess.run(['git', '-C', str(root), *arguments], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('init')
    git('add', '.')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture')
    sha = git('rev-parse', 'HEAD')
    # Ambient/dirty tooling must never supply candidate test resources or code.
    (root / 'app/__init__.py').write_text("IDENTITY = 'wrong-tooling-code'\n")
    (root / 'tests/conftest.py').write_text('# wrong tooling fixture\n')
    return root, sha


class DockerBoundary:
    """Deterministic daemon transport; production resource/runner logic is real."""
    def __init__(self, runner):
        self.runner = runner
        self.commands = []
        self.containers = {}
        self.fault = None
        self.tcp_ready = False
        self.tcp_probes = 0

    def command(self, *arguments, timeout=60):
        self.commands.append((arguments, timeout))
        if arguments[:2] == ('image', 'inspect'):
            image = {'Id': IMAGE_ID, 'RepoDigests': [profile.IMAGE_REPOSITORY + '@' + DIGEST],
                     'Config': {'Labels': {'org.opencontainers.image.revision': self.runner.identity['source_sha']}}}
            if self.fault == 'sha':
                image['Config']['Labels']['org.opencontainers.image.revision'] = '0' * 40
            if self.fault == 'digest':
                image['RepoDigests'] = []
            return json.dumps([image]).encode()
        if arguments[0] == 'pull' and self.fault == 'dependency':
            raise profile.PgAcceptanceError()
        if arguments[0] == 'exec' and arguments[2] == 'psql' and self.fault == 'provision':
            raise profile.PgAcceptanceError()
        if arguments[0] == 'exec' and arguments[2] == 'pg_isready' and self.fault in {'startup_race', 'readiness_exhausted'}:
            if '-h' not in arguments:
                return b'temporary socket server accepting connections'
            self.tcp_probes += 1
            if self.fault == 'readiness_exhausted' or self.tcp_probes < 3:
                raise profile.PgAcceptanceError()
            self.tcp_ready = True
            return b'final TCP server accepting connections'
        if arguments[:2] == ('container', 'ls'):
            name = arguments[arguments.index('--filter') + 1][len('name=^/'):-1]
            return (self.containers.get(name, {}).get('Id', '') + '\n').encode()
        if arguments[0] == 'inspect':
            return json.dumps([next(row for row in self.containers.values() if row['Id'] == arguments[-1])]).encode()
        if arguments[0] == 'create':
            name = arguments[arguments.index('--name') + 1]
            labels = {arguments[i + 1].split('=', 1)[0]: arguments[i + 1].split('=', 1)[1]
                      for i, value in enumerate(arguments) if value == '--label'}
            mounts = []
            for i, value in enumerate(arguments):
                if value == '--mount':
                    fields = dict(part.split('=', 1) for part in arguments[i + 1].split(',') if '=' in part)
                    mounts.append({'Type': fields['type'], 'Source': fields['src'],
                                   'Destination': fields['dst'], 'RW': False})
            identifier = hashlib.sha256(name.encode()).hexdigest()
            self.containers[name] = {
                'Id': identifier, 'Name': '/' + name, 'Image': IMAGE_ID,
                'Config': {'Labels': labels}, 'Mounts': mounts,
                'HostConfig': {'NetworkMode': arguments[arguments.index('--network') + 1],
                               'ReadonlyRootfs': '--read-only' in arguments, 'CapDrop': ['ALL']},
            }
            return identifier.encode()
        if arguments[0] == 'rm':
            name = next(name for name, row in self.containers.items() if row['Id'] == arguments[-1])
            del self.containers[name]
            return b''
        if arguments[:2] == ('start', '--attach'):
            if self.fault == 'startup_race' and not self.tcp_ready:
                raise profile.PgAcceptanceError()
            if self.fault == 'timeout':
                raise profile.PgAcceptanceError()
            if self.fault == 'interrupted':
                raise KeyboardInterrupt()
            manifest = json.loads((self.runner.directory / 'source/pg-acceptance-manifest.json').read_text())
            result = {**_result(self.runner.identity['source_sha'], self.runner.identity['channel'],
                               self.runner.identity['operation_id']), 'resource_tree': manifest['resource_tree']}
            if self.fault == 'resource':
                result['resource_tree'] = '0' * 40
            if self.fault == 'image':
                result['app_image_id'] = 'sha256:' + '0' * 64
            if self.fault == 'profile':
                result['profile_version'] = 'smoke.v0'
            return ('YGGDRASIL_PG_ACCEPTANCE=' + json.dumps(result)).encode()
        return b''


def _runner(tmp_path, monkeypatch, *, channel='dev', operation_id=None):
    root, sha = _repository(tmp_path)
    operation_id = operation_id or str(uuid4())
    runner = runner_module.PgAcceptanceRunner(root, tmp_path / 'journal', sha=sha,
                                            digest=DIGEST, channel=channel, operation_id=operation_id)
    boundary = DockerBoundary(runner)
    monkeypatch.setattr(runner, '_docker', boundary.command)
    return runner, boundary, sha, operation_id


@pytest.mark.parametrize('fault', [None, 'timeout', 'dependency', 'provision', 'profile', 'resource', 'image'])
def test_native_automatic_operation_requires_profile_before_commit(tmp_path, monkeypatch, fault):
    runner, boundary, sha, operation_id = _runner(tmp_path, monkeypatch)
    boundary.fault = fault
    journal = DeployJournal(tmp_path / 'native-journal', 'dev')
    config = SimpleNamespace(root=runner.repository, channel='dev', journal=journal)
    effects = linux.LinuxEffects(config)
    effects.lock_fd = 123
    effects.operation_id = operation_id
    plan = DeployPlan('dev', sha, ('db', 'api'), ('postgres-db', 'postgres-api'), image_digest=DIGEST, automatic=True)
    journal.bind_request(operation_id, plan, False, create=True)
    monkeypatch.setattr(effects, 'preflight', lambda _plan: 'fixture-password')
    monkeypatch.setattr(effects, 'initialized', lambda: False)
    monkeypatch.setattr(effects, 'materialize', lambda _password: None)
    monkeypatch.setattr(effects, 'quiescent', lambda: True)
    activated = []
    monkeypatch.setattr(effects, 'activate', lambda _plan: activated.append(journal.read().stage))
    monkeypatch.setattr(effects, '_pg_runner', lambda identifier, _plan: runner if identifier == operation_id else None)
    actual_verify = effects.verify
    def verify(identifier, received):
        assert journal.read().stage == 'verifying' and activated == ['activating']
        return actual_verify(identifier, received)
    monkeypatch.setattr(effects, 'verify', verify)
    receipt = DeployWorker(journal, effects).run(operation_id, plan)
    assert receipt.terminal_result == ('committed' if fault is None else 'failed')
    assert not boundary.containers and not runner.directory.exists()
    if fault is None:
        receipt.require_profile(plan)
        assert journal.read().pg_acceptance == receipt.pg_acceptance
    else:
        assert receipt.pg_acceptance is None
        candidate = driver.Candidate(sha, DIGEST, 1, 1, 1)
        calls = []
        def failed(channel, _candidate):
            calls.append(channel)
            return {'channel': channel, 'operation_id': candidate.operation_id(channel), 'terminal_result': 'failed'}
        assert driver.deliver(candidate, deploy=failed, current_main=lambda: sha, emit=lambda _row: None) == 78
        assert calls == ['dev']


def test_shared_pg_surface_preserves_selection_and_required_results():
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci-smoke.yaml').read_text())
    job = workflow['jobs']['pr-index-pg-contracts']
    step = next(row for row in job['steps'] if 'Run exact index' in row.get('name', ''))
    assert 'python -m app.ops.pg_acceptance --ci' in step['run']
    assert job['services']['postgres']['image'] == profile.POSTGRES_IMAGE
    assert any('CREATE EXTENSION IF NOT EXISTS vector' in row.get('run', '') for row in job['steps'])
    assert len(profile.SELECTORS) == 65
    assert all((ROOT / selector.split('::')[0]).is_file() for selector in profile.SELECTORS)
    args = profile.pytest_arguments()
    assert args[args.index('-m') + 1] == 'pg'
    assert '--timeout=120' in args and '--timeout-method=thread' in args and 'timeout' in args
    nodes = [selector if '::' in selector else selector + '::test_fixture' for selector in profile.SELECTORS]
    plugin = profile.RequiredResults()
    session = SimpleNamespace(items=[SimpleNamespace(nodeid=node) for node in nodes],
                              config=SimpleNamespace(getoption=lambda option: {'timeout': 120, 'timeout_method': 'thread'}[option]))
    plugin.pytest_collection_finish(session)
    for node in nodes:
        plugin.pytest_runtest_logreport(SimpleNamespace(nodeid=node, when='call', skipped=False, failed=False, passed=True))
    assert plugin.summary(0)['selected'] == len(nodes)
    plugin.pytest_runtest_logreport(SimpleNamespace(nodeid=nodes[0], when='setup', skipped=True, failed=False, passed=False))
    with pytest.raises(profile.PgAcceptanceError):
        plugin.summary(0)
    # Plenty of other nodes cannot hide one missing required selector.
    session.items = session.items[1:] + [SimpleNamespace(nodeid='foreign::test_fixture')]
    with pytest.raises(pytest.UsageError):
        profile.RequiredResults().pytest_collection_finish(session)


@pytest.mark.parametrize('case,expected', [('pass', 0), ('skip', 78), ('missing', 78)])
def test_ci_entrypoint_enforces_real_pytest_results(tmp_path, case, expected):
    (tmp_path / 'test_required.py').write_text(
        'import pytest\n@pytest.mark.pg\ndef test_required():\n    ' +
        ("pytest.skip('required dependency absent')" if case == 'skip' else 'assert True') + '\n')
    source = "from app.ops import pg_acceptance as p; p.SELECTORS=('" + (
        'missing.py' if case == 'missing' else 'test_required.py') + "',); p.MINIMUM_SELECTED=1; raise SystemExit(p.main(['--ci']))"
    result = subprocess.run([sys.executable, '-c', source], cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': str(ROOT)}, capture_output=True, text=True)
    assert result.returncode == expected, result.stdout + result.stderr


def test_production_runner_isolates_database_vault_and_credentials(tmp_path, monkeypatch):
    runner, boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    for key in ('DATABASE_URL', 'DB_DSN', 'VAULT_ROOT', 'BWS_ACCESS_TOKEN', 'GITHUB_TOKEN', 'DOCKER_HOST'):
        monkeypatch.setenv(key, 'persistent-private-secret-canary')
    result = runner.verify()
    calls = [arguments for arguments, _timeout in boundary.commands]
    db = next(args for args in calls if args[0] == 'create' and args[args.index('--name') + 1].endswith('-db'))
    tests = next(args for args in calls if args[0] == 'create' and args[args.index('--name') + 1].endswith('-tests'))
    assert db[db.index('--network') + 1] == 'none'
    assert tests[tests.index('--network') + 1].startswith('container:')
    assert '--publish' not in db and '--network=host' not in tests
    assert '--read-only' in tests and '--cap-drop' in tests and 'no-new-privileges' in tests
    assert '/usr/bin/env' in tests and '-i' in tests
    assert 'VAULT_ROOT=/scratch/vault' in tests
    assert 'persistent-private-secret-canary' not in json.dumps(calls)
    scratch_password = next(value.split('=', 1)[1] for value in db if value.startswith('POSTGRES_PASSWORD='))
    assert re.fullmatch(r'[0-9a-f]{48}', scratch_password)
    assert f'DATABASE_URL=postgresql://app:{scratch_password}@127.0.0.1:5432/app_test' in tests
    assert f'DB_DSN=postgresql://app:{scratch_password}@127.0.0.1:5432/app_test' in tests
    assert scratch_password not in json.dumps(result)
    mounts = [tests[i + 1] for i, value in enumerate(tests) if value == '--mount']
    assert all(str(runner.directory) in mount and mount.endswith('readonly') for mount in mounts)
    assert all('/app/app' not in mount and 'docker.sock' not in mount for mount in mounts)
    assert not boundary.containers
    provision = next(args for args in calls if args[0] == 'exec' and args[2] == 'psql')
    assert '--set=ON_ERROR_STOP=1' in provision
    assert provision[-2:] == ('--command', 'CREATE EXTENSION IF NOT EXISTS vector')
    assert calls.index(provision) < calls.index(tests)
    runner.verify()
    passwords = [next(value.split('=', 1)[1] for value in args if value.startswith('POSTGRES_PASSWORD='))
                 for args, _timeout in boundary.commands
                 if args[0] == 'create' and args[args.index('--name') + 1].endswith('-db')]
    assert len(passwords) == 2 and passwords[0] != passwords[1]
    # Actual subprocess boundary discards all caller credential/socket settings.
    observed = []
    monkeypatch.setattr(runner_module.subprocess, 'run', lambda argv, **options:
                        observed.append(options) or SimpleNamespace(returncode=0, stdout=b''))
    runner_module._command(['docker', 'version'])
    assert 'persistent-private-secret-canary' not in json.dumps(observed[0]['env'])


@pytest.mark.parametrize('fault', ['sha', 'digest', 'resource', 'image'])
def test_candidate_resources_and_imports_match_admitted_image(tmp_path, monkeypatch, fault):
    runner, boundary, sha, operation_id = _runner(tmp_path, monkeypatch)
    boundary.fault = fault
    with pytest.raises(profile.PgAcceptanceError):
        runner.verify()
    assert not boundary.containers
    if fault in {'sha', 'digest'}:
        assert not any(args[0] == 'create' for args, _timeout in boundary.commands)
    boundary.fault = None
    manifest = runner.resources(IMAGE_ID)
    source = runner.directory / 'source'
    assert (source / 'app/__init__.py').read_text() == "IDENTITY = 'candidate-image'\n"
    assert (source / 'tests/conftest.py').read_text() == '# exact fixture\n'
    candidate = tmp_path / 'image-root'
    shutil.copytree(source, candidate)
    import app
    monkeypatch.setattr(app, '__file__', str(candidate / 'app/__init__.py'))
    profile.verify_resources(manifest, root=candidate)
    (candidate / 'app/__init__.py').write_text('wrong app image code')
    with pytest.raises(profile.PgAcceptanceError):
        profile.verify_resources(manifest, root=candidate)
    with pytest.raises(profile.PgAcceptanceError):
        profile.require_pass({**_result(sha, 'dev', operation_id), 'source_sha': '0' * 40}, sha, DIGEST, 'dev', operation_id)
    runner.cleanup()


@pytest.mark.parametrize('field,value', [('profile_version', 'smoke.v0'), ('selection_hash', '0' * 64),
                                       ('source_sha', '0' * 40), ('image_digest', 'sha256:' + '0' * 64),
                                       ('channel', 'test'), ('operation_id', str(uuid4()))])
def test_recovery_cannot_reuse_smoke_only_or_foreign_profile_evidence(tmp_path, field, value):
    sha, operation_id = 'a' * 40, str(uuid4())
    plan = DeployPlan('dev', sha, ('db', 'api'), ('postgres-db', 'postgres-api'), image_digest=DIGEST, automatic=True)
    smoke = DeployReceipt(operation_id, 'dev', 'deploy', 'committed', 'committed')
    with pytest.raises(PostgresDeployError):
        smoke.require_profile(plan)
    receipt = replace(smoke, pg_acceptance={**_result(sha, 'dev', operation_id), field: value})
    with pytest.raises(PostgresDeployError):
        receipt.require_profile(plan)
    journal = DeployJournal(tmp_path / 'native', 'dev')
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'committed'):
        journal.write(operation_id, stage)
    supervisor = linux.DeploymentSupervisor(SimpleNamespace(channel='dev', journal=journal))
    with pytest.raises(PostgresDeployError):
        supervisor.request({'action': 'join', 'operation_id': operation_id,
                            'plan': json.loads(json.dumps(plan.payload())), 'bootstrap': False})
    state = tmp_path / 'controller'
    state.mkdir(mode=0o700)
    candidate = driver.Candidate(sha, DIGEST, 123, 1, 456)
    outcome = {'source_sha': sha, 'image_digest': DIGEST, 'source_run_id': 123, 'source_run_attempt': 1,
               'artifact_id': 456, 'result': 'passed', 'channel': 'dev', 'operation_id': candidate.operation_id('dev'),
               'pg_acceptance': {**_result(sha, 'dev', candidate.operation_id('dev')), field: value}}
    driver._save_outcome(state / 'postmerge-dev-test.json', candidate, outcome)
    assert driver.poll(state, build=lambda: 123, load=lambda _run: candidate,
                       deploy=lambda *_args: pytest.fail('foreign PG result advanced test')) == 0
    assert json.loads((state / 'postmerge-dev-test.json').read_text())['phase'] == 'failed'


def test_interrupted_cleanup_preserves_other_channel_resources(tmp_path, monkeypatch):
    runner, boundary, sha, operation_id = _runner(tmp_path, monkeypatch)
    other = runner_module.PgAcceptanceRunner(runner.repository, tmp_path / 'journal', sha=sha,
                                            digest=DIGEST, channel='test', operation_id=operation_id)
    monkeypatch.setattr(other, '_docker', boundary.command)
    other.resources(IMAGE_ID)
    other._create('db', ['--network', 'none', profile.POSTGRES_IMAGE])
    boundary.fault = 'interrupted'
    with pytest.raises(KeyboardInterrupt):
        runner.verify()
    assert other.directory.exists() and len(boundary.containers) == 1
    assert next(iter(boundary.containers)).startswith(other.name)
    # Simulate daemon loss while the PG phase was in progress: recovery cleans
    # the same operation and writes a truthful candidate failure under its lock.
    runner.resources(IMAGE_ID)
    runner._create('db', ['--network', 'none', profile.POSTGRES_IMAGE])
    journal = DeployJournal(tmp_path / 'native', 'dev')
    plan = DeployPlan('dev', sha, ('db', 'api'), ('postgres-db', 'postgres-api'), image_digest=DIGEST, automatic=True)
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'verifying'):
        journal.write(operation_id, stage)
    supervisor = linux.DeploymentSupervisor(SimpleNamespace(root=runner.repository, channel='dev', journal=journal))
    monkeypatch.setattr(supervisor, '_require_current_config', lambda: None)
    @contextmanager
    def lock(_self):
        yield 'owned-native-lock'
    monkeypatch.setattr(linux.LinuxEffects, 'failed_reconciliation_lock', lock)
    monkeypatch.setattr(linux.LinuxEffects, 'quiescent', lambda _self: True)
    monkeypatch.setattr(linux.LinuxEffects, 'retire_reconciled_channel_lock', lambda _self, _lock: None)
    monkeypatch.setattr(linux.LinuxEffects, '_pg_runner', lambda _self, _id, _plan: runner)
    receipt = supervisor._reconcile_failed(operation_id, plan, False)['receipt']
    assert receipt['terminal_result'] == 'failed' and not runner.directory.exists()
    assert other.directory.exists() and len(boundary.containers) == 1
    other.cleanup()
    assert not boundary.containers


def test_foreign_labels_are_never_cleanup_authority(tmp_path, monkeypatch):
    runner, boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    runner._create('db', ['--network', 'none', profile.POSTGRES_IMAGE])
    row = next(iter(boundary.containers.values()))
    row['Config']['Labels']['io.yggdrasil.pg.channel'] = 'test'
    with pytest.raises(profile.PgAcceptanceError):
        runner.cleanup()
    assert len(boundary.containers) == 1
    assert not any(args[0] == 'rm' for args, _timeout in boundary.commands)


@pytest.mark.parametrize('case', ['startup_race', 'readiness_exhausted'])
def test_database_startup_waits_for_candidate_tcp_listener(tmp_path, monkeypatch, case):
    runner, boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    boundary.fault = case
    monkeypatch.setattr(runner_module.time, 'sleep', lambda _seconds: None)
    if case == 'startup_race':
        assert runner.verify()['result'] == 'passed'
        assert boundary.tcp_probes == 3
    else:
        with pytest.raises(profile.PgAcceptanceError):
            runner.verify()
        assert boundary.tcp_probes == 30
        assert not any(args[:2] == ('start', '--attach') for args, _timeout in boundary.commands)
    probes = [args for args, _timeout in boundary.commands if args[0] == 'exec' and args[2] == 'pg_isready']
    assert probes and all(args[args.index('-h') + 1] == '127.0.0.1' for args in probes)
    assert all(args[args.index('-p') + 1] == '5432' for args in probes)
    assert not boundary.containers and not runner.directory.exists() and not runner.marker.exists()


@pytest.mark.parametrize('crash', ['before_owner_open', 'partial_owner', 'owner_ready_before_directory',
                                  'after_directory_creation', 'partial_rmtree', 'directory_removed'])
def test_resource_creation_and_removal_crashes_recover_same_native_operation(tmp_path, monkeypatch, crash):
    runner, boundary, sha, operation_id = _runner(tmp_path, monkeypatch)
    if crash in {'partial_rmtree', 'directory_removed'}:
        runner.resources(IMAGE_ID)
    with monkeypatch.context() as interrupted:
        if crash == 'before_owner_open':
            original = runner_module.os.open
            def fail_open(path, *args, **kwargs):
                if Path(path) == runner.preparing:
                    raise OSError('interrupted owner creation')
                return original(path, *args, **kwargs)
            interrupted.setattr(runner_module.os, 'open', fail_open)
        elif crash == 'partial_owner':
            original = runner_module.json.dump
            def fail_write(value, target, *args, **kwargs):
                if value == runner.identity:
                    target.write('{')
                    target.flush()
                    raise OSError('interrupted owner write')
                return original(value, target, *args, **kwargs)
            interrupted.setattr(runner_module.json, 'dump', fail_write)
        elif crash == 'owner_ready_before_directory':
            original = Path.mkdir
            def fail_mkdir(path, *args, **kwargs):
                if path == runner.directory:
                    raise OSError('interrupted directory create')
                return original(path, *args, **kwargs)
            interrupted.setattr(Path, 'mkdir', fail_mkdir)
        elif crash == 'after_directory_creation':
            interrupted.setattr(runner, '_git', lambda *_args: (_ for _ in ()).throw(OSError('interrupted snapshot')))
        elif crash == 'partial_rmtree':
            original = runner_module.shutil.rmtree
            def fail_rmtree(path, *args, **kwargs):
                if path == runner.directory:
                    (path / 'source/tests/conftest.py').unlink()
                    raise OSError('interrupted resource deletion')
                return original(path, *args, **kwargs)
            interrupted.setattr(runner_module.shutil, 'rmtree', fail_rmtree)
        else:
            original = Path.unlink
            def fail_unlink(path, *args, **kwargs):
                if path == runner.marker:
                    raise OSError('interrupted final marker removal')
                return original(path, *args, **kwargs)
            interrupted.setattr(Path, 'unlink', fail_unlink)
        with pytest.raises(OSError):
            if crash in {'partial_rmtree', 'directory_removed'}:
                runner.cleanup()
            else:
                runner.resources(IMAGE_ID)
    journal = DeployJournal(tmp_path / 'native', 'dev')
    plan = DeployPlan('dev', sha, ('db', 'api'), ('postgres-db', 'postgres-api'), image_digest=DIGEST, automatic=True)
    journal.bind_request(operation_id, plan, False, create=True)
    for stage in ('prepared', 'preflighted', 'materialized', 'activating', 'verifying'):
        journal.write(operation_id, stage)
    config = SimpleNamespace(channel='dev', root=runner.repository, journal=journal)
    supervisor = linux.DeploymentSupervisor(config)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    retired = []
    @contextmanager
    def lock(_self):
        yield 'same-native-lock'
    monkeypatch.setattr(linux.LinuxEffects, 'failed_reconciliation_lock', lock)
    monkeypatch.setattr(linux.LinuxEffects, 'quiescent', lambda _self: True)
    monkeypatch.setattr(linux.LinuxEffects, 'retire_reconciled_channel_lock', lambda _self, value: retired.append(value))
    monkeypatch.setattr(linux.LinuxEffects, '_pg_runner', lambda _self, _id, _plan: runner)
    request = {'action': 'reconcile-failed', 'operation_id': operation_id,
               'plan': json.loads(json.dumps(plan.payload())), 'bootstrap': False}
    receipt = supervisor.request(request)['receipt']
    assert receipt['terminal_result'] == 'failed' and journal.read().stage == 'failed'
    assert retired == ['same-native-lock']
    assert not runner.directory.exists() and not runner.marker.exists() and not runner.preparing.exists()
    assert not boundary.containers


@pytest.mark.parametrize('directory_already_removed', [False, True])
def test_cleanup_durably_removes_directory_before_retiring_owner(tmp_path, monkeypatch, directory_already_removed):
    runner, _boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    runner.resources(IMAGE_ID)
    if directory_already_removed:
        # Prior cleanup may have removed the directory without reaching its
        # parent durability barrier; current recovery must still flush absence.
        shutil.rmtree(runner.directory)
    events = []
    actual_sync = runner._sync_parent
    def sync():
        actual_sync()
        events.append(('parent_fsync', runner.directory.exists(), runner.marker.exists()))
    monkeypatch.setattr(runner, '_sync_parent', sync)
    actual_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path == runner.marker:
            assert events and events[-1] == ('parent_fsync', False, True)
            events.append(('marker_unlink', False, True))
        return actual_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', unlink)
    runner.cleanup()
    assert events == [('parent_fsync', False, True), ('marker_unlink', False, True),
                      ('parent_fsync', False, False)]
