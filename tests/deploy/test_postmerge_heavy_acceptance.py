from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from app.ops import heavy_acceptance as heavy
from app.ops import heavy_acceptance_runner as runner_module
from app.ops import postgres_deploy_linux as linux
from app.ops.heavy_acceptance_runner import HeavyAcceptanceRunner

SHA = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
OPERATION = str(uuid4())
ROOT = Path(__file__).resolve().parents[2]
SELECTOR_NAME = 'select_pr_tests' + '.py'


def _summary(**overrides):
    summary = {**heavy.identity(SHA, DIGEST, 'test', OPERATION), 'targets': ['tests/deploy'], 'exit_status': 0,
               'failures': [], 'report_hash': '0' * 64, 'selected': 500, 'passed': 490, 'failed': 0,
               'skipped': 10, 'docker_skipped': 0}
    return {**summary, **overrides}


def _expected():
    return heavy.identity(SHA, DIGEST, 'test', OPERATION)


def test_heavy_profile_refuses_failure_timeout_and_docker_skip(tmp_path):
    assert heavy.classify(_summary(), _expected())['result'] == 'passed'
    # A test failure, a pytest-timeout watchdog kill (reported as a failure),
    # a docker-gated skip, a nonzero session or an empty run are never a pass.
    for overrides in ({'failed': 1, 'failures': ['tests/deploy/test_a.py::test_slow']},
                      {'exit_status': 1}, {'docker_skipped': 3}, {'selected': 0, 'passed': 0}):
        assert heavy.classify(_summary(**overrides), _expected())['result'] == 'failed', overrides
    # Foreign identity, missing fields or unbounded evidence are refused.
    for broken in (_summary(source_sha='c' * 40), {k: v for k, v in _summary().items() if k != 'targets'},
                   _summary(targets=[]), _summary(failures=['x\ny']), _summary(failures=['t'] * 21),
                   _summary(passed=-1)):
        with pytest.raises(heavy.HeavyAcceptanceError):
            heavy.classify(broken, _expected())

    # In-container entrypoint: the exact tree's own selector, PR marker and
    # the 120 s thread watchdog; a docker-gated skip is counted.
    work = tmp_path / 'work'
    # Path pieces, not repo-relative literals: the heavy-trigger census reads
    # string literals in tests/deploy as repo files this suite depends on.
    (work / 'scripts').mkdir(parents=True)
    (work / 'tests' / 'heavy').mkdir(parents=True)
    (work / 'scripts' / SELECTOR_NAME).write_text(
        "HEAVY_PR_DEFERRED_TARGETS = {'tests/heavy': ()}\nPR_MARKER_EXPRESSION = 'not pg'\n")
    (work / 'tox.ini').write_text('[pytest]\nmarkers =\n    pg: pg\n')
    (work / 'tests' / 'heavy' / 'test_sample.py').write_text(
        'import pytest\n'
        'def test_ok():\n    pass\n'
        '@pytest.mark.pg\ndef test_pg_is_deselected():\n    raise AssertionError()\n'
        '@pytest.mark.skipif(True, reason="docker executable not found on PATH")\n'
        'def test_compose():\n    pass\n')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(_expected()))
    result = subprocess.run(
        [sys.executable, '-c', 'import sys; from app.ops.heavy_acceptance import main; '
         f'sys.path.insert(0, {str(work)!r}); raise SystemExit(main(["--manifest", {str(manifest)!r}]))'],
        cwd=work, capture_output=True, text=True, timeout=120,
        env={**os.environ, 'PYTHONPATH': str(ROOT), 'PYTEST_ADDOPTS': ''},
    )
    line = next(row for row in result.stdout.splitlines() if row.startswith(heavy.RESULT_PREFIX))
    summary = json.loads(line[len(heavy.RESULT_PREFIX):])
    assert result.returncode == 0, result.stdout + result.stderr
    assert summary['targets'] == ['tests/heavy']
    assert (summary['selected'], summary['passed'], summary['skipped'], summary['docker_skipped']) == (2, 1, 1, 1)
    assert heavy.classify(summary, _expected())['result'] == 'failed'


class _FakeDocker:
    """Records the trusted worker's Docker/Git calls for one disposable run."""

    def __init__(self, repository: Path, output: str):
        self.calls: list[list[str]] = []
        self.output = output
        self.container = None
        self.created: list[str] = []
        self.repository = repository

    def __call__(self, argv, *, timeout=60):
        self.calls.append(argv)
        if argv[0] == 'git':
            command, where = argv[5:], Path(argv[4])
            if command[:1] == ['rev-parse']:
                return (SHA if command[1] in {SHA + '^{commit}', 'HEAD'} else 'e' * 40).encode() + b'\n'
            if command[:1] == ['fetch']:
                assert command[-2:] == ['file://' + str(self.repository), SHA] and '--depth' in command
                return b''
            if command[:1] == ['checkout']:
                (where / 'scripts').mkdir()
                (where / 'scripts' / SELECTOR_NAME).write_text('x = 1\n')
                return b''
            if command[:1] in (['init'], ['status']):
                return b''
        command = argv[1:]
        if command[:2] == ['image', 'inspect']:
            return json.dumps([{'Id': 'sha256:' + 'f' * 64, 'RepoDigests': [heavy_image_digest()],
                                'Config': {'Labels': {'org.opencontainers.image.revision': SHA}}}]).encode()
        if command[:2] == ['container', 'ls']:
            return (self.container or '').encode()
        if command[:1] == ['create']:
            self.created = command
            self.container = 'c' * 64
            return self.container.encode() + b'\n'
        if command[:1] == ['inspect']:
            labels = {}
            for index, value in enumerate(self.created):
                if value == '--label':
                    key, _, item = self.created[index + 1].partition('=')
                    labels[key] = item
            mounts = [{'Type': 'bind', 'Source': self.created[i + 1].split(',')[1].removeprefix('src=')}
                      for i, value in enumerate(self.created) if value == '--mount']
            return json.dumps([{'Id': self.container, 'Name': '/' + self.created[2], 'Image': 'sha256:' + 'f' * 64,
                                'Config': {'Labels': labels}, 'Mounts': mounts,
                                'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'CapDrop': ['ALL']}}]
                              ).encode()
        if command[:2] == ['start', '--attach']:
            return self.output.encode()
        if command[:1] == ['rm']:
            self.container = None
            return b''
        raise AssertionError(argv)


def heavy_image_digest():
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    return IMAGE_REPOSITORY + '@' + DIGEST


def _runner(tmp_path, monkeypatch, output):
    journal = tmp_path / 'journal'
    journal.mkdir(mode=0o700)
    fake = _FakeDocker(tmp_path / 'repo', output)
    monkeypatch.setattr(runner_module, '_command', fake)
    docker = tmp_path / 'docker'
    compose = tmp_path / 'docker-compose'
    for path in (docker, compose):
        path.write_text('')
    monkeypatch.setattr(runner_module, 'host_docker_cli', lambda: (docker, compose))
    return HeavyAcceptanceRunner(tmp_path / 'repo', journal, sha=SHA, digest=DIGEST, channel='test',
                                 operation_id=OPERATION), fake


def test_runner_isolates_candidate_and_cleans_owned_resources(tmp_path, monkeypatch):
    output = 'pytest noise\n' + heavy.RESULT_PREFIX + json.dumps(_summary()) + '\n'
    runner, fake = _runner(tmp_path, monkeypatch, output)
    result = runner.verify()
    assert result['result'] == 'passed' and result['selected'] == 500
    create = fake.created
    for flag in (['--network', 'none'], ['--cap-drop', 'ALL'], ['--security-opt', 'no-new-privileges']):
        index = create.index(flag[0])
        assert create[index:index + 2] == flag
    assert '--read-only' in create
    mounts = [create[i + 1] for i, value in enumerate(create) if value == '--mount']
    assert any(m.endswith(f'dst={runner_module.CONTAINER_DOCKER},readonly') for m in mounts)
    assert any(m.endswith(f'dst={runner_module.CONTAINER_COMPOSE},readonly') for m in mounts)
    assert not any('docker.sock' in m for m in mounts)
    assert create[-3:] == ['app.ops.heavy_acceptance', '--manifest', '/heavy-manifest.json']
    # Exact owned container and work tree are gone after the run.
    assert fake.container is None and not runner.directory.exists()


@pytest.mark.parametrize('output', ['', heavy.RESULT_PREFIX + 'refused\n',
                                    heavy.RESULT_PREFIX + json.dumps(_summary(operation_id=str(uuid4()))) + '\n'])
def test_runner_refuses_missing_or_foreign_evidence(tmp_path, monkeypatch, output):
    runner, fake = _runner(tmp_path, monkeypatch, output)
    with pytest.raises(heavy.HeavyAcceptanceError):
        runner.verify()
    assert fake.container is None and not runner.directory.exists()


def test_qualify_heavy_is_fixed_dev_test_and_refuses_uncommitted(monkeypatch, capsys):
    assert linux.main(['qualify-heavy', 'prod', OPERATION]) == 78
    assert json.loads(capsys.readouterr().out) == {
        'profile_version': heavy.PROFILE_VERSION, 'result': 'refused', 'reason': 'fixed_dev_test_invocation_required'}

    class Journal:
        directory = Path('/nonexistent')

        @staticmethod
        def read():
            return None

    monkeypatch.setattr(linux.LinuxConfig, 'load', classmethod(
        lambda cls, channel, **_kw: type('Config', (), {'channel': channel, 'journal': Journal})()))
    assert linux.main(['qualify-heavy', 'test', OPERATION]) == 78
    assert json.loads(capsys.readouterr().out)['reason'] == 'expected_committed_native_operation_required'


def test_launcher_admits_qualify_heavy(monkeypatch):
    # The installed launcher is a fixed action/arity allowlist; the controller's
    # exact `qualify-heavy <channel> <operation-id>` call must pass it and reach
    # the root-owned channel configuration read.
    import importlib.util

    spec = importlib.util.spec_from_file_location('launcher', ROOT / 'scripts' / 'postgres_deploy_service.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    opened = []

    def refuse(path, *_args, **_kwargs):
        opened.append(str(path))
        raise PermissionError()

    monkeypatch.setattr(launcher.os, 'open', refuse)
    for argv, admitted in ((['qualify-heavy', 'dev', OPERATION], True), (['qualify-heavy', 'test', OPERATION], True),
                           (['qualify-heavy', 'dev'], False), (['qualify-heavy', 'stage', OPERATION], False),
                           (['qualify-anything', 'dev', OPERATION], False)):
        opened.clear()
        monkeypatch.setattr(launcher.sys, 'argv', ['yggdrasil-bws-deploy', *argv])
        assert launcher.run() == 78  # the config read is refused in this sandbox either way
        assert bool(opened) is admitted, argv
