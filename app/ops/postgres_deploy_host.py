"""Agent-host entrypoint; BWS admin authentication stays in macOS Keychain."""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from typing import Any
from uuid import UUID

from app.ops.bws_secret_admin import BwsAdminConfig, BwsSecretAdmin
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.host_secret_controller import HostSecretController, TerminalEvidence
from app.ops.postgres_deploy import DeployPlan, DeployReceipt, PostgresDeployError, deploy_from_host
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('channel', choices=('dev', 'test', 'prod'))
    parser.add_argument('revision')
    parser.add_argument('--image-digest', help='immutable published sha256 image-index digest')
    parser.add_argument('--automatic', action='store_true', help='non-production existing-secret delivery')
    parser.add_argument('--operation-id', help='stable automatic candidate/channel operation UUID')
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
    args = parser.parse_args(argv)
    try:
        if args.automatic and not args.existing_secrets_only:
            raise PostgresDeployError()
        if args.operation_id is not None and (
            not args.automatic or str(UUID(args.operation_id)) != args.operation_id
        ):
            raise PostgresDeployError()
        controller = HostSecretController()
        # The controller can inspect DB credentials and the API's degrade-visibly
        # binding. VM-only consumers are selected from VM runtime/migration state.
        plan = DeployPlan(args.channel, args.revision, tuple(DATABASE_CONSUMERS.values()),
                          (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), args.ack_forward_only,
                          args.image_digest, args.automatic)
        plan.validate()
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
            print(json.dumps(receipt.__dict__, sort_keys=True))
            return 0
        admin = SecretAdmin(_configured_host_admin(), controller=controller)
        options = {'operation_id': args.operation_id} if args.operation_id is not None else {}
        receipt = deploy_from_host(admin, SshDeployRemote('ygg-' + args.channel), plan,
                                   qualified=lambda: require_qualification(controller),
                                   allow_bootstrap=not args.existing_secrets_only, **options)
        print(json.dumps(receipt.__dict__, sort_keys=True))
        return 0 if receipt.terminal_result == 'committed' else 78
    except Exception:
        print('database deployment refused; inspect value-free operation status', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
