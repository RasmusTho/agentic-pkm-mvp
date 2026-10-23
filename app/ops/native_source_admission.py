"""Current observations inside the existing source-operation ownership boundary.

This module neither recovers historical ownership nor starts application services.
Private fingerprints bind complete installed/current Compose observations; public
results remain the existing diagnostic or ordinary-producer aggregate receipts.
"""
from __future__ import annotations

from functools import partial
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, TYPE_CHECKING
from uuid import UUID

from app.ops.postgres_deploy import AuthorityCutover, PostgresDeployError

if TYPE_CHECKING:
    from app.ops.postgres_deploy_linux import LinuxEffects, SourceIdentityRuntimeSnapshot


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def strict_census(
    rows: Any, *, ids: list[str], compose: Any, channel: str,
    transitioning_writers: tuple[str, ...],
) -> tuple[str, str]:
    """Classify every effective service and every installed container, closed-world."""
    from app.instance.mvr05_cutover import _service_role
    from app.ops.postgres_deploy_linux import _canonical_mount_records

    roles = {
        'api': 'client', 'worker': 'client', 'watcher': 'client',
        'heimdal-capture-watch': 'client', 'companion-ui': 'non-client',
        'db': 'server', 'ollama': 'non-client', 'migrate': 'migration-runner',
        'instance-state-init': 'fence-controller', 'source-identity-db-witness': 'non-client',
    }
    writers = {'api', 'worker', 'watcher', 'heimdal-capture-watch', 'companion-ui'}
    one_shots = {'migrate', 'instance-state-init', 'source-identity-db-witness'}
    try:
        services = compose['services']
        if (not isinstance(services, dict) or not {'api', 'worker', 'watcher'} <= set(services)
            or not set(services) <= set(roles)
            or not set(transitioning_writers) <= writers
            or len(ids) != len(set(ids))
            or any(re.fullmatch(r'[0-9a-f]{64}', value) is None for value in ids)
            or len(rows) != len(ids) or {row['Id'] for row in rows} != set(ids)):
            raise ValueError
        for name, service in services.items():
            if (not isinstance(service, dict) or _service_role(name, service) != roles[name]
                or (name in one_shots and service.get('restart', 'no') not in {'', 'no'})):
                raise ValueError
        installed: dict[str, Any] = {}
        retained: dict[str, Any] = {}
        for row in rows:
            config, state = row['Config'], row['State']
            labels = config['Labels']
            service = labels['com.docker.compose.service']
            if (service not in services or service in installed
                or labels.get('com.docker.compose.project') != 'pkm-' + channel
                or labels.get('com.docker.compose.oneoff', 'False') not in {'False', 'false', 'True', 'true'}
                or (labels.get('com.docker.compose.oneoff', 'False').lower() == 'true'
                    and service not in one_shots)
                or state['Status'] not in {'running', 'exited'}
                or type(state['Running']) is not bool
                or state['Running'] != (state['Status'] == 'running')
                or state['Paused'] is not False or state['Restarting'] is not False
                or state.get('Dead', False) is not False
                or type(state['Pid']) is not int
                or state['Pid'] < 0
                or (state['Pid'] > 0) != state['Running']
                or (service in one_shots and (
                    state['Status'] != 'exited'
                    or row['HostConfig']['RestartPolicy']['Name'] not in {'', 'no'}
                    or services[service].get('restart', 'no') not in {'', 'no'}
                ))):
                raise ValueError
            installed[service] = {
                'id': row['Id'], 'image': row['Image'], 'config': config,
                'host_config': row['HostConfig'],
                'mounts': _canonical_mount_records(row['Mounts']),
            }
            if service not in transitioning_writers:
                retained[service] = {
                    key: state.get(key) for key in (
                        'Status', 'Running', 'Paused', 'Restarting', 'Pid',
                        'StartedAt', 'FinishedAt', 'Dead', 'OOMKilled', 'ExitCode', 'Error',
                    )
                }
        if not {'api', 'worker', 'watcher'} <= set(installed):
            raise ValueError
        return _digest({'installed': installed, 'compose': compose}), _digest(retained)
    except Exception:
        raise PostgresDeployError() from None


def require_terminal_deployment(effects: LinuxEffects) -> None:
    receipt = effects.config.journal.read()
    if receipt is None or receipt.terminal_result not in {'committed', 'aborted', 'failed'}:
        raise PostgresDeployError()
    # Authenticate the terminal against its existing immutable request; a lone
    # terminal marker is not proof that the supervisor's old operation is over.
    plan = effects.config.journal.bound_plan(receipt.operation_id)
    effects.config.journal.bind_request(receipt.operation_id, plan, False)
    receipt.require_profile(plan)


def runtime_matches(current: SourceIdentityRuntimeSnapshot, request: dict[str, Any]) -> bool:
    return all(getattr(current, key) == request.get(key) for key in (
        'installed_fingerprint', 'execution_fingerprint', 'census_fingerprint',
        'retained_state_fingerprint', 'container_root', 'vault_overlay',
    ))


def run_diagnostic(
    effects: LinuxEffects, operation_id: str, revision: str, image_digest: str,
    selected: AuthorityCutover, *, cleanup_only: bool,
) -> dict[str, Any]:
    from app.ops import native_source_identity_diagnostics as diagnostic
    from app.ops.pg_acceptance import IMAGE_REPOSITORY
    from app.ops.postgres_deploy_linux import _atomic_private_json, _private_json

    cfg = effects.config
    if (cfg.channel not in {'dev', 'test'} or str(UUID(operation_id)) != operation_id
        or re.fullmatch(r'[0-9a-f]{40}', revision) is None
        or re.fullmatch(r'sha256:[0-9a-f]{64}', image_digest) is None
        or type(cleanup_only) is not bool):
        raise PostgresDeployError()
    selected.validate()
    base = {'operation_id': operation_id, 'channel': cfg.channel, 'revision': revision,
            'image_digest': image_digest, 'source_mode': 'current-state',
            'kind': 'source-identity-diagnostic',
            'authority_cutover': {'binding_id': selected.binding_id, 'root': selected.root,
                                  'ownership_root': selected.ownership_root}}
    stem = cfg.journal.directory / f'{cfg.channel}-source-diagnostic-{operation_id}'
    request_path, attempt_path, terminal_path = (
        Path(str(stem) + suffix) for suffix in ('.request.json', '.attempt.json', '.json')
    )
    owner = {key: str(base[key]) for key in ('kind', 'channel', 'operation_id')}
    expected_owner = (json.dumps(owner, sort_keys=True) + '\n').encode()
    image = IMAGE_REPOSITORY + '@' + image_digest
    require_terminal_deployment(effects)
    fingerprint_fields = (
        'installed_fingerprint', 'execution_fingerprint', 'census_fingerprint',
        'retained_state_fingerprint',
    )
    runtime_fields = (*fingerprint_fields, 'container_root', 'vault_overlay')
    retained_request = os.path.lexists(request_path)
    if retained_request:
        retained = _private_json(request_path)
        if (set(retained) != {*base, *runtime_fields, 'owner_token'}
            or any(retained[k] != value for k, value in base.items())
            or any(not isinstance(retained[key], str)
                   or re.fullmatch(r'[0-9a-f]{64}', retained[key]) is None for key in fingerprint_fields)
            or retained['container_root'] not in {selected.root, '/app/vault'}
            or retained['vault_overlay'] not in {'docker-compose.full-host-vault.yml', 'docker-compose.legacy-vault.yml'}):
            raise PostgresDeployError()
        token = retained['owner_token']
        if not isinstance(token, str) or re.fullmatch(r'[0-9a-f]{32}', token) is None:
            raise PostgresDeployError()
        request = {key: value for key, value in retained.items() if key != 'owner_token'}
    else:
        if cleanup_only or any(os.path.lexists(path) for path in (attempt_path, terminal_path)):
            raise PostgresDeployError()
        if effects.channel_lock_owner() is not None:
            raise PostgresDeployError()
        plan = effects.qualify_source_identity_authority(revision, image_digest, selected)
        runtime = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=False, current_state=True,
        )
        request = {**base, **{key: getattr(runtime, key) for key in runtime_fields}}
        token = secrets.token_hex(16)
        _atomic_private_json(request_path, {**request, 'owner_token': token})

    def guard(*, candidate: bool = True, owner_required: bool = True) -> None:
        if type(cfg).load(cfg.channel) != cfg:
            raise PostgresDeployError()
        require_terminal_deployment(effects)
        current_plan = effects.qualify_source_identity_authority(revision, image_digest, selected)
        current = effects.source_identity_runtime_snapshot(
            selected, require_running_capture=False, current_state=True,
        )
        if (not runtime_matches(current, request)
            or effects.channel_lock_owner() != (expected_owner if owner_required else None)):
            raise PostgresDeployError()
        if candidate:
            effects.require_source_identity_candidate(current_plan, selected, acquire=False, source_snapshot=current)

    def cleanup_container(name: str, token: str) -> None:
        expected_image = (IMAGE_REPOSITORY + ':' + revision + '@' + image_digest
                          if name == f'pkm-source-id-witness-{revision[:12]}' else image)
        diagnostic._cleanup_owned_container(name, token, expected_image=expected_image)

    def cleanup() -> None:
        for phase in ('prepare', 'witness', 'finalize'):
            cleanup_container(f'pkm-source-id-{phase}-{revision[:12]}', token)

    refused = diagnostic.validate_source_receipt({
        'contract': diagnostic.SOURCE_RECEIPT_CONTRACT, 'channel': cfg.channel, 'revision': revision,
        'terminal_state': 'refused', 'reason': 'database_witness_refused',
        **{key: 0 for key in (*diagnostic.SOURCE_COUNT_FIELDS, *diagnostic.COUNT_FIELDS)},
    })
    effects.operation_id = operation_id
    if retained_request or cleanup_only:
        if os.path.lexists(attempt_path) and _private_json(attempt_path) != request:
            raise PostgresDeployError()
        result = diagnostic.validate_source_receipt(_private_json(terminal_path)) if os.path.lexists(terminal_path) else refused
        if result['channel'] != cfg.channel or result['revision'] != revision:
            raise PostgresDeployError()
        if effects.channel_lock_owner() is not None:
            with effects.failed_reconciliation_lock(expected_owner=owner) as handle:
                # Only the authenticated request/fence/token/image may retire
                # its own one-shot before the complete census. A surviving
                # witness is not an ordinary installed service or authority.
                cleanup()
                guard(candidate=False)
                _atomic_private_json(terminal_path, result)
                effects.retire_reconciled_channel_lock(handle, expected_owner=owner)
        elif not os.path.lexists(terminal_path):
            # This request can precede the first lock or attempted worker.
            # Reconcile its own token only; never execute the workers on retry.
            with effects.channel_lock(journal=cfg.journal, owner_marker=owner, retire_terminal=False):
                cleanup()
                guard(candidate=False)
                _atomic_private_json(terminal_path, result)
            with effects.failed_reconciliation_lock(expected_owner=owner) as handle:
                guard(candidate=False)
                effects.retire_reconciled_channel_lock(handle, expected_owner=owner)
        else:
            guard(candidate=False, owner_required=False)
        return result
    result = refused
    with effects.channel_lock(journal=cfg.journal, owner_marker=owner, retire_terminal=False):
        guard(candidate=False)
        effects.require_source_identity_candidate(plan, selected, acquire=True, source_snapshot=runtime)
        guard()
        password = effects.source.read_for_source_witness()
        argv, environment = effects.source_compose_invocation(
            cutover=selected, candidate=plan, source_snapshot=runtime,
        )
        _atomic_private_json(attempt_path, request)
        try:
            result = diagnostic.run_production_diagnostic(
                source_image=image,
                source_root=Path(selected.root), container_source_root=runtime.container_root,
                compose_prefix=tuple(argv), channel=cfg.channel, revision=revision,
                source_environment=dict(runtime.child_environment), effect_guard=guard, owner_token=token,
                witness_password=password,
                witness_database_url=environment['DATABASE_URL'],
                container_cleanup=cleanup_container,
                child_runner=partial(diagnostic._run_bounded_child, environment=environment, cwd=cfg.root),
            )
        except Exception:
            result = refused
        cleanup()
        guard()
        _atomic_private_json(terminal_path, result)
    with effects.failed_reconciliation_lock(expected_owner=owner) as handle:
        guard()
        effects.retire_reconciled_channel_lock(handle, expected_owner=owner)
    return result
