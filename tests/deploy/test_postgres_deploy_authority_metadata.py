from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import yaml

from app.ops import postgres_deploy_linux as linux
from app.ops.postgres_deploy import PostgresDeployError
from tests.deploy.test_postgres_deploy_authority_cutover import REPO, request, target as cutover_target


@pytest.fixture
def target(tmp_path, monkeypatch, request):
    # Register locally: an already-collected test module is not a reliable
    # global fixture plugin. Reuse its exact initialized-source fixture body.
    return cutover_target.__wrapped__(tmp_path, monkeypatch, request)


def _prepare(target, monkeypatch, *, admitted=True):
    effects = linux.LinuxEffects(target.cfg)
    monkeypatch.setattr(linux, 'LinuxEffects', lambda _: effects)
    # Keep native validate/select/qualification and the real runtime-UID proof.
    # Only password/DB effects outside metadata admission are fixture boundaries.
    effects.preflight = lambda plan: (effects.select_active_plan(plan), 'fixture-password')[1]
    effects.initialized = lambda: True
    effects.materialize = lambda _: None
    effects.local_database = lambda: False
    effects.authenticate = lambda: None
    effects.quiescent = lambda: True
    # Unblock the fixture's non-daemon thread at teardown without executing
    # the activation runner or any authority-writing effect.
    monkeypatch.setattr(linux.DeployWorker, 'run', lambda *_: None)
    supervisor = linux.DeploymentSupervisor(target.cfg)
    result = supervisor.request(request(target.plan, str(uuid4())))
    if admitted:
        assert result['ready']
    else:
        assert result['receipt']['terminal_result'] == 'aborted'
        assert result['receipt']['stage'] == 'aborted'
        assert target.selected.root not in str(result)
        assert target.selected.ownership_root not in str(result)
    assert not any(call[1] not in {'ps', 'inspect', 'volume'} for call in target.calls)
    supervisor.operation.activation.set()
    supervisor.operation.thread.join(timeout=5)
    assert not supervisor.operation.thread.is_alive()
    return result


def _migration(target):
    # Derive the command/ownership/access shape from the checked-in producer,
    # rather than inventing a content mount just for qualification.
    compose = yaml.safe_load((REPO / 'docker-compose.yaml').read_text())
    service = compose['services']['migrate']
    assert not service.get('volumes')
    assert service['command'] == ['/bin/bash', '/app/scripts/run_migrations.sh']
    script = (REPO / 'scripts/run_migrations.sh').read_text()
    assert 'alembic -c app/alembic.ini upgrade head' in script
    row = {'Id': '4' * 64, 'State': {'Status': 'exited'}, 'Config': {
        'Labels': {**target.rows[0]['Config']['Labels'],
                   'com.docker.compose.service': 'migrate', **service['labels']},
        'Cmd': service['command'], 'Entrypoint': None, 'WorkingDir': service['working_dir'],
        'Env': ['PKM_ENVIRONMENT=test', 'POSTGRES_PASSWORD', 'PGPASSWORD']}, 'Mounts': []}
    target.rows.append(row)
    return row


@pytest.mark.parametrize('stopped', [False, True])
@pytest.mark.parametrize('heimdal', [False, True])
def test_native_prepare_accepts_optional_docker_unsets(target, monkeypatch, stopped, heimdal):
    if heimdal:
        row = deepcopy(target.rows[0])
        row['Id'] = '5' * 64
        row['Config']['Labels']['com.docker.compose.service'] = 'heimdal-capture-watch'
        target.rows.append(row)
        monkeypatch.setattr(linux, '_capture_watch_configured', lambda _: True)
    for row, unsets in zip(target.rows, (3, 2, 2)):
        row['State'] = {'Status': 'exited' if stopped else 'running'}
        row['Config']['Env'] += ['POSTGRES_PASSWORD', 'PGPASSWORD', 'OPTIONAL_PROVIDER'][:unsets]
    if heimdal:
        target.rows[-1]['State'] = {'Status': 'exited' if stopped else 'running'}
        target.rows[-1]['Config']['Env'] += ['POSTGRES_PASSWORD', 'PGPASSWORD']
    _prepare(target, monkeypatch)


@pytest.mark.parametrize('secret_mount', [False, True])
def test_native_prepare_classifies_actual_migration_producer(target, monkeypatch, secret_mount):
    migration = _migration(target)
    if secret_mount:
        migration['Mounts'] = [{'Type': 'bind', 'Destination': '/run/secrets/postgres_password',
                               'Source': str(target.cfg.password_file), 'RW': False}]
    _prepare(target, monkeypatch)


@pytest.mark.parametrize('defect', [
    'duplicate', 'duplicate-unset', 'duplicate-channel', 'invalid-key', 'empty-entry',
    'non-string', 'nul-value', 'env-object', 'missing-root', 'unset-root', 'wrong-root',
    'missing-channel', 'unset-channel', 'wrong-channel', 'wrong-host', 'bare-root-with-fallback',
    'wrong-content', 'duplicate-content', 'wrong-ownership', 'wrong-registry',
    'missing-registry', 'missing-writer', 'stopped-wrong-content', 'heimdal-wrong-content',
    'migration-command', 'migration-entrypoint', 'migration-workdir', 'migration-owner',
    'migration-content', 'migration-hidden-content', 'migration-code', 'migration-rw-secret',
    'migration-foreign-secret', 'migration-duplicate', 'migration-oneoff',
])
def test_native_prepare_refuses_ambiguous_or_wrong_writer_metadata(target, monkeypatch, defect):
    row = target.rows[0]
    env = row['Config']['Env']
    if defect == 'duplicate': env.append('VAULT_ROOT=/app/vault')
    elif defect == 'duplicate-unset': env.extend(['OPTIONAL_PROVIDER', 'OPTIONAL_PROVIDER=value'])
    elif defect == 'duplicate-channel': env.append('PKM_ENVIRONMENT=test')
    elif defect == 'invalid-key': env.append('BAD KEY=value')
    elif defect == 'empty-entry': env.append('')
    elif defect == 'non-string': env.append(None)
    elif defect == 'nul-value': env.append('OPTIONAL_PROVIDER=bad\x00value')
    elif defect == 'env-object': row['Config']['Env'] = {'VAULT_ROOT': '/app/vault'}
    elif defect in {'missing-root', 'unset-root', 'wrong-root'}:
        row['Config']['Env'] = ['PKM_ENVIRONMENT=test']
        if defect == 'unset-root': row['Config']['Env'].append('VAULT_ROOT')
        if defect == 'wrong-root': row['Config']['Env'].append('VAULT_ROOT=/wrong')
    elif defect in {'missing-channel', 'unset-channel', 'wrong-channel'}:
        row['Config']['Env'] = [item for item in env if not item.startswith('PKM_ENVIRONMENT=')]
        if defect == 'unset-channel': row['Config']['Env'].append('PKM_ENVIRONMENT')
        if defect == 'wrong-channel': row['Config']['Env'].append('PKM_ENVIRONMENT=prod')
    elif defect == 'wrong-host': env.append('VAULT_HOST_ROOT=/wrong')
    elif defect == 'bare-root-with-fallback':
        row['Config']['Env'] = ['PKM_ENVIRONMENT=test', 'VAULT_ROOT', 'WATCHER_VAULT_PATH=/app/vault']
    elif defect in {'wrong-content', 'stopped-wrong-content'}:
        row['Mounts'][0]['Source'] = '/wrong'
        row['State'] = {'Status': 'exited'}
    elif defect == 'duplicate-content': row['Mounts'].append(deepcopy(row['Mounts'][0]))
    elif defect == 'wrong-ownership': row['Mounts'][1]['Source'] = '/wrong'
    elif defect == 'wrong-registry': row['Mounts'][2]['Name'] = 'pkm-prod_instance-state'
    elif defect == 'missing-registry': row['Mounts'].pop()
    elif defect == 'missing-writer': target.rows.pop()
    elif defect == 'heimdal-wrong-content':
        row = deepcopy(row)
        row['Id'] = '5' * 64
        row['Config']['Labels']['com.docker.compose.service'] = 'heimdal-capture-watch'
        row['Mounts'][0]['Source'] = '/wrong'
        target.rows.append(row)
        monkeypatch.setattr(linux, '_capture_watch_configured', lambda _: True)
    else:
        row = _migration(target)
        if defect == 'migration-command': row['Config']['Cmd'] = ['/app/scripts/start_api.sh']
        elif defect == 'migration-entrypoint': row['Config']['Entrypoint'] = ['/custom']
        elif defect == 'migration-workdir': row['Config']['WorkingDir'] = '/other'
        elif defect == 'migration-owner': row['Config']['Labels'].pop('com.agentic-pkm.mvr05.db-role')
        elif defect == 'migration-content': row['Mounts'] = deepcopy(target.rows[0]['Mounts'])
        elif defect == 'migration-hidden-content':
            row['Mounts'] = [{'Type': 'bind', 'Destination': '/other', 'Source': target.selected.root}]
        elif defect == 'migration-code':
            row['Mounts'] = [{'Type': 'bind', 'Destination': '/app/scripts', 'Source': '/other'}]
        elif defect in {'migration-rw-secret', 'migration-foreign-secret'}:
            row['Mounts'] = [{'Type': 'bind', 'Destination': '/run/secrets/postgres_password',
                             'Source': str(target.cfg.password_file) if defect == 'migration-rw-secret' else '/foreign',
                             'RW': defect == 'migration-rw-secret'}]
        elif defect == 'migration-duplicate': target.rows.append({**deepcopy(row), 'Id': '6' * 64})
        elif defect == 'migration-oneoff': row['Config']['Labels']['com.docker.compose.oneoff'] = 'True'
    snapshots = {path: path.read_bytes() for directory in (target.registry.path.parent, target.ledger.root)
                 for path in directory.iterdir() if path.is_file()}
    with pytest.raises(PostgresDeployError) as error:
        linux.LinuxEffects(target.cfg).validate_plan(target.plan)
    assert str(error.value) == str(PostgresDeployError())
    _prepare(target, monkeypatch, admitted=False)
    assert all(path.read_bytes() == payload for path, payload in snapshots.items())
    receipt = target.cfg.journal.read()
    assert receipt is None or receipt.stage != 'activating'
