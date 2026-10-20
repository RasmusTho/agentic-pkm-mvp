"""Agent-host entrypoint; BWS admin authentication stays in macOS Keychain."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any
from uuid import UUID, uuid4

from app.ops.bws_secret_admin import BwsAdminConfig, BwsSecretAdmin
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.host_secret_controller import HostSecretController, TerminalEvidence
from app.ops.postgres_deploy import (
    AuthorityCutover, DeployPlan, DeployReceipt, PostgresDeployError, TestRecoveryRequest,
    deploy_from_host,
)
from app.ops.postgres_deploy_linux import SshDeployRemote
from app.ops.secret_admin import SecretAdmin


_ADMIN_METADATA_KEYS = ('BWS_ORGANIZATION_ID', 'BWS_NON_PROD_PROJECT_ID', 'BWS_PROD_PROJECT_ID')
# Stdlib-only code sent to the existing strict aliases: it requires no checkout
# update on the VMs and opens only canonical non-secret channel configuration.
_CHANNEL_METADATA_READER = '''
import json, os, stat, sys
from uuid import UUID

def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError()
    return result

def trusted_directory(descriptor):
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError()

directory = None
try:
    if len(sys.argv) != 2 or sys.argv[1] not in ('dev', 'test', 'prod'):
        raise ValueError()
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    trusted_directory(directory)
    for component in ('etc', 'yggdrasil', 'bws-deploy'):
        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        os.close(directory)
        directory = child
        trusted_directory(directory)
    descriptor = os.open(sys.argv[1] + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
            or not 0 < info.st_size <= 65536):
            raise ValueError()
        raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        data = json.loads(raw, object_pairs_hook=unique_object)
    keys = {'root', 'data_directory', 'uid', 'gid', 'organization_id', 'project_id'}
    if not isinstance(data, dict) or set(data) not in (keys, keys | {'runtime_env_file'}):
        raise ValueError()
    metadata = {key: data[key] for key in ('organization_id', 'project_id')}
    for value in metadata.values():
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    print(json.dumps(metadata, sort_keys=True))
except Exception:
    print('channel metadata refused', file=sys.stderr)
    raise SystemExit(78) from None
finally:
    if directory is not None:
        os.close(directory)
'''


def _unique_metadata_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise PostgresDeployError()
    return result


def _canonical_uuid(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise PostgresDeployError()
    return value


def _installed_channel_metadata(channel: str) -> dict[str, str]:
    if channel not in ('dev', 'test', 'prod'):
        raise PostgresDeployError()
    try:
        # Do not inherit token, metadata, or runtime-secret environment into SSH.
        ssh_environment = {key: os.environ[key] for key in
                           ('HOME', 'USER', 'LOGNAME', 'PATH', 'SSH_AUTH_SOCK') if key in os.environ}
        result = subprocess.run([
            '/usr/bin/ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
            '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no',
            '--', 'ygg-' + channel, 'sudo', '-n', '/usr/bin/python3', '-I', '-S', '-B', '-', channel,
        ], input=_CHANNEL_METADATA_READER, env=ssh_environment, text=True,
            capture_output=True, timeout=20, check=False)
        if result.returncode != 0 or result.stderr or len(result.stdout) > 256:
            raise PostgresDeployError()
        data = json.loads(result.stdout, object_pairs_hook=_unique_metadata_object)
        if not isinstance(data, dict) or set(data) != {'organization_id', 'project_id'}:
            raise PostgresDeployError()
        return {key: _canonical_uuid(data[key]) for key in ('organization_id', 'project_id')}
    except Exception:
        raise PostgresDeployError() from None


def _configured_host_admin() -> BwsSecretAdmin:
    # Keep unrelated callers' configured_admin factory unchanged. Complete
    # explicit metadata preserves its route; partial metadata must match sources.
    supplied = {key: _canonical_uuid(os.environ[key]) for key in _ADMIN_METADATA_KEYS if key in os.environ}
    if len(supplied) == len(_ADMIN_METADATA_KEYS):
        return BwsSecretAdmin(BwsAdminConfig.from_environment(supplied))
    installed = {channel: _installed_channel_metadata(channel) for channel in ('dev', 'test', 'prod')}
    if (len({item['organization_id'] for item in installed.values()}) != 1
        or installed['dev']['project_id'] != installed['test']['project_id']):
        raise PostgresDeployError()
    metadata = dict(zip(_ADMIN_METADATA_KEYS, (installed['dev']['organization_id'],
                    installed['dev']['project_id'], installed['prod']['project_id']), strict=True))
    if any(value != metadata[key] for key, value in supplied.items()):
        raise PostgresDeployError()
    return BwsSecretAdmin(BwsAdminConfig.from_environment(metadata))


def require_qualification(controller: HostSecretController) -> None:
    """Read an owner-installed admission receipt; never manufacture live approval."""
    path = controller.directory / 'qualification.json'
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor) as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096):
            raise PostgresDeployError()
        receipt = json.load(source)
    if (not isinstance(receipt, dict)
        or set(receipt) != {'controller', 'sole_writer_approved', 'credentials_restricted', 'live_receipt'}
        or receipt['controller'] != str(controller.directory)
        or receipt['sole_writer_approved'] is not True or receipt['credentials_restricted'] is not True
        or not isinstance(receipt['live_receipt'], str)
        or not receipt['live_receipt'].startswith('https://github.com/RasmusTho/agentic-pkm-mvp/issues/5667#issuecomment-')
        or not receipt['live_receipt'].rsplit('-', 1)[-1].isdigit()):
        raise PostgresDeployError()


_TEST_RECOVERY_MARKER_SCHEMA = 'test-source-recovery-host.v1'
_TEST_RECOVERY_REPAIR_MARKER_SCHEMA = 'test-source-recovery-host.v2'


def _test_recovery_marker_path(controller: HostSecretController,
                               request: TestRecoveryRequest) -> Path:
    request.validate()
    directory = controller.directory
    if (not directory.is_absolute()
            or any(parent.is_symlink() for parent in (directory, *directory.parents))):
        raise PostgresDeployError()
    source_operation_id = request.source_operation_id or request.failed_operation_id
    return directory / ('test-source-recovery-' + source_operation_id + '.json')


def _read_test_recovery_marker(controller: HostSecretController,
                               request: TestRecoveryRequest) -> dict[str, Any] | None:
    path = _test_recovery_marker_path(controller, request)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, 'r', encoding='utf-8') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_size > 65536):
            raise PostgresDeployError()
        marker = json.load(source, object_pairs_hook=_unique_metadata_object)
    v1_fields = (
        {'schema', 'state', 'request', 'fresh_operation_id'},
        {'schema', 'state', 'request', 'fresh_operation_id',
         'instance_state_reconstructed'},
    )
    v2_fields = {
        'schema', 'state', 'request', 'fresh_operation_id',
        'instance_state_reconstructed', 'repair',
    }
    if (not isinstance(marker, dict)
            or (marker.get('schema') == _TEST_RECOVERY_MARKER_SCHEMA
                and set(marker) not in v1_fields)
            or (marker.get('schema') == _TEST_RECOVERY_REPAIR_MARKER_SCHEMA
                and set(marker) != v2_fields)
            or marker.get('schema') not in {
                _TEST_RECOVERY_MARKER_SCHEMA, _TEST_RECOVERY_REPAIR_MARKER_SCHEMA,
            }
            or marker['state'] not in {'resetting', 'ready'}
            or ('instance_state_reconstructed' in marker
                and type(marker['instance_state_reconstructed']) is not bool)):
        raise PostgresDeployError()
    try:
        fresh_operation_id = _canonical_uuid(marker['fresh_operation_id'])
    except Exception:
        raise PostgresDeployError() from None
    if fresh_operation_id != marker['fresh_operation_id']:
        raise PostgresDeployError()
    stored = TestRecoveryRequest.from_payload(marker['request'])
    source_operation_id = request.source_operation_id or request.failed_operation_id
    if (stored.source_operation_id is not None
            or stored.failed_operation_id != source_operation_id
            or stored.authority_cutover != request.authority_cutover
            or (marker['state'] != 'ready' and stored != request)):
        raise PostgresDeployError()
    if marker['schema'] == _TEST_RECOVERY_REPAIR_MARKER_SCHEMA:
        repair = marker.get('repair')
        if (not isinstance(repair, dict)
                or set(repair) != {
                    'failed_successor_operation_id', 'candidate_plan',
                    'next_operation_id',
                }):
            raise PostgresDeployError()
        try:
            failed_successor = _canonical_uuid(repair['failed_successor_operation_id'])
            next_operation = _canonical_uuid(repair['next_operation_id'])
            candidate_plan = DeployPlan.from_payload(repair['candidate_plan'])
        except Exception:
            raise PostgresDeployError() from None
        if (failed_successor != marker['fresh_operation_id']
                or failed_successor == next_operation
                or candidate_plan.channel != 'test'
                or not candidate_plan.automatic
                or candidate_plan.authority_cutover is not None):
            raise PostgresDeployError()
        marker['repair'] = {
            **repair,
            'candidate_plan_object': candidate_plan,
        }
    # A marker written by the source-reset-only producer predates the explicit
    # instance-state producer.  Treat it as an authenticated reset checkpoint,
    # never as proof that reconstruction happened.
    marker.setdefault('instance_state_reconstructed', False)
    return marker


def _write_test_recovery_repair_marker(
    controller: HostSecretController, source_request: TestRecoveryRequest,
    *, failed_successor_operation_id: str, candidate_plan: DeployPlan,
    next_operation_id: str, instance_state_reconstructed: bool,
) -> None:
    failed_successor_operation_id = _canonical_uuid(failed_successor_operation_id)
    next_operation_id = _canonical_uuid(next_operation_id)
    if (failed_successor_operation_id == next_operation_id
            or source_request.source_operation_id is not None):
        raise PostgresDeployError()
    candidate_plan.validate()
    probe = TestRecoveryRequest(
        failed_successor_operation_id, candidate_plan,
        source_request.authority_cutover,
        source_operation_id=source_request.failed_operation_id,
        source_plan=source_request.plan,
    )
    probe.validate()
    prior = _read_test_recovery_marker(controller, probe)
    if prior is None or prior['state'] != 'ready':
        raise PostgresDeployError()
    repair = {
        'failed_successor_operation_id': failed_successor_operation_id,
        'candidate_plan': json.loads(json.dumps(candidate_plan.payload())),
        'next_operation_id': next_operation_id,
    }
    if prior['schema'] == _TEST_RECOVERY_REPAIR_MARKER_SCHEMA:
        normalized = dict(prior['repair'])
        normalized.pop('candidate_plan_object', None)
        if normalized != repair:
            raise PostgresDeployError()
        if prior['instance_state_reconstructed'] or not instance_state_reconstructed:
            return
    path = _test_recovery_marker_path(controller, source_request)
    payload = {
        'schema': _TEST_RECOVERY_REPAIR_MARKER_SCHEMA,
        'state': 'ready',
        'request': source_request.payload(),
        'fresh_operation_id': failed_successor_operation_id,
        'instance_state_reconstructed': instance_state_reconstructed,
        'repair': repair,
    }
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix='.' + path.name + '.', text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _write_test_recovery_marker(controller: HostSecretController,
                                request: TestRecoveryRequest, state: str,
                                fresh_operation_id: str,
                                *, instance_state_reconstructed: bool = False) -> None:
    if state not in {'resetting', 'ready'}:
        raise PostgresDeployError()
    fresh_operation_id = _canonical_uuid(fresh_operation_id)
    path = _test_recovery_marker_path(controller, request)
    directory = path.parent
    try:
        info = directory.stat()
    except OSError:
        raise PostgresDeployError() from None
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PostgresDeployError()
    prior = _read_test_recovery_marker(controller, request)
    if prior is not None:
        if prior['fresh_operation_id'] != fresh_operation_id:
            raise PostgresDeployError()
        if (prior['state'] == state
                and (prior['instance_state_reconstructed'] or not instance_state_reconstructed)):
            return
    payload = {
        'schema': _TEST_RECOVERY_MARKER_SCHEMA,
        'state': state,
        'request': request.payload(),
        'fresh_operation_id': fresh_operation_id,
        'instance_state_reconstructed': instance_state_reconstructed,
    }
    descriptor, temporary_name = tempfile.mkstemp(
        dir=directory, prefix='.' + path.name + '.', text=True,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('channel', choices=('dev', 'test', 'prod'))
    parser.add_argument('revision')
    parser.add_argument('--image-digest', help='immutable published sha256 image-index digest')
    parser.add_argument('--automatic', action='store_true', help='non-production existing-secret delivery')
    parser.add_argument('--operation-id', help='stable automatic candidate/channel operation UUID')
    parser.add_argument('--authority-cutover-binding', help='already-qualified nonprod binding')
    parser.add_argument('--authority-cutover-root', help='exact existing selected host root')
    parser.add_argument('--authority-cutover-ownership-root', help='qualified existing host ownership state')
    parser.add_argument(
        '--ack-forward-only', action='store_true',
        help='acknowledge forward-only migrations in this exact deployment request',
    )
    parser.add_argument(
        '--existing-secrets-only', action='store_true',
        help='refuse a missing PostgreSQL password before remote mutation; never bootstrap a BWS value',
    )
    parser.add_argument(
        '--reconcile-pending', action='store_true',
        help='reconcile this exact existing-secrets-only operation after remote terminal evidence',
    )
    parser.add_argument(
        '--prove-never-admitted', action='store_true',
        help='prove this exact automatic operation left no host or native mutation footprint',
    )
    parser.add_argument(
        '--persist-source-identity', action='store_true',
        help='run one explicit DEV/TEST ordinary-producer identity persistence operation',
    )
    parser.add_argument(
        '--preflight-source-persistence-admission', action='store_true',
        help='read exact value-free host admission before allocating a source operation ID',
    )
    parser.add_argument(
        '--restore-operator-source-identity', action='store_true',
        help='run the separately reviewed DEV-only established-identity restoration',
    )
    parser.add_argument(
        '--resume-unattempted-operator-restoration', action='store_true',
        help='resume only a positively undispatched restoration request',
    )
    parser.add_argument(
        '--reconcile-operator-unknown-cleanup', action='store_true',
        help='retire one exact host operator operation after qualified native unknown cleanup',
    )
    parser.add_argument(
        '--prove-source-persistence-never-admitted', action='store_true',
        help='retire one exact host source operation only after fixed native absence proof',
    )
    parser.add_argument(
        '--recover-test-source', action='store_true',
        help='reset only the exact failed TEST source projection, then deploy this candidate',
    )
    parser.add_argument(
        '--reconstruct-missing-instance-state', '--reconstruct-missing-test-instance-state',
        dest='reconstruct_missing_instance_state', action='store_true',
        help='reconstruct only the exact already-lost TEST instance-state authority',
    )
    parser.add_argument(
        '--failed-operation-id',
        help='exact failed TEST deployment operation authenticated by --recover-test-source',
    )
    args = parser.parse_args(argv)
    try:
        cutover = None
        recovery_authority = None
        if any(value is not None for value in (args.authority_cutover_binding, args.authority_cutover_root,
                                               args.authority_cutover_ownership_root)):
            if (not args.authority_cutover_binding or not args.authority_cutover_root
                or not args.authority_cutover_ownership_root or not args.existing_secrets_only):
                raise PostgresDeployError()
            selected = AuthorityCutover(args.authority_cutover_binding, args.authority_cutover_root,
                                        args.authority_cutover_ownership_root)
            if args.recover_test_source or args.reconstruct_missing_instance_state:
                recovery_authority = selected
            else:
                cutover = selected
        if args.recover_test_source or args.reconstruct_missing_instance_state:
            if (args.channel != 'test' or not args.automatic or not args.existing_secrets_only
                or args.reconcile_pending or args.operation_id is not None
                or args.failed_operation_id is None or recovery_authority is None
                or (args.recover_test_source and args.reconstruct_missing_instance_state)):
                raise PostgresDeployError()
            if not isinstance(args.failed_operation_id, str) or str(UUID(args.failed_operation_id)) != args.failed_operation_id:
                raise PostgresDeployError()
        elif args.failed_operation_id is not None:
            raise PostgresDeployError()
        if args.automatic and not args.existing_secrets_only:
            raise PostgresDeployError()
        if args.operation_id is not None and (
            not (args.automatic or cutover is not None) or str(UUID(args.operation_id)) != args.operation_id
        ):
            raise PostgresDeployError()
        controller = HostSecretController()
        if args.preflight_source_persistence_admission:
            if (
                args.channel not in {'dev', 'test'}
                or not args.automatic
                or not args.existing_secrets_only
                or args.operation_id is not None
                or cutover is not None
                or args.persist_source_identity
                or args.restore_operator_source_identity
                or args.resume_unattempted_operator_restoration
                or args.reconcile_operator_unknown_cleanup
                or args.reconcile_pending
                or args.prove_never_admitted
                or args.prove_source_persistence_never_admitted
                or args.recover_test_source
                or args.reconstruct_missing_instance_state
                or args.failed_operation_id is not None
                or args.ack_forward_only
            ):
                raise PostgresDeployError()
            preflight = controller.source_persistence_preflight(args.channel)
            print(json.dumps(preflight, sort_keys=True))
            return 0 if preflight['ready'] is True else 78
        if args.reconcile_operator_unknown_cleanup:
            if (
                args.channel != 'dev'
                or not args.automatic
                or not args.existing_secrets_only
                or args.operation_id is None
                or cutover is None
                or args.image_digest is None
                or args.persist_source_identity
                or args.restore_operator_source_identity
                or args.resume_unattempted_operator_restoration
                or args.reconcile_pending
                or args.prove_never_admitted
                or args.prove_source_persistence_never_admitted
                or args.recover_test_source
                or args.reconstruct_missing_instance_state
                or args.failed_operation_id is not None
                or args.ack_forward_only
                or re.fullmatch(r'[0-9a-f]{40}', args.revision) is None
            ):
                raise PostgresDeployError()
            with controller.operator_identity_restoration_operation(
                'dev', operation_id=args.operation_id,
            ) as (operation, resumed):
                if not resumed:
                    raise PostgresDeployError()
                if operation.completed_result == 'reconciled-unknown':
                    print(json.dumps({
                        'contract': 'operator-restoration-host-reconciliation.v1',
                        'operation_id': operation.operation_id,
                        'host_terminal_projection': 'reconciled-unknown',
                        'idempotent_replay': True,
                        'native_replayed': False,
                    }, sort_keys=True))
                    return 0
                if operation.completed_result is not None or not operation.mutation_started:
                    raise PostgresDeployError()
                remote = SshDeployRemote('ygg-dev')
                reconciliation = remote.reconcile_operator_identity_restoration_unknown(
                    operation.operation_id, args.revision, args.image_digest, cutover,
                )
                operation.finish(TerminalEvidence(
                    operation.operation_id, 'operator-identity-restoration', 'dev',
                    'reconciled-unknown', 'remote-terminal-unknown-cleanup-complete',
                ))
            print(json.dumps({
                **reconciliation,
                'host_terminal_projection': 'reconciled-unknown',
                'idempotent_replay': False,
            }, sort_keys=True))
            return 0
        if args.prove_source_persistence_never_admitted:
            if (
                args.channel not in {'dev', 'test'}
                or not args.automatic
                or not args.existing_secrets_only
                or args.operation_id is None
                or cutover is not None
                or args.persist_source_identity
                or args.preflight_source_persistence_admission
                or args.restore_operator_source_identity
                or args.reconcile_operator_unknown_cleanup
                or args.reconcile_pending
                or args.prove_never_admitted
                or args.recover_test_source
                or args.reconstruct_missing_instance_state
                or args.failed_operation_id is not None
                or args.ack_forward_only
            ):
                raise PostgresDeployError()
            with controller.source_persistence_operation(
                args.channel, operation_id=args.operation_id,
            ) as (operation, resumed):
                if (
                    not resumed
                    or operation.completed_result not in {None, 'failed'}
                    or (
                        operation.completed_result is None
                        and not operation.mutation_started
                    )
                ):
                    raise PostgresDeployError()
                remote = SshDeployRemote('ygg-' + args.channel)
                proof = remote.prove_source_identity_absence(args.operation_id)
                operation.finish(TerminalEvidence(
                    operation.operation_id, 'source-persistence', args.channel,
                    'failed', 'native-absence-proof',
                ))
            result = {**proof, 'host_operation_retired': True}
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.restore_operator_source_identity:
            if (
                args.channel != 'dev'
                or not args.automatic
                or not args.existing_secrets_only
                or args.operation_id is None
                or cutover is None
                or args.image_digest is None
                or args.reconcile_pending
                or args.prove_never_admitted
                or args.prove_source_persistence_never_admitted
                or args.persist_source_identity
                or args.preflight_source_persistence_admission
                or args.reconcile_operator_unknown_cleanup
                or args.recover_test_source
                or args.reconstruct_missing_instance_state
                or args.failed_operation_id is not None
                or args.ack_forward_only
                or re.fullmatch(r'[0-9a-f]{40}', args.revision) is None
            ):
                raise PostgresDeployError()
            try:
                command = json.load(sys.stdin, object_pairs_hook=_unique_metadata_object)
            except Exception:
                raise PostgresDeployError() from None
            from app.ops.native_operator_identity_restoration import validate_command

            command = validate_command(command)
            remote = SshDeployRemote('ygg-dev')
            with controller.operator_identity_restoration_operation(
                'dev', operation_id=args.operation_id,
            ) as (operation, resumed):
                if operation.completed_result is None:
                    if resumed and not args.resume_unattempted_operator_restoration:
                        # Remote continuation remains cleanup-only by default.
                        pass
                    operation.prepare_mutation()
                result = remote.restore_operator_source_identity(
                    operation.operation_id, args.revision, args.image_digest,
                    cutover, command,
                    resume_unattempted=args.resume_unattempted_operator_restoration,
                )
                if result['cleanup'] != 'complete' or result['result'] == 'unknown':
                    print(json.dumps(result, sort_keys=True))
                    return 78
                terminal = 'committed' if result['result'] == 'committed' else 'failed'
                operation.finish(TerminalEvidence(
                    operation.operation_id, 'operator-identity-restoration', 'dev',
                    terminal, 'remote-terminal',
                ))
            print(json.dumps(result, sort_keys=True))
            return 0 if result['result'] == 'committed' else 78
        if args.persist_source_identity:
            if (
                args.channel not in {'dev', 'test'}
                or not args.automatic
                or not args.existing_secrets_only
                or args.operation_id is None
                or cutover is None
                or args.image_digest is None
                or args.reconcile_pending
                or args.prove_never_admitted
                or args.prove_source_persistence_never_admitted
                or args.recover_test_source
                or args.reconstruct_missing_instance_state
                or args.failed_operation_id is not None
                or args.ack_forward_only
                or args.restore_operator_source_identity
                or args.resume_unattempted_operator_restoration
                or args.preflight_source_persistence_admission
                or args.reconcile_operator_unknown_cleanup
                or re.fullmatch(r'[0-9a-f]{40}', args.revision) is None
            ):
                raise PostgresDeployError()
            remote = SshDeployRemote('ygg-' + args.channel)
            with controller.source_persistence_operation(
                args.channel, operation_id=args.operation_id,
            ) as (operation, _resumed):
                if operation.completed_source == 'native-absence-proof':
                    raise PostgresDeployError()
                if operation.completed_result is None:
                    operation.prepare_mutation()
                result = remote.persist_source_identity(
                    operation.operation_id, args.revision, args.image_digest, cutover,
                )
                terminal = result['terminal_state']
                operation.finish(TerminalEvidence(
                    operation.operation_id, 'source-persistence', args.channel,
                    terminal, 'remote-terminal',
                ))
            print(json.dumps(result, sort_keys=True))
            return 0 if result['terminal_state'] == 'committed' else 78
        if args.resume_unattempted_operator_restoration:
            raise PostgresDeployError()
        # The controller can inspect DB credentials and the API's degrade-visibly
        # binding. VM-only consumers are selected from VM runtime/migration state.
        plan = DeployPlan(args.channel, args.revision, tuple(DATABASE_CONSUMERS.values()),
                          (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), args.ack_forward_only,
                          args.image_digest, args.automatic, cutover)
        recovery_request = None
        if args.recover_test_source or args.reconstruct_missing_instance_state:
            failed_operation_id = args.failed_operation_id
            selected_authority = recovery_authority
            if not isinstance(failed_operation_id, str) or selected_authority is None:
                raise PostgresDeployError()
            recovery_request = TestRecoveryRequest(failed_operation_id, plan, selected_authority)
            recovery_request.validate()
        plan.validate()
        if args.prove_never_admitted:
            if (
                not args.existing_secrets_only
                or not args.automatic
                or args.operation_id is None
                or args.reconcile_pending
                or args.recover_test_source
                or args.reconstruct_missing_instance_state
                or args.channel not in {'dev', 'test'}
            ):
                raise PostgresDeployError()
            remote = SshDeployRemote('ygg-' + args.channel)
            proof = controller.prove_deploy_absence(
                args.operation_id,
                args.channel,
                lambda: remote.prove_absence(args.operation_id, plan),
            )
            proof = {
                **proof,
                'contract': 'postmerge-native-operation-absence.v1',
                'candidate_sha': args.revision,
                'image_digest': args.image_digest or '',
            }
            print(json.dumps(proof, sort_keys=True))
            return 0
        if recovery_request is not None:
            remote = SshDeployRemote('ygg-test')
            marker = _read_test_recovery_marker(controller, recovery_request)
            if args.reconstruct_missing_instance_state:
                if marker is None or marker['state'] != 'ready':
                    raise PostgresDeployError()
                source_request = TestRecoveryRequest.from_payload(marker['request'])
                failed_successor_operation_id = marker['fresh_operation_id']
                if marker['schema'] == _TEST_RECOVERY_REPAIR_MARKER_SCHEMA:
                    repair = marker['repair']
                    if repair['candidate_plan_object'] != plan:
                        raise PostgresDeployError()
                    next_operation_id = repair['next_operation_id']
                else:
                    next_operation_id = str(uuid4())
                lineage_request = TestRecoveryRequest(
                    failed_successor_operation_id, plan,
                    recovery_request.authority_cutover,
                    source_operation_id=recovery_request.failed_operation_id,
                    source_plan=source_request.plan,
                )
                lineage_request.validate()
                # The original reset checkpoint is insufficient: the exact
                # automatic successor stored in it must itself be terminal
                # failed before a distinct new candidate can be allocated.
                with controller.deploy_operation(
                    'test', allow_bootstrap=False,
                    operation_id=failed_successor_operation_id,
                ) as (failed_successor, resumed):
                    if (not resumed
                            or failed_successor.completed_result != 'failed'):
                        raise PostgresDeployError()
                _write_test_recovery_repair_marker(
                    controller, source_request,
                    failed_successor_operation_id=failed_successor_operation_id,
                    candidate_plan=plan,
                    next_operation_id=next_operation_id,
                    instance_state_reconstructed=marker['instance_state_reconstructed'],
                )
                marker = _read_test_recovery_marker(controller, lineage_request)
                if marker is None:
                    raise PostgresDeployError()
                if not marker['instance_state_reconstructed']:
                    result = remote.test_recovery_reconstruct_instance_state(
                        lineage_request
                    )
                    if result.get('activation') != 'inactive_fenced':
                        raise PostgresDeployError()
                    _write_test_recovery_repair_marker(
                        controller, source_request,
                        failed_successor_operation_id=failed_successor_operation_id,
                        candidate_plan=plan,
                        next_operation_id=next_operation_id,
                        instance_state_reconstructed=True,
                    )
                # Reconstruction deliberately retains its deployment lease
                # until this host checkpoint is durable. The explicit,
                # idempotent handoff then clears only that authenticated lease
                # before the fresh normal deployment tries to claim it.
                remote.test_recovery_release_instance_state(
                    lineage_request, successor_operation_id=next_operation_id,
                )
                admin = SecretAdmin(_configured_host_admin(), controller=controller)
                receipt = deploy_from_host(
                    admin, remote, plan,
                    qualified=lambda: require_qualification(controller),
                    allow_bootstrap=False, operation_id=next_operation_id,
                )
                print(json.dumps(receipt.payload(), sort_keys=True))
                return 0 if receipt.terminal_result == 'committed' else 78

            if marker is not None and marker['schema'] != _TEST_RECOVERY_MARKER_SCHEMA:
                raise PostgresDeployError()
            if (marker is not None
                    and TestRecoveryRequest.from_payload(marker['request'])
                    != recovery_request):
                raise PostgresDeployError()
            if marker is None:
                fresh_operation_id = str(uuid4())
                marker_state = 'resetting'
            else:
                fresh_operation_id = marker['fresh_operation_id']
                marker_state = marker['state']
            if marker_state == 'resetting':
                # Keep the old host operation bound until the VM has returned
                # exact failed terminal evidence. If the old operation was
                # already terminalized before a crash, deploy_operation exposes
                # that exact completed ID and the reset remains idempotent.
                with controller.deploy_operation(
                    'test', allow_bootstrap=False,
                    operation_id=recovery_request.failed_operation_id,
                ) as (operation, resumed):
                    if not resumed:
                        raise PostgresDeployError()
                    receipt = remote.test_recovery_reset(recovery_request)
                    if receipt.terminal_result != 'failed':
                        raise PostgresDeployError()
                    if operation.completed_result is None:
                        operation.finish(receipt.evidence())
                    elif operation.completed_result != 'failed':
                        raise PostgresDeployError()
                    # The VM validates the retained failed plan against the
                    # automatic successor before any reset mutation.  Persist
                    # the host checkpoint only after that call succeeds so a
                    # static mismatch cannot leave a misleading local marker.
                    _write_test_recovery_marker(
                        controller, recovery_request, 'ready', fresh_operation_id,
                    )
            admin = SecretAdmin(_configured_host_admin(), controller=controller)
            receipt = deploy_from_host(
                admin, remote, plan, qualified=lambda: require_qualification(controller),
                allow_bootstrap=False, operation_id=fresh_operation_id,
            )
            print(json.dumps(receipt.payload(), sort_keys=True))
            return 0 if receipt.terminal_result == 'committed' else 78
        if args.reconcile_pending:
            if not args.existing_secrets_only:
                raise PostgresDeployError()
            remote = SshDeployRemote('ygg-' + args.channel)
            receipts: list[DeployReceipt] = []

            def readback(operation_id: str, kind: str, target: str) -> TerminalEvidence:
                if kind != 'deploy' or target != args.channel:
                    raise PostgresDeployError()
                receipt = remote.reconcile_failed(operation_id, plan)
                receipts.append(receipt)
                return receipt.evidence()

            if args.operation_id is not None:
                with controller.deploy_operation(args.channel, allow_bootstrap=False,
                                                 operation_id=args.operation_id) as (operation, resumed):
                    if not resumed:
                        raise PostgresDeployError()
                    operation.finish(readback(operation.operation_id, 'deploy', args.channel))
            else:
                controller.reconcile(readback, expected=('deploy', args.channel, False))
            receipt = receipts[-1]
            print(json.dumps(receipt.payload(), sort_keys=True))
            return 0
        admin = SecretAdmin(_configured_host_admin(), controller=controller)
        options = {'operation_id': args.operation_id} if args.operation_id is not None else {}
        receipt = deploy_from_host(admin, SshDeployRemote('ygg-' + args.channel), plan,
                                   qualified=lambda: require_qualification(controller),
                                   allow_bootstrap=not args.existing_secrets_only, **options)
        print(json.dumps(receipt.payload(), sort_keys=True))
        return 0 if receipt.terminal_result == 'committed' else 78
    except Exception:
        print('database deployment refused; inspect value-free operation status', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
