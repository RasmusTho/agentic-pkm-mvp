"""Public fixtures at subprocess I/O; the canonical acquisition owner stays real."""
from __future__ import annotations

from dataclasses import replace
import json
import subprocess
from types import SimpleNamespace

import pytest

from app.ops import postgres_deploy_linux as linux
from app.ops.pg_acceptance import IMAGE_REPOSITORY
from app.ops.postgres_deploy import AuthorityCutover, DeployPlan, PostgresDeployError


REVISION = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64
GENERIC = 'database deployment refused; matching terminal evidence required'
PUBLIC_ERRORS = (
    ('unauthorized: authentication required', 'registry_unauthorized'),
    ('denied: requested access to the resource is denied', 'registry_denied'),
    ('manifest unknown: manifest unknown', 'registry_manifest_unknown'),
    ('toomanyrequests: too many requests', 'registry_rate_limited'),
)
CANARY = 'private-canary /private/source token=secret-value https://private.invalid'


def _owner(tmp_path, monkeypatch, channel='dev', database='db'):
    # Only subprocess I/O is substituted. Even public-source protocol, candidate,
    # environment and image qualification execute their production implementations.
    for key in (
        'DATABASE_URL', 'DB_DSN', 'POSTGRES_PASSWORD', 'PGPASSWORD', 'PGPASSFILE',
        'PGSERVICE', 'PGSERVICEFILE', 'DOCKER_HOST', 'DOCKER_CONTEXT',
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('BWS_ACCESS_TOKEN', 'ambient-token-must-not-reach-child')
    monkeypatch.setenv('OPTIONAL_PROVIDER', 'ambient-value-must-not-reach-child')
    monkeypatch.setenv('APP_IMAGE_TAG', 'ambient-image-must-not-win')
    monkeypatch.setenv('COMPOSE_PROFILES', 'db')
    runtime = tmp_path / 'runtime.env'
    runtime.write_text('')
    cfg = SimpleNamespace(
        channel=channel, root=tmp_path, runtime_env_file=runtime,
        uid=1000, gid=1001, password_file=tmp_path / 'password',
    )
    effects = linux.LinuxEffects(cfg)
    selected = AuthorityCutover('public-fixture', '/srv/public-fixture', '/srv/public-ownership')
    plan = DeployPlan(
        channel, REVISION, ('db', 'api', 'worker', 'watcher'),
        ('postgres-db', 'postgres-api', 'postgres-worker', 'postgres-watcher', 'heimdal-api-ingress'),
        image_digest=DIGEST, authority_cutover=selected,
    )
    snapshot = linux.SourceIdentityRuntimeSnapshot(
        'c' * 64, 'd' * 64, ('api', 'worker', 'watcher'), ('api', 'worker', 'watcher'),
        selected.root, 'docker-compose.full-host-vault.yml',
        (
            ('DATABASE_URL', 'postgresql+psycopg:///?host=' + database),
            ('EMBED_PROVIDER', 'public-fixture-provider'), ('EMBED_MODEL', 'public-fixture-model'),
            ('STORE_BACKEND', 'pg'), ('PKM_ENVIRONMENT', channel),
        ),
        ('OPTIONAL_PROVIDER',),
    )
    image = [{
        'Config': {'Labels': {'org.opencontainers.image.revision': REVISION}, 'Env': []},
        'RepoDigests': [IMAGE_REPOSITORY + '@' + DIGEST],
    }]
    result = SimpleNamespace(returncode=1, stdout='', stderr='')
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == 'git' and 'cat-file' in argv:
            assert argv[-1] == REVISION + '^{commit}'
            return subprocess.CompletedProcess(argv, 0, b'', b'')
        if argv[0] == 'git' and 'show' in argv:
            assert argv[-1] == REVISION + ':app/config/database.py'
            return subprocess.CompletedProcess(argv, 0, 'DATABASE_FILE_CREDENTIAL_PROTOCOL = 1\n', '')
        if argv[:2] == ['docker', 'compose']:
            assert argv[-2:] == ['pull', 'api']
            return result
        if argv[:5] == ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect']:
            assert argv[-1] == IMAGE_REPOSITORY + '@' + DIGEST
            assert kwargs['env'] == {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
            return subprocess.CompletedProcess(argv, 0, json.dumps(image), '')
        pytest.fail('unexpected external effect')

    monkeypatch.setattr(linux.subprocess, 'run', run)
    return effects, selected, plan, snapshot, result, calls, image


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize(('message', 'expected'), PUBLIC_ERRORS)
@pytest.mark.parametrize('progress', [False, True])
def test_canonical_helper_pull_preserves_fixed_failure_class(
    tmp_path, monkeypatch, channel, message, expected, progress,
):
    effects, selected, plan, snapshot, result, calls, _image = _owner(tmp_path, monkeypatch, channel)
    result.stderr = (
        (' api Pulling\n api Error ' + message + '\n') if progress else ''
    ) + 'Error response from daemon: ' + message + '\n'
    with pytest.raises(PostgresDeployError) as raised:
        effects.require_source_identity_candidate(plan, selected, acquire=True, source_snapshot=snapshot)
    assert len(calls) == 3  # source existence, source protocol, failed pull; no image/writer work
    assert raised.value.image_pull_failure == expected
    assert str(raised.value) == GENERIC
    assert vars(raised.value) == {'image_pull_failure': expected}
    assert calls[-1][1]['errors'] == 'replace'


@pytest.mark.parametrize(('stdout', 'stderr'), [
    ('', CANARY),
    (CANARY, 'Error response from daemon: unauthorized: authentication required\n'),
    ('', 'Error response from daemon: unauthorized: authentication required ' + CANARY),
    ('', 'Error response from daemon: unauthorized: authentication required\n' + CANARY),
    ('', 'Error response from daemon: unauthorized: authentication required\n'
         'Error response from daemon: denied: requested access to the resource is denied\n'),
    ('', ' api Error denied: requested access to the resource is denied\n'
         'Error response from daemon: unauthorized: authentication required\n'),
    ('', 'Error response from daemon: unauthorized: authentication required\n' * 2),
    ('', 'Error response from daemon: unknown: private-shape\n'),
    ('', 'unauthorized: authentication required'),
    ('', 'Error response from daemon: unauthorized: authentication required\x00'),
    ('', 'Error response from daemon: unauthorized: authentication required\ufffd'),
    ('', '\x1b[31mError response from daemon: unauthorized: authentication required\n'),
    ('', 'Error response from daemon: unauthorized: authentication required\n' + 'x' * 16384),
    ('x' * 16385, 'Error response from daemon: unauthorized: authentication required\n'),
    ('', None),
    ('', b'Error response from daemon: unauthorized: authentication required\n'),
    ('', ''),
], ids=[str(index) for index in range(17)])
def test_canonical_helper_pull_failure_is_bounded_and_private(tmp_path, monkeypatch, capsys, stdout, stderr):
    effects, selected, plan, snapshot, result, calls, _image = _owner(tmp_path, monkeypatch)
    result.stdout, result.stderr = stdout, stderr
    with pytest.raises(PostgresDeployError) as raised:
        effects.require_source_identity_candidate(plan, selected, acquire=True, source_snapshot=snapshot)
    assert raised.value.image_pull_failure == 'unclassified'
    assert vars(raised.value) == {'image_pull_failure': 'unclassified'}
    assert raised.value.args == (GENERIC,)
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    assert CANARY not in repr(raised.value)
    assert capsys.readouterr() == ('', '')
    assert len(calls) == 3


@pytest.mark.parametrize('channel', ['dev', 'test'])
@pytest.mark.parametrize('database', ['db', 'postgres.invalid'])
@pytest.mark.parametrize('acquire', [False, True])
def test_canonical_helper_failure_preserves_owner_ordering_and_compatibility(
    tmp_path, monkeypatch, channel, database, acquire,
):
    effects, selected, plan, snapshot, result, calls, image = _owner(
        tmp_path, monkeypatch, channel, database,
    )
    result.stderr = 'Error response from daemon: unauthorized: authentication required\n'
    if acquire:
        with pytest.raises(PostgresDeployError) as failed:
            effects.require_source_identity_candidate(plan, selected, acquire=True, source_snapshot=snapshot)
        assert failed.value.image_pull_failure == 'registry_unauthorized'
        argv, kwargs = calls[-1]
        expected_files = [
            'docker-compose.yaml', 'docker-compose.' + channel + '.yml', 'docker-compose.bws.yml',
            *(['docker-compose.bws-external.yml'] if database != 'db' else []),
            'docker-compose.full-host-vault.yml',
            *(['docker-compose.test-vault.yml'] if channel == 'test' else []),
        ]
        assert [argv[i + 1] for i, arg in enumerate(argv) if arg == '-f'] == [
            str(tmp_path / name) for name in expected_files
        ]
        assert argv[:4] == ['docker', 'compose', '--env-file', str(tmp_path / 'config/deploy' / (channel + '.env'))]
        assert argv[-4:] == ['-p', 'pkm-' + channel, 'pull', 'api']
        assert kwargs['cwd'] == tmp_path and kwargs['timeout'] == 1800
        env = kwargs['env']
        assert env['APP_IMAGE_TAG'] == REVISION and env['APP_IMAGE_DIGEST_SUFFIX'] == '@' + DIGEST
        assert env['VAULT_HOST_ROOT'] == env['DEPLOY_VAULT_CONTAINER_ROOT'] == selected.root
        assert env['INSTANCE_OWNERSHIP_HOST_STATE_DIR'] == selected.ownership_root
        assert env['EMBED_PROVIDER'] == 'public-fixture-provider' and env['EMBED_MODEL'] == 'public-fixture-model'
        assert env['LOCAL_UID'] == '1000' and env['LOCAL_GID'] == '1001'
        assert 'OPTIONAL_PROVIDER' not in env and 'BWS_ACCESS_TOKEN' not in env
        if database != 'db':
            assert env['COMPOSE_PROFILES'] == ''
        # An unrelated Compose caller retains its ordinary generic refusal.
        with pytest.raises(PostgresDeployError) as unrelated:
            effects.compose('pull', 'api', cutover=selected, candidate=plan, source_snapshot=snapshot)
        assert unrelated.value.image_pull_failure is None
        assert calls[-1][1]['errors'] == 'strict'

    result.returncode = 0
    calls.clear()
    effects.require_source_identity_candidate(plan, selected, acquire=acquire, source_snapshot=snapshot)
    assert len(calls) == (4 if acquire else 3)
    assert calls[-1][0][:5] == ['docker', '--host', 'unix:///var/run/docker.sock', 'image', 'inspect']
    for invalid_image in (
        [{**image[0], 'RepoDigests': [IMAGE_REPOSITORY + '@sha256:' + 'e' * 64]}],
        [{**image[0], 'Config': {'Labels': {'org.opencontainers.image.revision': 'e' * 40}, 'Env': []}}],
        [{**image[0], 'Config': {**image[0]['Config'], 'Env': ['OPTIONAL_PROVIDER=image-default']}}],
    ):
        image[:] = invalid_image
        with pytest.raises(PostgresDeployError) as invalid:
            effects.require_source_identity_candidate(plan, selected, acquire=acquire, source_snapshot=snapshot)
        assert invalid.value.image_pull_failure is None
    calls.clear()
    with pytest.raises(PostgresDeployError):
        effects.require_source_identity_candidate(
            replace(plan, image_digest=None), selected, acquire=acquire, source_snapshot=snapshot,
        )
    assert calls == []
