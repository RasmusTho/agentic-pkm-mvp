from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import postmerge_dev_test as driver


CANARY = 'persistent-private-secret-canary'


def _native_chains(tmp_path, monkeypatch, *, run_ids=(123,)):
    """Exercise driver, native worker and real PG runner; fake only transports."""
    from app.ops.pg_acceptance_runner import PgAcceptanceRunner
    from app.ops import postgres_deploy_linux as linux
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, DeployWorker
    from tests.deploy.test_postmerge_pg_acceptance import DIGEST, DockerBoundary, _repository

    repository, sha = _repository(tmp_path)
    actual_run = driver.subprocess.run
    records, outcomes, native_envs, docker_envs = [], [], [], []
    active = []

    def transport(argv, **options):
        if argv[0] == 'docker':
            docker_envs.append(options['env'])
            data = active[0].command(*argv[1:], timeout=options.get('timeout', 60))
            return SimpleNamespace(returncode=0, stdout=data)
        if argv[1:3] != ['-m', 'app.ops.postgres_deploy_host']:
            return actual_run(argv, **options)
        native_envs.append(options['env'])
        channel, revision = argv[3:5]
        operation_id = argv[argv.index('--operation-id') + 1]
        digest = argv[argv.index('--image-digest') + 1]
        assert '--existing-secrets-only' in argv and '--automatic' in argv
        assert channel in {'dev', 'test'} and revision == sha and digest == DIGEST
        journal = DeployJournal(tmp_path / 'journals' / operation_id, channel)
        runner = PgAcceptanceRunner(repository, journal.directory, sha=revision,
                                    digest=digest, channel=channel, operation_id=operation_id)
        boundary = DockerBoundary(runner)
        active[:] = [boundary]
        effects = linux.LinuxEffects(SimpleNamespace(root=repository, channel=channel, journal=journal))
        effects.lock_fd = 123
        effects.operation_id = operation_id
        plan = DeployPlan(channel, revision, ('db', 'api'), ('postgres-db', 'postgres-api'),
                          image_digest=digest, automatic=True)
        journal.bind_request(operation_id, plan, False, create=True)
        monkeypatch.setattr(effects, 'preflight', lambda _plan: CANARY)
        monkeypatch.setattr(effects, 'initialized', lambda: False)
        monkeypatch.setattr(effects, 'materialize', lambda _password: None)
        monkeypatch.setattr(effects, 'activate', lambda _plan: None)
        monkeypatch.setattr(effects, 'quiescent', lambda: True)
        monkeypatch.setattr(effects, '_pg_runner', lambda _identifier, _plan: runner)
        receipt = DeployWorker(journal, effects).run(operation_id, plan)
        records.append((runner, boundary, receipt))
        return SimpleNamespace(returncode=0 if receipt.terminal_result == 'committed' else 78,
                               stdout=json.dumps(receipt.payload()))

    monkeypatch.setattr(driver.subprocess, 'run', transport)
    for run_id in run_ids:
        candidate = driver.Candidate(sha, DIGEST, run_id, 1, 456)
        assert driver.deliver(candidate, deploy=driver.native_deploy,
                              current_main=lambda: sha, emit=outcomes.append) == 0
    return records, outcomes, native_envs, docker_envs


def test_pg_acceptance_isolated_per_channel_and_run(tmp_path, monkeypatch):
    records, outcomes, _native_envs, _docker_envs = _native_chains(
        tmp_path, monkeypatch, run_ids=(123, 124))
    assert [receipt.channel for _runner, _boundary, receipt in records] == ['dev', 'test', 'dev', 'test']
    assert len({receipt.operation_id for _runner, _boundary, receipt in records}) == 4
    assert len({runner.name for runner, _boundary, _receipt in records}) == 4
    assert len({runner.directory for runner, _boundary, _receipt in records}) == 4
    proofs = [receipt.pg_acceptance for _runner, _boundary, receipt in records]
    assert all(proof['result'] == 'passed' for proof in proofs)
    assert len({(proof['source_sha'], proof['image_digest'], proof['selection_hash'],
                 proof['resource_tree'], proof['app_image_id']) for proof in proofs}) == 1
    for runner, boundary, receipt in records:
        assert receipt.terminal_result == 'committed'
        assert not runner.directory.exists() and not boundary.containers
        creates = [args for args, _timeout in boundary.commands if args[0] == 'create']
        database = next(args for args in creates if args[args.index('--name') + 1].endswith('-db'))
        tests = next(args for args in creates if args[args.index('--name') + 1].endswith('-tests'))
        assert database[database.index('--network') + 1] == 'none'
        assert tests[tests.index('--network') + 1].startswith('container:')
        assert '--publish' not in database and '--read-only' in tests
    assert [row['channel'] for row in outcomes if row['result'] == 'passed'] == ['dev', 'test', 'dev', 'test']


def test_candidate_tests_cannot_read_deployment_credentials(tmp_path, monkeypatch):
    for key in ('DATABASE_URL', 'DB_DSN', 'VAULT_ROOT', 'BWS_ACCESS_TOKEN', 'GH_TOKEN',
                'GITHUB_TOKEN', 'DOCKER_HOST', 'HOST_SECRET_RUNTIME_ENV_FILE'):
        monkeypatch.setenv(key, CANARY)
    records, outcomes, native_envs, docker_envs = _native_chains(tmp_path, monkeypatch)
    assert all('GH_TOKEN' not in env and 'GITHUB_TOKEN' not in env for env in native_envs)
    assert docker_envs and CANARY not in json.dumps(docker_envs)
    for runner, boundary, receipt in records:
        tests = next(args for args, _timeout in boundary.commands
                     if args[0] == 'create' and args[args.index('--name') + 1].endswith('-tests'))
        assert '/usr/bin/env' in tests and '-i' in tests
        assert 'VAULT_ROOT=/scratch/vault' in tests
        mounts = [tests[i + 1] for i, value in enumerate(tests) if value == '--mount']
        assert all(str(runner.directory) in mount and mount.endswith('readonly') for mount in mounts)
        assert all('docker.sock' not in mount and '/app/app' not in mount for mount in mounts)
        assert CANARY not in json.dumps(boundary.commands)
        assert CANARY not in json.dumps(receipt.payload())
    assert CANARY not in json.dumps(outcomes)


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_pg_failure_after_forward_only_activation_retains_compatible_target(
    tmp_path, monkeypatch, channel,
):
    from app.ops import postgres_deploy_linux as linux
    from app.ops.host_secret_contract import DATABASE_CONSUMERS
    from app.ops.pg_acceptance import PgAcceptanceError
    from app.ops.postgres_deploy import DeployJournal, DeployPlan, DeployWorker, PostgresDeployError
    from tests.deploy.test_deploy_channel import (
        _deploy_events, _forward_only_nonprod_harness, _run_deploy,
    )

    root, env, previous_sha, target_sha = _forward_only_nonprod_harness(tmp_path, channel)
    digest = 'sha256:' + 'b' * 64
    candidate = driver.Candidate(target_sha, digest, 321, 1, 456)
    operation_id = candidate.operation_id(channel)
    journal = DeployJournal(tmp_path / 'journal', channel)
    source_directory = tmp_path / 'secret-handles'
    source_directory.mkdir()
    effects = linux.LinuxEffects(SimpleNamespace(
        root=root, channel=channel, journal=journal, source_directory=source_directory,
    ))
    effects.lock_fd = 123
    effects.operation_id = operation_id
    effects.active_consumers = tuple(DATABASE_CONSUMERS)
    plan = DeployPlan(channel, target_sha, tuple(DATABASE_CONSUMERS.values()),
                      tuple(DATABASE_CONSUMERS), image_digest=digest, automatic=True)
    journal.bind_request(operation_id, plan, False, create=True)
    monkeypatch.setattr(effects, 'preflight', lambda _plan: CANARY)
    monkeypatch.setattr(effects, 'initialized', lambda: False)
    monkeypatch.setattr(effects, 'materialize', lambda _password: None)
    monkeypatch.setattr(effects, 'environment', lambda: dict(env))
    monkeypatch.setattr(effects.source, 'verify', lambda: None)
    monkeypatch.setattr(effects, 'quiescent', lambda: True)

    def shell_transport(argv, **options):
        assert argv == [
            'bash', str(root / 'scripts/deploy_channel.sh'), 'deploy', channel, target_sha,
            '--image-digest', digest, '--automatic',
        ]
        assert options['cwd'] == root and options['pass_fds'] == (123,)
        assert options['env']['BWS_DEPLOY_OPERATION_ID'] == operation_id
        result = _run_deploy(root, env, target_sha, '--automatic', '--image-digest',
                            digest, channel=channel)
        if result.returncode:
            raise PostgresDeployError(result.stdout + result.stderr)
        return result.stdout

    monkeypatch.setattr(linux, '_command', shell_transport)
    activation_events, cleanup_calls = [], []

    class FailedProfile:
        def verify(self):
            assert journal.read().stage == 'verifying'
            deployment = json.loads((root / 'ops/deployments' / (channel + '-latest.json')).read_text())
            assert deployment['migration_receipt']['forward_only'] == ['forward_only_nonprod.py']
            assert deployment['migration_receipt']['ack_forward_only'] is False
            assert deployment['image_digest'] == digest and deployment['automatic'] is True
            assert deployment['image'].endswith(':' + target_sha + '@' + digest)
            activation_events[:] = _deploy_events(env)
            raise PgAcceptanceError('injected candidate PG failure after activation')

        def cleanup(self):
            cleanup_calls.append(operation_id)

    monkeypatch.setattr(effects, '_pg_runner', lambda _identifier, _plan: FailedProfile())
    receipt = DeployWorker(journal, effects).run(operation_id, plan)
    assert receipt.terminal_result == 'failed' and receipt.pg_acceptance is None
    assert journal.read().payload() == receipt.payload()
    assert cleanup_calls == [operation_id]
    assert activation_events and _deploy_events(env) == activation_events
    assert f'APP_IMAGE_TAG={target_sha}' in (root / 'config/deploy' / (channel + '.env')).read_text()
    assert 'APP_IMAGE_DIGEST_SUFFIX=@' + digest in (root / 'config/deploy' / (channel + '.env')).read_text()
    assert f'APP_IMAGE_TAG={previous_sha}' in (root / 'config/deploy' / (channel + '.previous.env')).read_text()
    assert not (root / 'config/deploy' / (channel + '.migration-pending.env')).exists()
    assert not list(source_directory.iterdir())
    calls, outcomes = [], []

    def deploy(requested_channel, requested_candidate):
        assert requested_candidate == candidate
        calls.append(requested_channel)
        return receipt.payload()

    channels = ('dev', 'test') if channel == 'dev' else ('test',)
    assert driver.deliver(candidate, deploy=deploy, current_main=lambda: target_sha,
                          emit=outcomes.append, channels=channels) == 78
    assert calls == [channel] and not any(row['result'] == 'passed' for row in outcomes)
