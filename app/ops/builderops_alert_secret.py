"""Fixed Heimdal/BWS handoff to bob-1's existing systemd credential facility.

The administrator remains on Demerzel. No reader account or Product consumer is
installed on bob-1. Values travel only in process memory and SSH standard input.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from app.ops.bws_secret_admin import (
    BUILDEROPS_ALERT_IDENTITY, BUILDEROPS_ALERT_TARGET, SecretAdminError,
)
from app.ops.host_secret_controller import TerminalEvidence

TARGET = BUILDEROPS_ALERT_TARGET
IDENTITY = BUILDEROPS_ALERT_IDENTITY

# This fixed receiver is transported from reviewed source; it is not a new daemon.
REMOTE = r'''
import fcntl, json, os, re, socket, stat, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

ENGINE = '799a3d86-54f6-4208-b71a-36ae3eee61b6'
DOCKER = ['/usr/bin/docker', '-H', 'unix:///run/docker-builderops.sock']
DIRECTORY = Path('/etc/yggdrasil/credentials')
TARGET = DIRECTORY / 'builderops-discord.cred'
RECEIPTS = Path('/opt/builderops/receipts')
LOCK = Path('/tmp/agentic-pkm-mvp-builderops-lock/deployment.lock')

class DurabilityError(OSError):
    pass

def sync_directory(path):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(descriptor)
    except OSError:
        raise DurabilityError() from None
    finally:
        if descriptor is not None: os.close(descriptor)

def private(path, directory=False):
    info = path.lstat()
    if (info.st_uid != 0 or info.st_mode & 0o022
        or (not stat.S_ISDIR(info.st_mode) if directory else
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
        raise ValueError()
    return info

def preflight():
    if os.geteuid() != 0 or socket.gethostname() != 'builder-system':
        raise ValueError()
    for p in [Path('/etc'), Path('/etc/yggdrasil'), Path('/opt'),
              Path('/opt/builderops'), RECEIPTS]:
        private(p, True)
    identity = subprocess.run(DOCKER + ['info', '--format', '{{json .ID}}'],
        check=True, capture_output=True, timeout=10, text=True)
    if json.loads(identity.stdout) != ENGINE:
        raise ValueError()
    if not Path('/var/lib/systemd/credential.secret').is_file():
        raise ValueError()
    subprocess.run(['/usr/bin/systemd-creds', '--version'], check=True,
        capture_output=True, timeout=10)
    if DIRECTORY.exists() or DIRECTORY.is_symlink():
        if stat.S_IMODE(private(DIRECTORY, True).st_mode) != 0o700:
            raise ValueError()
    if TARGET.exists() or TARGET.is_symlink():
        if stat.S_IMODE(private(TARGET).st_mode) != 0o600:
            raise ValueError()

def replace(path, raw, mode):
    descriptor, name = tempfile.mkstemp(prefix='.builderops-alert-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name): os.unlink(name)

def main():
    action, operation_id = sys.argv[1:]
    preflight()
    if action == 'preflight':
        print('{"status":"ready"}')
        return
    if str(UUID(operation_id)) != operation_id:
        raise ValueError()
    receipt = RECEIPTS / ('builderops-alerts-' + operation_id + '.json')
    if action == 'receipt':
        private(receipt)
        # A prior acknowledgement can be lost during the receipt directory sync.
        # Re-establish durability before this read can become terminal evidence.
        descriptor = os.open(receipt, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            raw = os.read(descriptor, 2049)
            if len(raw) > 2048: raise ValueError()
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        sync_directory(RECEIPTS)
        print(raw.decode())
        return
    if action != 'apply' or receipt.exists() or receipt.is_symlink():
        raise ValueError()
    private(LOCK.parent, True)
    descriptor = os.open(LOCK, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError()
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight()
        value = sys.stdin.buffer.read(4097).decode()
        parsed = urlsplit(value)
        if (len(value) > 4096 or value != value.strip() or parsed.scheme != 'https'
            or parsed.netloc not in {'discord.com', 'discordapp.com'}
            or parsed.query or parsed.fragment
            or not re.fullmatch(r'/api/webhooks/[0-9]+/[A-Za-z0-9._-]+', parsed.path)):
            raise ValueError()
        previous = TARGET.read_bytes() if TARGET.exists() else None
        changed = False
        committed = False
        try:
            encrypted = subprocess.run(['/usr/bin/systemd-creds', 'encrypt',
                '--with-key=host', '--name=builderops-discord', '-', '-'],
                input=value.encode(), check=True, capture_output=True, timeout=20).stdout
            del value
            if not encrypted or len(encrypted) > 16384:
                raise ValueError()
            subprocess.run(['/usr/bin/systemd-creds', 'decrypt',
                '--name=builderops-discord', '-', '/dev/null'], input=encrypted,
                check=True, capture_output=True, timeout=20)
            if not DIRECTORY.exists():
                DIRECTORY.mkdir(mode=0o700)
                sync_directory(DIRECTORY.parent)
            changed = True
            replace(TARGET, encrypted, 0o600)
            private(TARGET)
            committed = True
        except Exception as error:
            if changed:
                if previous is None:
                    TARGET.unlink(missing_ok=True)
                    sync_directory(DIRECTORY)
                else: replace(TARGET, previous, 0o600)
            if isinstance(error, DurabilityError):
                raise
        result = dict(schema='builderops_alert_handoff.v1', operation_id=operation_id,
            kind='deploy', target='bob-1', result='committed' if committed else 'aborted',
            source='remote-terminal', engine_id=ENGINE, consumer='heimdal-builderops-alerts')
        replace(receipt, json.dumps(result, sort_keys=True).encode(), 0o600)
        print(json.dumps(result, sort_keys=True))
    finally:
        os.close(descriptor)

try:
    main()
except Exception:
    print('builderops alert handoff refused', file=sys.stderr)
    raise SystemExit(78)
'''


def valid_webhook(value: str) -> bool:
    from app.ops.host_secret_bootstrap import validate_secret_value
    return validate_secret_value("webhook", value)


def remote(action: str, operation_id: str = "-", value: str | None = None) -> dict[str, Any]:
    command = shlex.join(["/usr/bin/sudo", "-n", "/usr/bin/python3", "-I", "-B",
                          "-c", REMOTE, action, operation_id])
    environment = {key: os.environ[key] for key in ("HOME", "USER", "LOGNAME", "PATH")
                   if key in os.environ}
    try:
        result = subprocess.run([
            "/usr/bin/ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1", "-o",
            "ClearAllForwardings=yes", "-o", "ForwardAgent=no", "-o", "ControlMaster=no",
            "-o", "ControlPath=none", "-o", "PermitLocalCommand=no", "--",
            "bob-1-builder-system", command,
        ], input=value or "", text=True, capture_output=True, env=environment, timeout=60)
        if result.returncode or result.stderr or len(result.stdout) > 2048:
            raise SecretAdminError()
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise SecretAdminError()
        return data
    except Exception:
        raise SecretAdminError() from None


def terminal(data: dict[str, Any], operation_id: str) -> TerminalEvidence:
    expected = {"schema", "operation_id", "kind", "target", "result", "source",
                "engine_id", "consumer"}
    if (set(data) != expected or data["schema"] != "builderops_alert_handoff.v1"
        or data["operation_id"] != operation_id or data["kind"] != "deploy"
        or data["target"] != TARGET or data["result"] not in {"committed", "aborted"}
        or data["source"] != "remote-terminal"
        or data["engine_id"] != "799a3d86-54f6-4208-b71a-36ae3eee61b6"
        or data["consumer"] != "heimdal-builderops-alerts"):
        raise SecretAdminError()
    return TerminalEvidence(operation_id, "deploy", TARGET, data["result"], "remote-terminal")


def run(action: str, *, admin: Any = None) -> int:
    from app.ops.secret_admin import SecretAdmin
    if admin is None:
        from app.ops.postgres_deploy_host import _configured_host_admin
        admin = SecretAdmin(_configured_host_admin())
    if action == "reconcile":
        admin.controller.reconcile(
            lambda operation_id, kind, target: terminal(remote("receipt", operation_id), operation_id),
            expected=("deploy", TARGET, None))
        print('{"status":"reconciled"}')
        return 0
    if action in {"check", "preflight"}:
        with admin.controller.admit("check", TARGET) as operation:
            try:
                copy = admin.provider.read("non-prod", IDENTITY)
                valid = copy is not None and valid_webhook(copy.value)
                if action == "preflight" and remote("preflight") != {"status": "ready"}:
                    raise SecretAdminError()
                print(json.dumps({"status": "ok" if valid else "missing_or_invalid"}))
            finally:
                operation.finish(TerminalEvidence(operation.operation_id, "check", TARGET,
                                                 "committed", "read-complete"))
        return 0 if valid else 1
    if action != "apply":
        raise SecretAdminError()
    with admin.controller.deploy_operation(TARGET) as (operation, pending):
        if pending:
            raise SecretAdminError()
        copy = admin.provider.read("non-prod", IDENTITY)
        if copy is None or not valid_webhook(copy.value):
            raise SecretAdminError()
        operation.prepare_mutation()
        try:
            remote("apply", operation.operation_id, copy.value)
        except SecretAdminError:
            pass
        receipt = remote("receipt", operation.operation_id)
        operation.finish(terminal(receipt, operation.operation_id))
        print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["result"] == "committed" else 1
