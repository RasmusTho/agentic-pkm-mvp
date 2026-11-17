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

from app.ops import pg_acceptance as profile
from app.ops import pg_acceptance_runner as runner_module
from app.ops import bws_installation_transaction as installation_transaction
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
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == 'docker-compose.yaml':
                path.write_text(
                    'services:\n'
                    '  api: {}\n'
                    '  companion-ui: {}\n'
                    '  db: {}\n'
                    '  heimdal-capture-watch: {}\n'
                    '  instance-state-init: {}\n'
                    '  migrate: {}\n'
                    '  ollama: {}\n'
                    '  source-identity-db-witness: {}\n'
                    '  watcher: {}\n'
                    '  worker: {}\n'
                )
            else:
                path.write_text('exact resource')
            if name.endswith('.sh') and name.startswith('scripts/'):
                path.chmod(0o755)
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
                'State': {'OOMKilled': False, 'ExitCode': 0, 'Running': False},
                'HostConfig': {'NetworkMode': arguments[arguments.index('--network') + 1],
                               'ReadonlyRootfs': '--read-only' in arguments, 'CapDrop': ['ALL'],
                               'Memory': (int(arguments[arguments.index('--memory') + 1])
                                          if '--memory' in arguments else 0) + int(self.fault == 'memory_mismatch'),
                               'MemorySwap': int(arguments[arguments.index('--memory-swap') + 1])
                                             if '--memory-swap' in arguments else 0},
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
            if self.fault == 'incomplete':
                return b'457 passing cases; no complete envelope'
            if self.fault == 'interrupted':
                raise KeyboardInterrupt()
            test_row = next(row for row in self.containers.values() if row['Id'] == arguments[-1])
            test_row['State'] = {'OOMKilled': self.fault == 'oom_test', 'ExitCode': 0, 'Running': False}
            if self.fault == 'oom_db':
                next(row for name, row in self.containers.items() if name.endswith('-db'))['State']['OOMKilled'] = True
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
        if arguments[0] == 'start':
            next(row for row in self.containers.values() if row['Id'] == arguments[-1])['State']['Running'] = True
            return b''
        return b''


def _runner(tmp_path, monkeypatch, *, channel='dev', operation_id=None, memory_policy=None):
    root, sha = _repository(tmp_path)
    operation_id = operation_id or str(uuid4())
    runner = runner_module.PgAcceptanceRunner(root, tmp_path / 'journal', sha=sha,
                                            digest=DIGEST, channel=channel, operation_id=operation_id,
                                            memory_policy=memory_policy)
    boundary = DockerBoundary(runner)
    monkeypatch.setattr(runner, '_docker', boundary.command)
    return runner, boundary, sha, operation_id


def _native_source_absent(monkeypatch, channel, operation_id):
    # PG qualification fixtures never create a channel source-bootstrap one-off.
    # Keep its new independent census at the transport seam, not by skipping
    # production recovery or contacting the ambient Docker daemon.
    def command(argv, **kwargs):
        assert argv == ['docker', 'ps', '--all', '--filter',
                        f'name=^/pkm-{channel}-source-bootstrap-{operation_id}$',
                        '--format', '{{.ID}}']
        assert kwargs == {'timeout': 15}
        return ''
    monkeypatch.setattr(linux, '_command', command)


@pytest.mark.parametrize('fault', [None, 'timeout', 'incomplete', 'dependency', 'provision', 'profile', 'resource', 'image'])
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


def test_scalar_rollback_resources_are_committed_and_readonly(tmp_path, monkeypatch):
    runner, boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    committed = {
        name: (runner.repository / name).read_bytes()
        for name in (
            'docker-compose.yaml', 'docker-compose.scalar-rollback.yml',
            'ops/scalar-rollback/nginx.conf', 'scripts/scalar_rollback_native.sh',
        )
    }
    (runner.repository / 'docker-compose.yaml').write_bytes(b'dirty checkout bytes')
    manifest = runner.resources(IMAGE_ID)
    source = runner.directory / 'source'
    for name, content in committed.items():
        path = source / name
        assert path.read_bytes() == content
        assert manifest['files'][name] == hashlib.sha256(content).hexdigest()
    assert (source / 'scripts/scalar_rollback_native.sh').stat().st_mode & 0o777 == 0o755
    runner.cleanup()

    runner.verify()
    calls = [arguments for arguments, _timeout in boundary.commands]
    tests = next(args for args in calls if args[0] == 'create' and args[args.index('--name') + 1].endswith('-tests'))
    mounts = {
        fields['dst']: fields
        for index, value in enumerate(tests)
        if value == '--mount'
        for fields in [dict(part.split('=', 1) for part in tests[index + 1].split(',') if '=' in part)]
    }
    assert {
        '/app/docker-compose.yaml', '/app/docker-compose.scalar-rollback.yml',
        '/app/ops/scalar-rollback/nginx.conf', '/app/scripts/scalar_rollback_native.sh',
    } <= mounts.keys()
    for index, value in enumerate(tests):
        if value != '--mount':
            continue
        fields = dict(part.split('=', 1) for part in tests[index + 1].split(',') if '=' in part)
        if fields.get('dst') in {
            '/app/docker-compose.yaml', '/app/docker-compose.scalar-rollback.yml',
            '/app/ops/scalar-rollback/nginx.conf', '/app/scripts/scalar_rollback_native.sh',
        }:
            assert tests[index + 1].endswith(',readonly')
    assert not boundary.containers


def test_native_principal_producer_resources_are_complete_and_readonly(tmp_path, monkeypatch):
    from app.instance.principal_fence import (
        AUTH_PRODUCER_ROLES,
        NATIVE_AUTH_PRODUCERS,
        discover_auth_producers,
    )

    runner, boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    resources = (
        'scripts/deploy_channel.sh',
        'scripts/export_runtime_env.sh',
        'scripts/start_full_system.sh',
    )
    committed = {name: (runner.repository / name).read_bytes() for name in resources}
    manifest = runner.resources(IMAGE_ID)
    source = runner.directory / 'source'
    for name, content in committed.items():
        path = source / name
        assert path.read_bytes() == content
        assert manifest['files'][name] == hashlib.sha256(content).hexdigest()
        assert path.stat().st_mode & 0o777 == 0o755
    producers, digest = discover_auth_producers(
        compose_path=source / 'docker-compose.yaml',
        repo_root=source,
    )
    assert {producer.role for producer in producers} == AUTH_PRODUCER_ROLES
    assert {producer.source for producer in producers} >= set(NATIVE_AUTH_PRODUCERS)
    assert {
        path for path in NATIVE_AUTH_PRODUCERS if path.startswith('scripts/')
    } <= set(runner_module.RESOURCE_PATHS)
    assert re.fullmatch(r'[0-9a-f]{64}', digest)
    assert digest == discover_auth_producers(
        compose_path=source / 'docker-compose.yaml',
        repo_root=source,
    )[1]
    runner.cleanup()

    runner.verify()
    calls = [arguments for arguments, _timeout in boundary.commands]
    tests = next(args for args in calls if args[0] == 'create' and args[args.index('--name') + 1].endswith('-tests'))
    mounts = {
        fields['dst']: fields
        for index, value in enumerate(tests)
        if value == '--mount'
        for fields in [dict(part.split('=', 1) for part in tests[index + 1].split(',') if '=' in part)]
    }
    destinations = {f'/app/{name}' for name in resources}
    assert destinations <= mounts.keys()
    for destination in destinations:
        mount = next(
            tests[index + 1]
            for index, value in enumerate(tests)
            if value == '--mount'
            and dict(part.split('=', 1) for part in tests[index + 1].split(',') if '=' in part).get('dst') == destination
        )
        assert mount.endswith(',readonly')
    assert not boundary.containers


def test_scalar_rollback_resource_closure_refuses_missing_or_tampered_assets(tmp_path, monkeypatch):
    runner, _boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    manifest = runner.resources(IMAGE_ID)
    source = runner.directory / 'source'
    candidate = tmp_path / 'image-root'
    shutil.copytree(source, candidate)
    import app
    monkeypatch.setattr(app, '__file__', str(candidate / 'app/__init__.py'))
    assets = (
        'docker-compose.yaml', 'docker-compose.scalar-rollback.yml',
        'ops/scalar-rollback/nginx.conf', 'scripts/scalar_rollback_native.sh',
        'scripts/deploy_channel.sh', 'scripts/export_runtime_env.sh',
        'scripts/start_full_system.sh',
    )
    for asset in assets:
        path = candidate / asset
        original = path.read_bytes()
        path.unlink()
        with pytest.raises(profile.PgAcceptanceError):
            profile.verify_resources(manifest, root=candidate)
        path.write_bytes(original + b'\n')
        with pytest.raises(profile.PgAcceptanceError):
            profile.verify_resources(manifest, root=candidate)
        path.write_bytes(original)
    runner.cleanup()


def test_native_principal_producer_resources_refuse_missing_or_tampered_files(tmp_path, monkeypatch):
    from app.instance.principal_fence import PrincipalFenceError, discover_auth_producers

    runner, _boundary, _sha, _operation_id = _runner(tmp_path, monkeypatch)
    manifest = runner.resources(IMAGE_ID)
    source = runner.directory / 'source'
    candidate = tmp_path / 'image-root'
    shutil.copytree(source, candidate)
    import app
    monkeypatch.setattr(app, '__file__', str(candidate / 'app/__init__.py'))
    assets = (
        'scripts/deploy_channel.sh', 'scripts/export_runtime_env.sh',
        'scripts/start_full_system.sh',
    )
    for asset in assets:
        path = candidate / asset
        original = path.read_bytes()
        path.unlink()
        with pytest.raises(PrincipalFenceError, match=Path(asset).name):
            discover_auth_producers(
                compose_path=candidate / 'docker-compose.yaml',
                repo_root=candidate,
            )
        with pytest.raises(profile.PgAcceptanceError):
            profile.verify_resources(manifest, root=candidate)
        path.write_bytes(original + b'\n')
        with pytest.raises(profile.PgAcceptanceError):
            profile.verify_resources(manifest, root=candidate)
        path.write_bytes(original)
    runner.cleanup()


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


@pytest.mark.parametrize(
    'field,value',
    [
        ('profile_version', 'smoke.v0'),
        ('selection_hash', '0' * 64),
        ('source_sha', '0' * 40),
        ('image_digest', 'sha256:' + '0' * 64),
        ('channel', 'test'),
        ('operation_id', str(uuid4())),
    ],
    ids=[
        'profile-version',
        'selection-hash',
        'source-sha',
        'image-digest',
        'channel',
        'operation-id',
    ],
)
def test_recovery_cannot_reuse_smoke_only_or_foreign_profile_evidence(tmp_path, field, value, monkeypatch):
    dispatches = []
    monkeypatch.setattr(driver, 'dispatch_verdict', lambda *_args: pytest.fail('unmocked GitHub dispatch'))
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
                       deploy=lambda *_args: pytest.fail('foreign PG result advanced test'),
                       dispatch=lambda sent_candidate, evidence: dispatches.append((sent_candidate, dict(evidence))),
                       alert=lambda _evidence: None) == 0
    assert dispatches == [(candidate, {'result': 'refused', 'reason': 'dev_deploy_failed', 'dispatch': 'started'})]
    checkpoint = json.loads((state / 'postmerge-dev-test.json').read_text())
    assert checkpoint['phase'] == 'failed'
    assert checkpoint['heavy'] == {'result': 'refused', 'reason': 'dev_deploy_failed', 'dispatch': 'sent'}


def test_interrupted_cleanup_preserves_other_channel_resources(tmp_path, monkeypatch):
    runner, boundary, sha, operation_id = _runner(tmp_path, monkeypatch)
    _native_source_absent(monkeypatch, 'dev', operation_id)
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
    _native_source_absent(monkeypatch, 'dev', operation_id)
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


def _deadline_native_worker(tmp_path, monkeypatch, *, cleanup_refuses=False):
    root, sha = _repository(tmp_path)
    operation_id = str(uuid4())
    journal = DeployJournal(tmp_path / 'native-journal', 'dev')
    effects = linux.LinuxEffects(SimpleNamespace(root=root, channel='dev', journal=journal))
    effects.lock_fd = 123
    effects.operation_id = operation_id
    plan = DeployPlan('dev', sha, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=DIGEST, automatic=True)
    signals = []
    monkeypatch.setattr(linux, '_emit_native_diagnostic', signals.append)
    # This is the production factory, including its fixed native signal wiring.
    runner = effects._pg_runner(operation_id, plan)
    boundary = DockerBoundary(runner)
    actual_run = subprocess.run
    expired = []

    def run(argv, **options):
        if argv[:3] == ['docker', 'start', '--attach']:
            assert options['timeout'] == profile.PROFILE_DEADLINE
            expired.append(True)
            raise subprocess.TimeoutExpired(argv, options['timeout'],
                                            output=b'private-output-canary', stderr=b'private-error-canary')
        return actual_run(argv, **options)

    def docker(*arguments, timeout=60):
        if arguments[:2] == ('start', '--attach'):
            return runner_module._command(['docker', *arguments], timeout=timeout)
        return boundary.command(*arguments, timeout=timeout)

    actual_cleanup = runner.cleanup
    def cleanup():
        if cleanup_refuses and expired:
            raise profile.PgAcceptanceError()
        actual_cleanup()

    monkeypatch.setattr(runner_module.subprocess, 'run', run)
    monkeypatch.setattr(runner, '_docker', docker)
    monkeypatch.setattr(runner, 'cleanup', cleanup)
    monkeypatch.setattr(effects, '_pg_runner', lambda identifier, _plan: runner if identifier == operation_id else None)
    monkeypatch.setattr(effects, 'preflight', lambda _plan: 'fixture-password')
    monkeypatch.setattr(effects, 'initialized', lambda: False)
    monkeypatch.setattr(effects, 'materialize', lambda _password: None)
    monkeypatch.setattr(effects, 'quiescent', lambda: True)
    monkeypatch.setattr(effects, 'activate', lambda _plan: None)
    journal.bind_request(operation_id, plan, False, create=True)
    return DeployWorker(journal, effects), journal, plan, operation_id, runner, boundary, signals, actual_cleanup


def test_native_profile_budget_is_bound_and_finite(tmp_path, monkeypatch):
    runner, boundary, sha, operation_id = _runner(tmp_path, monkeypatch)
    result = runner.verify()
    attach = [(args, timeout) for args, timeout in boundary.commands if args[:2] == ('start', '--attach')]
    assert len(attach) == 1 and attach[0][1] == profile.PROFILE_DEADLINE == 5400
    profile.require_pass(result, sha, DIGEST, 'dev', operation_id)
    assert profile.TEST_TIMEOUT == 120 and '--timeout=120' in profile.pytest_arguments()
    assert not boundary.containers and not runner.directory.exists()


def test_native_attach_timeout_is_typed_and_cleanup_runs(tmp_path, monkeypatch, capsys):
    worker, journal, plan, operation_id, runner, boundary, signals, _cleanup = _deadline_native_worker(tmp_path, monkeypatch)
    with pytest.raises(profile.PgAcceptanceDeadlineExceeded) as refused:
        runner_module._command(['docker', 'start', '--attach', 'private-argv-canary'], timeout=profile.PROFILE_DEADLINE)
    assert refused.value.__cause__ is None and 'canary' not in str(refused.value)
    receipt = worker.run(operation_id, plan)
    assert receipt.terminal_result == 'failed' and receipt.pg_acceptance is None
    assert not boundary.containers and not runner.directory.exists() and not runner.marker.exists()
    assert signals == [b'PRIORITY=3\nSYSLOG_IDENTIFIER=yggdrasil-bws-deploy\n'
                       b'MESSAGE=native PG acceptance failure: reason=profile_deadline_exceeded\n']
    assert 'canary' not in repr(signals) + repr(capsys.readouterr())
    candidate, calls = driver.Candidate(plan.revision, DIGEST, 1, 1, 1), []
    def failed(channel, _candidate):
        calls.append(channel)
        return {'stage': 'failed', 'terminal_result': 'failed', 'operation_id': operation_id}
    assert driver.deliver(candidate, deploy=failed, current_main=lambda: plan.revision, emit=lambda _row: None) == 78
    assert calls == ['dev'] and journal.read().terminal_result == 'failed'


def test_deadline_signal_survives_cleanup_refusal(tmp_path, monkeypatch):
    worker, journal, plan, operation_id, runner, boundary, signals, cleanup = _deadline_native_worker(
        tmp_path, monkeypatch, cleanup_refuses=True)
    with pytest.raises(PostgresDeployError):
        worker.run(operation_id, plan)
    receipt = journal.read()
    assert receipt.stage == 'verifying' and receipt.terminal_result is None and receipt.pg_acceptance is None
    assert signals and b'reason=profile_deadline_exceeded' in signals[0]
    assert boundary.containers and runner.marker.exists()
    cleanup()  # Fixture teardown only; this does not manufacture terminal evidence.


def test_profile_budget_identity_rejects_old_receipts(tmp_path, monkeypatch):
    old_hash = 'ee37e3f865bfcdcb3de2345030bc5df7ab396a72de55d94f280e961887e4c381'
    runner, boundary, sha, operation_id = _runner(tmp_path, monkeypatch)
    observed_manifests = []
    original = boundary.command
    def docker(*arguments, timeout=60):
        if arguments[:2] == ('start', '--attach'):
            observed_manifests.append(json.loads((runner.directory / 'source/pg-acceptance-manifest.json').read_text()))
        return original(*arguments, timeout=timeout)
    monkeypatch.setattr(runner, '_docker', docker)
    result = runner.verify()
    plan = DeployPlan('dev', sha, ('db', 'api'), ('postgres-db', 'postgres-api'), image_digest=DIGEST, automatic=True)
    expected = {'version': profile.PROFILE_VERSION, 'selection_hash': profile.SELECTION_HASH}
    assert plan.payload()['verification_profile'] == expected
    assert observed_manifests[0]['selection_hash'] == result['selection_hash'] == profile.SELECTION_HASH != old_hash
    with pytest.raises(profile.PgAcceptanceError):
        profile.require_pass({**result, 'selection_hash': old_hash}, sha, DIGEST, 'dev', operation_id)
    receipt = DeployReceipt(operation_id, 'dev', 'deploy', 'committed', 'committed', pg_acceptance=result)
    receipt.validate()
    receipt.require_profile(plan)


LEGACY_PROFILE_DEADLINE = 3600
LEGACY_SELECTION_HASH = 'ee37e3f865bfcdcb3de2345030bc5df7ab396a72de55d94f280e961887e4c381'


def _legacy_terminal_fixture(
    tmp_path, *, channel='dev', terminal_result='committed', operation_id=None,
):
    """Install one exact retained C2 request/receipt pair without using bind_request."""
    operation_id = operation_id or str(uuid4())
    revision = 'a' * 40
    plan = DeployPlan(channel, revision, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=DIGEST, automatic=True)
    raw_plan = plan.payload()
    raw_plan['verification_profile'] = {
        'version': profile.LEGACY_PROFILE_VERSION,
        'selection_hash': LEGACY_SELECTION_HASH,
    }
    acceptance = None
    if terminal_result == 'committed':
        acceptance = _result(revision, channel, operation_id)
        acceptance['selection_hash'] = LEGACY_SELECTION_HASH
    receipt = DeployReceipt(operation_id, channel, 'deploy', terminal_result, terminal_result,
                            pg_acceptance=acceptance)
    journal = DeployJournal(tmp_path / 'native-history', channel)
    journal.directory.parent.mkdir(parents=True, exist_ok=True)
    journal.directory.mkdir(mode=0o700)
    journal._write_json(journal._operation_name(operation_id, 'request'), {
        'operation_id': operation_id, 'plan': raw_plan, 'bootstrap': False,
    })
    journal._write_json(journal._operation_name(operation_id, 'receipt'), receipt.payload())
    journal._write_json(f'{channel}.json', receipt.payload())
    journal._write_json(f'{channel}.request.json', {
        'operation_id': operation_id, 'plan': raw_plan, 'bootstrap': False,
    })
    return journal, operation_id, plan, raw_plan, receipt


def test_legacy_terminal_profile_history_allows_fresh_current_prepare(tmp_path):
    for channel in ('dev', 'test'):
        journal, operation_id, _legacy_plan, raw_plan, receipt = _legacy_terminal_fixture(
            tmp_path / channel, channel=channel,
        )
        with pytest.raises(PostgresDeployError):
            DeployPlan.from_payload(raw_plan)

        retained = journal.operation_request(operation_id)
        assert retained is not None and retained[0]['plan'] == json.loads(json.dumps(raw_plan))
        assert retained[1].payload()['verification_profile'] == raw_plan['verification_profile']
        assert journal.operation_receipt(operation_id) == receipt

        current = DeployPlan(channel, 'b' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'),
                             image_digest=DIGEST, automatic=True)
        fresh_id = str(uuid4())
        # A fresh prepare first asks whether its ID has a retained receipt while
        # the channel slot still contains the exact old terminal pair.  This must
        # return no receipt without strict-reading the old profile as new state.
        assert journal.operation_receipt(fresh_id) is None
        retained_bytes = (journal.directory / f'{operation_id}.request.json').read_bytes()
        journal.bind_request(fresh_id, current, False, create=True)
        journal.write(fresh_id, 'prepared')
        assert journal.current_request()[1] == current
        assert (journal.directory / f'{operation_id}.request.json').read_bytes() == retained_bytes
        assert journal.operation_request(operation_id)[0]['plan'] == json.loads(json.dumps(raw_plan))


def test_legacy_terminal_profile_history_allows_real_supervisor_fresh_worker(
    tmp_path, monkeypatch, admitted_bws_caller,
):
    """Fresh workers supersede only exact failed-DEV/committed-TEST terminal pairs."""
    from contextlib import contextmanager
    from types import SimpleNamespace
    from tests.deploy.test_deploy_channel_script import _BwsVmEffects

    for channel, terminal_result in (('dev', 'failed'), ('test', 'committed')):
        journal, old_id, old_plan, _raw_plan, _old_receipt = _legacy_terminal_fixture(
            tmp_path / channel, channel=channel, terminal_result=terminal_result,
        )
        old_request_bytes = (journal.directory / f'{old_id}.request.json').read_bytes()
        old_receipt_bytes = (journal.directory / f'{old_id}.receipt.json').read_bytes()
        current = DeployPlan(channel, 'b' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'),
                             image_digest=DIGEST, automatic=True)
        fresh_id = str(uuid4())
        effects = _BwsVmEffects()
        effects.config = SimpleNamespace(channel=channel, journal=journal)
        if channel == 'dev':
            effects.require_promotion_admission = lambda _plan: None
        effects.validate_plan = lambda selected: selected.validate()
        effects.select_active_plan = lambda selected: selected
        effects.verify = lambda operation_id, plan: {
            **profile.identity(plan.revision, plan.image_digest or '', plan.channel, operation_id),
            'result': 'passed', 'selected': len(profile.SELECTORS), 'passed': len(profile.SELECTORS),
            'resource_tree': 'd' * 40, 'app_image_id': IMAGE_ID, 'report_hash': 'e' * 64,
        }
        effects.cleanup_verification = lambda *_args: None

        @contextmanager
        def channel_lock():
            yield
            receipt = journal.read()
            assert receipt is not None and receipt.operation_id == fresh_id

        effects.channel_lock = channel_lock
        monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: effects.config)
        monkeypatch.setattr(linux, 'LinuxEffects', lambda _config: effects)
        supervisor = linux.DeploymentSupervisor(effects.config)
        request = {
            'action': 'prepare', 'operation_id': fresh_id,
            'plan': json.loads(json.dumps(current.payload())), 'bootstrap': False,
        }
        assert supervisor.request(request)['ready']
        operation = supervisor.operation
        assert operation is not None
        operation.activation.set()
        result = supervisor.request({**request, 'action': 'join'})
        assert result['receipt']['terminal_result'] == 'committed'
        assert journal.read().operation_id == fresh_id
        assert (journal.directory / f'{old_id}.request.json').read_bytes() == old_request_bytes
        assert (journal.directory / f'{old_id}.receipt.json').read_bytes() == old_receipt_bytes
        retained_old = journal.operation_request(old_id)
        assert retained_old is not None and retained_old[1].revision == old_plan.revision
        assert retained_old[1].verification_profile == {
            'version': profile.LEGACY_PROFILE_VERSION, 'selection_hash': LEGACY_SELECTION_HASH,
        }


def test_legacy_terminal_profile_history_refuses_failed_bootstrap_before_publication(
    tmp_path, monkeypatch, admitted_bws_caller,
):
    """A failed legacy pair with bootstrap authority cannot publish a fresh ID."""
    from contextlib import contextmanager
    from tests.deploy.test_deploy_channel_script import _BwsVmEffects

    journal, old_id, _old_plan, _raw_plan, _old_receipt = _legacy_terminal_fixture(
        tmp_path, channel='dev', terminal_result='failed',
    )
    for name in (f'{old_id}.request.json', 'dev.request.json'):
        request = json.loads((journal.directory / name).read_text())
        request['bootstrap'] = True
        (journal.directory / name).write_text(json.dumps(request))
    current = DeployPlan('dev', 'b' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'),
                         image_digest=DIGEST, automatic=True)
    fresh_id = str(uuid4())
    effects = _BwsVmEffects()
    effects.config = SimpleNamespace(channel='dev', journal=journal)
    reached_worker = []

    @contextmanager
    def channel_lock():
        reached_worker.append(True)
        yield

    effects.channel_lock = channel_lock
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: effects.config)
    monkeypatch.setattr(linux, 'LinuxEffects', lambda _config: effects)
    supervisor = linux.DeploymentSupervisor(effects.config)
    with pytest.raises(PostgresDeployError):
        supervisor.request({
            'action': 'prepare', 'operation_id': fresh_id,
            'plan': json.loads(json.dumps(current.payload())), 'bootstrap': False,
        })
    assert supervisor.operation is None
    assert reached_worker == []
    assert not (journal.directory / f'{fresh_id}.request.json').exists()
    # The old failed C2 record is historical-only, and its deliberately
    # malformed bootstrap binding must not be admitted even by the historical
    # reader.
    with pytest.raises(PostgresDeployError):
        journal.read()


def test_legacy_terminal_profile_history_qualifies_source_preflight(tmp_path):
    from app.ops import native_source_admission

    # Source admission and the writer census must both qualify the two
    # supported terminal states.  The failed DEV envelope has no PG payload;
    # the committed TEST envelope must still satisfy the pinned historical
    # profile.  Neither reader may turn the old request into current state.
    for channel, terminal_result in (('dev', 'failed'), ('test', 'committed')):
        journal, operation_id, _legacy_plan, _raw_plan, receipt = _legacy_terminal_fixture(
            tmp_path / channel, channel=channel, terminal_result=terminal_result,
        )
        effects = SimpleNamespace(config=SimpleNamespace(journal=journal), operation_id=operation_id)

        native_source_admission.require_terminal_deployment(effects)
        assert journal.read(historical=True) == receipt
        with pytest.raises(PostgresDeployError):
            journal.read()

        runtime = SimpleNamespace(
            installed_fingerprint='1' * 64, execution_fingerprint='2' * 64,
            running_writers=('api', 'worker', 'watcher'), existing_writers=('api', 'worker', 'watcher'),
            census_fingerprint='3' * 64, retained_state_fingerprint='4' * 64,
            container_root='/srv/app', vault_overlay='docker-compose.full-host-vault.yml',
        )
        effects = SimpleNamespace(
            config=SimpleNamespace(channel=channel, journal=journal),
            source_identity_runtime_snapshot=lambda *_args, **_kwargs: runtime,
            quiescent=lambda: True,
        )
        snapshot = installation_transaction._current_writer_snapshot(effects, {
            'channel': channel, 'candidate_sha': 'b' * 40, 'image_digest': DIGEST,
        })
        assert snapshot.terminal_revision == 'a' * 40
        assert snapshot.terminal_image_digest == DIGEST


def test_legacy_terminal_profile_history_refuses_invalid_or_replayed_pairs(tmp_path, monkeypatch):
    def expect_refusal(journal, operation):
        before = {path.name: path.read_bytes() for path in journal.directory.iterdir()}
        with pytest.raises(PostgresDeployError):
            operation()
        assert {path.name: path.read_bytes() for path in journal.directory.iterdir()} == before

    journal, operation_id, legacy_plan, raw_plan, _receipt = _legacy_terminal_fixture(tmp_path)
    expect_refusal(journal, lambda: journal.bind_request(
        operation_id, DeployPlan('dev', 'b' * 40, ('db', 'api'),
                                 ('postgres-db', 'postgres-api'),
                                 image_digest=DIGEST, automatic=True), False,
    ))
    # Reusing the old ID with a current-profile plan is not a prepare/join or
    # reconcile path; even a first current write must leave every old byte
    # untouched.
    expect_refusal(journal, lambda: journal.write(operation_id, 'prepared'))
    same_source_current = DeployPlan(
        legacy_plan.channel, legacy_plan.revision, legacy_plan.services, legacy_plan.consumers,
        image_digest=DIGEST, automatic=True,
    )
    config = SimpleNamespace(channel='dev', journal=journal)
    monkeypatch.setattr(linux.LinuxConfig, 'load', lambda _channel: config)
    for action in ('prepare', 'join', 'reconcile-failed'):
        expect_refusal(journal, lambda action=action: linux.DeploymentSupervisor(config).request({
            'action': action, 'operation_id': operation_id,
            'plan': same_source_current.payload(), 'bootstrap': False,
        }))
    expect_refusal(journal, lambda: journal.write(
        operation_id, 'committed', _result(legacy_plan.revision, 'dev', operation_id),
    ))

    foreign, foreign_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'foreign')
    foreign_receipt = json.loads((foreign.directory / f'{foreign_id}.receipt.json').read_text())
    foreign_receipt['pg_acceptance']['channel'] = 'test'
    foreign._write_json(f'{foreign_id}.receipt.json', foreign_receipt)
    foreign._write_json('dev.json', foreign_receipt)
    expect_refusal(foreign, lambda: foreign.operation_request(foreign_id))

    named_slot, named_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'named-slot')
    retained_foreign = json.loads((named_slot.directory / f'{named_id}.receipt.json').read_text())
    retained_foreign['operation_id'] = str(uuid4())
    named_slot._write_json(f'{named_id}.receipt.json', retained_foreign)
    # A UUID-named retained slot is not an optional archive: its embedded ID
    # must bind the filename before a valid current slot can be considered.
    expect_refusal(named_slot, lambda: named_slot.operation_request(named_id))

    mixed_non_pg, mixed_non_pg_id, _plan, old_raw_plan, _receipt = _legacy_terminal_fixture(
        tmp_path / 'mixed-karakeep',
    )
    karakeep_request = {
        'operation_id': mixed_non_pg_id,
        'plan': {'channel': 'dev', 'revision': 'a' * 40},
        'bootstrap': False,
    }
    manual_receipt = DeployReceipt(
        mixed_non_pg_id, 'dev', 'deploy', 'committed', 'committed',
    ).payload()
    for name in (f'{mixed_non_pg_id}.request.json', 'dev.request.json'):
        mixed_non_pg._write_json(name, karakeep_request)
    for name in (f'{mixed_non_pg_id}.receipt.json', 'dev.json'):
        mixed_non_pg._write_json(name, manual_receipt)
    # The retained non-EE view must not hide an EE request/receipt that has
    # appeared in the same-ID current slots.
    mixed_non_pg._write_json('dev.request.json', {
        'operation_id': mixed_non_pg_id, 'plan': old_raw_plan, 'bootstrap': False,
    })
    mixed_non_pg._write_json('dev.json', DeployReceipt(
        mixed_non_pg_id, 'dev', 'deploy', 'failed', 'failed',
    ).payload())
    expect_refusal(mixed_non_pg, lambda: mixed_non_pg.operation_request(mixed_non_pg_id))
    expect_refusal(mixed_non_pg, lambda: mixed_non_pg.operation_receipt(mixed_non_pg_id))

    tampered = json.loads((journal.directory / f'{operation_id}.receipt.json').read_text())
    tampered['pg_acceptance']['source_sha'] = 'c' * 40
    (journal.directory / f'{operation_id}.receipt.json').write_text(json.dumps(tampered))
    expect_refusal(journal, lambda: journal.operation_receipt(operation_id))

    expect_refusal(journal, lambda: journal.current_request())

    missing, missing_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'missing')
    (missing.directory / f'{missing_id}.receipt.json').unlink()
    (missing.directory / 'dev.json').unlink()
    expect_refusal(missing, lambda: missing.operation_request(missing_id))

    incomplete, incomplete_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'incomplete')
    incomplete._write_json(f'{incomplete_id}.receipt.json', DeployReceipt(
        incomplete_id, 'dev', 'deploy', 'prepared', None,
    ).payload())
    expect_refusal(incomplete, lambda: incomplete.operation_request(incomplete_id))

    failed, failed_id, _plan, _raw, _receipt = _legacy_terminal_fixture(
        tmp_path / 'failed', channel='dev', terminal_result='failed',
    )
    assert failed.operation_receipt(failed_id) is not None
    (failed.directory / f'{failed_id}.request.json').unlink()
    (failed.directory / 'dev.request.json').unlink()
    expect_refusal(failed, lambda: failed.operation_receipt(failed_id))

    failed_bootstrap, failed_bootstrap_id, _plan, _raw, _receipt = _legacy_terminal_fixture(
        tmp_path / 'failed-bootstrap', channel='dev', terminal_result='failed',
    )
    for name in (f'{failed_bootstrap_id}.request.json', 'dev.request.json'):
        request = json.loads((failed_bootstrap.directory / name).read_text())
        request['bootstrap'] = True
        (failed_bootstrap.directory / name).write_text(json.dumps(request))
    expect_refusal(failed_bootstrap, lambda: failed_bootstrap.operation_receipt(str(uuid4())))

    conflict, conflict_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'conflict')
    conflicting = json.loads((conflict.directory / 'dev.json').read_text())
    conflicting['stage'] = 'aborted'
    conflicting['terminal_result'] = 'aborted'
    (conflict.directory / 'dev.json').write_text(json.dumps(conflicting))
    expect_refusal(conflict, lambda: conflict.operation_request(conflict_id))

    request_conflict, request_conflict_id, _plan, _raw, _receipt = _legacy_terminal_fixture(
        tmp_path / 'request-conflict',
    )
    conflicting_request = json.loads((request_conflict.directory / 'dev.request.json').read_text())
    conflicting_request['plan']['revision'] = 'c' * 40
    (request_conflict.directory / 'dev.request.json').write_text(json.dumps(conflicting_request))
    expect_refusal(request_conflict, lambda: request_conflict.operation_request(request_conflict_id))

    manual, manual_id, _plan, raw_plan, _receipt = _legacy_terminal_fixture(tmp_path / 'manual')
    manual_plan = {key: raw_plan[key] for key in (
        'channel', 'revision', 'services', 'consumers', 'ack_forward_only',
    )}
    for name in (f'{manual_id}.request.json', 'dev.request.json'):
        request = json.loads((manual.directory / name).read_text())
        request['plan'] = manual_plan
        (manual.directory / name).write_text(json.dumps(request))
    expect_refusal(manual, lambda: manual.operation_receipt(manual_id))
    expect_refusal(manual, lambda: manual.current_request(historical=True))
    expect_refusal(manual, lambda: manual.bound_plan(manual_id, historical=True))

    malformed, malformed_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'malformed')
    malformed_receipt = json.loads((malformed.directory / f'{malformed_id}.receipt.json').read_text())
    malformed_receipt['pg_acceptance']['source_sha'] = 'not-a-sha'
    (malformed.directory / f'{malformed_id}.receipt.json').write_text(json.dumps(malformed_receipt))
    expect_refusal(malformed, lambda: malformed.operation_receipt(malformed_id))

    unknown, unknown_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'unknown-profile')
    for name in (f'{unknown_id}.request.json', 'dev.request.json'):
        request = json.loads((unknown.directory / name).read_text())
        request['plan']['verification_profile'] = {
            'version': 'unknown-profile', 'selection_hash': 'f' * 64,
        }
        unknown._write_json(name, request)
    expect_refusal(unknown, lambda: unknown.operation_request(unknown_id))

    mixed, mixed_id, old_plan, old_raw_plan, old_receipt = _legacy_terminal_fixture(tmp_path / 'mixed-request')
    current_plan = DeployPlan(
        old_plan.channel, old_plan.revision, old_plan.services, old_plan.consumers,
        image_digest=DIGEST, automatic=True,
    )
    current_receipt = DeployReceipt(
        mixed_id, 'dev', 'deploy', 'committed', 'committed',
        pg_acceptance=_result(old_plan.revision, 'dev', mixed_id),
    )
    mixed._write_json(f'{mixed_id}.request.json', {
        'operation_id': mixed_id, 'plan': current_plan.payload(), 'bootstrap': False,
    })
    mixed._write_json(f'{mixed_id}.receipt.json', current_receipt.payload())
    mixed._write_json('dev.request.json', {
        'operation_id': mixed_id, 'plan': old_raw_plan, 'bootstrap': False,
    })
    mixed._write_json('dev.json', old_receipt.payload())
    expect_refusal(mixed, lambda: mixed.operation_request(mixed_id))

    mixed_receipt, mixed_receipt_id, old_plan, old_raw_plan, old_receipt = _legacy_terminal_fixture(
        tmp_path / 'mixed-receipt',
    )
    current_plan = DeployPlan(
        old_plan.channel, old_plan.revision, old_plan.services, old_plan.consumers,
        image_digest=DIGEST, automatic=True,
    )
    mixed_receipt._write_json(f'{mixed_receipt_id}.request.json', {
        'operation_id': mixed_receipt_id, 'plan': current_plan.payload(), 'bootstrap': False,
    })
    mixed_receipt._write_json('dev.request.json', {
        'operation_id': mixed_receipt_id, 'plan': current_plan.payload(), 'bootstrap': False,
    })
    mixed_receipt._write_json(f'{mixed_receipt_id}.receipt.json', DeployReceipt(
        mixed_receipt_id, 'dev', 'deploy', 'committed', 'committed',
        pg_acceptance=_result(old_plan.revision, 'dev', mixed_receipt_id),
    ).payload())
    mixed_receipt._write_json('dev.json', old_receipt.payload())
    expect_refusal(mixed_receipt, lambda: mixed_receipt.operation_receipt(mixed_receipt_id))

    bootstrap, bootstrap_id, _plan, _raw, _receipt = _legacy_terminal_fixture(tmp_path / 'bootstrap')
    retained_request = json.loads((bootstrap.directory / f'{bootstrap_id}.request.json').read_text())
    retained_request['bootstrap'] = True
    (bootstrap.directory / f'{bootstrap_id}.request.json').write_text(json.dumps(retained_request))
    expect_refusal(bootstrap, lambda: bootstrap.operation_request(bootstrap_id))
