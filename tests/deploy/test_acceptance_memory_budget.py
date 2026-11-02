from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import acceptance_memory, heavy_acceptance, postgres_deploy_linux as linux
from app.ops.acceptance_memory import AcceptanceMemoryError, load_policy
from app.ops.postgres_deploy import DeployPlan, PostgresDeployError
from tests.deploy import test_postmerge_heavy_acceptance as heavy_tests
from tests.deploy import test_postmerge_pg_acceptance as pg_tests


def _policy() -> dict[str, object]:
    return {
        'version': 1,
        'heavy': {'memory': 768 * 1024**2, 'memory_swap': 768 * 1024**2},
        'pg_db': {'memory': 256 * 1024**2, 'memory_swap': 256 * 1024**2},
        'pg_tests': {'memory': 768 * 1024**2, 'memory_swap': 768 * 1024**2},
    }


@pytest.mark.parametrize('channel', ['dev', 'test'])
def test_native_acceptance_containers_enforce_configured_memory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, channel: str,
) -> None:
    assert load_policy(channel, root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3, total_swap=0) is None
    assert capsys.readouterr().err == f'acceptance_memory_policy_unconfigured channel={channel} isolation=inactive\n'
    path = tmp_path / (channel + '.acceptance-memory.json')
    path.write_text(json.dumps(_policy()))
    path.chmod(0o600)
    policy = load_policy(channel, root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3, total_swap=0)
    assert policy is not None
    assert policy.heavy.memory == 768 * 1024**2
    assert policy.pg_db.memory + policy.pg_tests.memory == 1024**3

    heavy_root = tmp_path / 'heavy'
    heavy_root.mkdir()
    output = heavy_acceptance.RESULT_PREFIX + json.dumps(heavy_tests._summary(channel=channel)) + '\n'
    heavy_runner, heavy_docker = heavy_tests._runner(
        heavy_root, monkeypatch, output, channel=channel, memory_limit=policy.heavy,
    )
    assert heavy_runner.verify()['result'] == 'passed'
    assert heavy_docker.created[heavy_docker.created.index('--memory') + 1] == str(policy.heavy.memory)
    assert heavy_docker.created[heavy_docker.created.index('--memory-swap') + 1] == str(policy.heavy.memory_swap)
    assert heavy_docker.container is None

    pg_root = tmp_path / 'pg'
    pg_root.mkdir()
    pg_runner, pg_docker, sha, operation_id = pg_tests._runner(
        pg_root, monkeypatch, channel=channel, memory_policy=policy,
    )
    assert pg_runner.verify()['result'] == 'passed'
    creates = [args for args, _timeout in pg_docker.commands if args[0] == 'create']
    assert len(creates) == 2 and not pg_docker.containers
    for args, limit in zip(creates, (policy.pg_db, policy.pg_tests), strict=True):
        assert args[args.index('--memory') + 1] == str(limit.memory)
        assert args[args.index('--memory-swap') + 1] == str(limit.memory_swap)

    # The real native PG constructor consumes the configured channel policy.
    config = SimpleNamespace(root=pg_runner.repository, channel=channel, journal=SimpleNamespace(directory=pg_root))
    effects = linux.LinuxEffects(config)
    monkeypatch.setattr(acceptance_memory, 'load_policy', lambda selected: policy if selected == channel else None)
    plan = DeployPlan(channel, sha, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=pg_tests.DIGEST, automatic=True)
    assert effects._pg_runner(operation_id, plan).memory_policy == policy

    # The real heavy dispatch reads the same channel policy before calling its runner.
    proof = pg_tests._result(sha, channel, operation_id)
    receipt = SimpleNamespace(operation_id=operation_id, terminal_result='committed', pg_acceptance=proof)
    config.journal = SimpleNamespace(directory=heavy_root, read=lambda: receipt)
    monkeypatch.setattr(linux, 'ensure_candidate_object', lambda *_args: None)
    seen = []
    monkeypatch.setattr(heavy_tests.HeavyAcceptanceRunner, 'verify',
                        lambda self: seen.append(self.memory_limit) or {'result': 'passed'})
    assert linux.qualify_heavy(config, operation_id) == {'result': 'passed'}
    assert seen == [policy.heavy]


def test_memory_failure_is_non_green_and_cleanup_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / 'test.acceptance-memory.json'
    policy = _policy()
    policy['heavy'] = {'memory': 768 * 1024**2, 'memory_swap': -1}
    path.write_text(json.dumps(policy))
    path.chmod(0o600)
    with pytest.raises(AcceptanceMemoryError):
        load_policy('test', root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3, total_swap=0)
    policy = _policy()
    path.write_text(json.dumps(policy))
    valid = load_policy('test', root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3, total_swap=0)
    assert valid is not None

    for fault in ('oom_test', 'oom_db', 'memory_mismatch'):
        root = tmp_path / fault
        root.mkdir()
        runner, docker, _sha, _operation = pg_tests._runner(root, monkeypatch, channel='test', memory_policy=valid)
        docker.fault = fault
        with pytest.raises(pg_tests.profile.PgAcceptanceError):
            runner.verify()
        assert not docker.containers and not runner.directory.exists()
        if fault == 'memory_mismatch':
            assert not any(args[0] == 'start' for args, _timeout in docker.commands)

    for fault in ('oom', 'limit_mismatch'):
        root = tmp_path / fault
        root.mkdir()
        output = heavy_acceptance.RESULT_PREFIX + json.dumps(heavy_tests._summary()) + '\n'
        runner, docker = heavy_tests._runner(root, monkeypatch, output, memory_limit=valid.heavy)
        setattr(docker, fault, True)
        with pytest.raises(heavy_acceptance.HeavyAcceptanceError):
            runner.verify()
        assert docker.container is None and not runner.directory.exists()
        if fault == 'limit_mismatch':
            assert not any(call[1:3] == ['start', '--attach'] for call in docker.calls)

    # A green-looking summary emitted before a later OOM is never enough,
    # including the compatibility path without a configured budget.
    for profile in ('heavy', 'pg_test', 'pg_db'):
        root = tmp_path / ('no_policy_' + profile)
        root.mkdir()
        if profile == 'heavy':
            output = heavy_acceptance.RESULT_PREFIX + json.dumps(heavy_tests._summary()) + '\n'
            runner, docker = heavy_tests._runner(root, monkeypatch, output)
            docker.oom = True
            with pytest.raises(heavy_acceptance.HeavyAcceptanceError):
                runner.verify()
            assert docker.container is None and not runner.directory.exists()
        else:
            runner, docker, _sha, _operation = pg_tests._runner(root, monkeypatch, channel='test')
            docker.fault = 'oom_test' if profile == 'pg_test' else 'oom_db'
            with pytest.raises(pg_tests.profile.PgAcceptanceError):
                runner.verify()
            assert not docker.containers and not runner.directory.exists()

    monkeypatch.setattr(acceptance_memory, 'load_policy', lambda _channel: (_ for _ in ()).throw(AcceptanceMemoryError()))
    config = SimpleNamespace(root=tmp_path, channel='test', journal=SimpleNamespace(directory=tmp_path))
    operation_id = str(uuid4())
    effects = linux.LinuxEffects(config)
    plan = DeployPlan('test', 'a' * 40, ('db', 'api'), ('postgres-db', 'postgres-api'),
                      image_digest=pg_tests.DIGEST, automatic=True)
    with pytest.raises(PostgresDeployError):
        effects._pg_runner(operation_id, plan)
    assert 'acceptance_memory_policy_invalid' in caplog.text

    proof = pg_tests._result('a' * 40, 'test', operation_id)
    config.journal = SimpleNamespace(directory=tmp_path, read=lambda: SimpleNamespace(
        operation_id=operation_id, terminal_result='committed', pg_acceptance=proof,
    ))
    called: list[bool] = []
    monkeypatch.setattr(linux, 'ensure_candidate_object', lambda *_args: called.append(True))
    with pytest.raises(heavy_acceptance.HeavyAcceptanceError, match='acceptance_memory_policy_invalid'):
        linux.qualify_heavy(config, operation_id)
    assert not called


@pytest.mark.parametrize('case', ['symlink', 'mode', 'duplicate', 'bool', 'oversized', 'pg_sum',
                                  'combined_sum', 'swap_sum', 'prod'])
def test_untrusted_or_unbounded_memory_policy_refuses(tmp_path: Path, case: str) -> None:
    path = tmp_path / 'dev.acceptance-memory.json'
    policy = _policy()
    if case == 'bool':
        policy['heavy'] = {'memory': True, 'memory_swap': 768 * 1024**2}
    if case == 'oversized':
        policy['heavy'] = {'memory': 3 * 1024**3, 'memory_swap': 3 * 1024**3}
    if case == 'pg_sum':
        policy['pg_tests'] = {'memory': 2 * 1024**3, 'memory_swap': 2 * 1024**3}
    if case == 'combined_sum':
        policy['heavy'] = {'memory': 1536 * 1024**2, 'memory_swap': 1536 * 1024**2}
    if case == 'swap_sum':
        policy['heavy'] = {'memory': 768 * 1024**2, 'memory_swap': 769 * 1024**2}
    path.write_text(json.dumps(policy))
    path.chmod(0o600)
    if case == 'mode':
        path.chmod(0o644)
    if case == 'duplicate':
        path.write_text('{"version":1,"version":1}')
    if case == 'symlink':
        path.unlink()
        path.symlink_to(tmp_path / 'missing')
    channel = 'prod' if case == 'prod' else 'dev'
    with pytest.raises(AcceptanceMemoryError):
        load_policy(channel, root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3, total_swap=0)


def test_configured_swap_budget_uses_measured_host_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'dev.acceptance-memory.json'
    data = _policy()
    data['heavy'] = {'memory': 768 * 1024**2, 'memory_swap': 1024 * 1024**2}
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    monkeypatch.setattr(acceptance_memory.Path, 'read_text', lambda *_args, **_kwargs: 'SwapTotal: 262144 kB\n')
    assert load_policy('dev', root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3) is not None
    monkeypatch.setattr(acceptance_memory.Path, 'read_text', lambda *_args, **_kwargs: 'SwapTotal: 0 kB\n')
    with pytest.raises(AcceptanceMemoryError):
        load_policy('dev', root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3)
    monkeypatch.setattr(acceptance_memory.Path, 'read_text', lambda *_args, **_kwargs: 'MemTotal: 123 kB\n')
    with pytest.raises(AcceptanceMemoryError):
        load_policy('dev', root=tmp_path, expected_uid=os.getuid(), total_memory=2 * 1024**3)
