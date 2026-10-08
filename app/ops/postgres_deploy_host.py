"""Agent-host entrypoint; BWS admin authentication stays in macOS Keychain."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys

from app.ops.bws_secret_admin import configured_admin
from app.ops.host_secret_contract import DATABASE_CONSUMERS
from app.ops.host_secret_controller import HostSecretController
from app.ops.postgres_deploy import DeployPlan, PostgresDeployError, deploy_from_host
from app.ops.postgres_deploy_linux import SshDeployRemote
from app.ops.secret_admin import SecretAdmin


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
    parser.add_argument(
        '--ack-forward-only', action='store_true',
        help='acknowledge forward-only migrations in this exact deployment request',
    )
    parser.add_argument(
        '--existing-secrets-only', action='store_true',
        help='refuse a missing PostgreSQL password before remote mutation; never bootstrap a BWS value',
    )
    args = parser.parse_args(argv)
    try:
        controller = HostSecretController()
        # The controller can inspect DB credentials and the API's degrade-visibly
        # binding. VM-only consumers are selected from VM runtime/migration state.
        plan = DeployPlan(args.channel, args.revision, tuple(DATABASE_CONSUMERS.values()),
                          (*DATABASE_CONSUMERS, 'heimdal-api-ingress'), args.ack_forward_only)
        admin = SecretAdmin(configured_admin(), controller=controller)
        receipt = deploy_from_host(admin, SshDeployRemote('ygg-' + args.channel), plan,
                                   qualified=lambda: require_qualification(controller),
                                   allow_bootstrap=not args.existing_secrets_only)
        print(json.dumps(receipt.__dict__, sort_keys=True))
        return 0 if receipt.terminal_result == 'committed' else 78
    except Exception:
        print('database deployment refused; inspect value-free operation status', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
