"""Demerzel-only BWS handoff to the existing BOB-1 DevUI gh config.

No VM BWS account, token environment, arbitrary target, or container recreation.
Unknown SSH outcomes stay pending until an exact durable remote receipt is read.
"""
from __future__ import annotations

import json
from io import StringIO
import os
import shlex
import subprocess
from typing import Any, TextIO

from app.ops.bws_secret_admin import (
    DEVUI_IDENTITY, DEVUI_SECRET, DEVUI_TARGET, SecretAdminError, valid_devui_token,
)
from app.ops.host_secret_controller import TerminalEvidence

# Executed from reviewed source, not installed as a second administrative writer.
# stdin is the sole value-bearing transport; neither script nor arguments contain it.
REMOTE = r'''
import fcntl, json, os, re, stat, subprocess, sys, tempfile, urllib.request
from pathlib import Path
from uuid import UUID

BASE = Path('/opt/builderops/devui-gh')
HOSTS = BASE / 'hosts.yml'
RECEIPTS = Path('/opt/builderops/receipts')
CONTAINER = 'builderops-devui-devui-1'
DOCKER = ['/usr/bin/docker', '-H', 'unix:///run/docker-builderops.sock']
REPO = 'RasmusTho/agentic-pkm-mvp'
ROUTES = ['repos/' + REPO, 'repos/' + REPO + '/issues?per_page=1',
          'repos/' + REPO + '/pulls?per_page=1',
          'repos/' + REPO + '/branches?per_page=1',
          'repos/' + REPO + '/commits/main/status']

def docker(*args):
    r = subprocess.run(DOCKER + list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=40, check=True)
    return r.stdout

def preflight():
    if os.geteuid() != 0:
        raise ValueError()
    for p in (Path('/opt'), BASE.parent, BASE, HOSTS, RECEIPTS):
        s = p.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise ValueError()
    s = HOSTS.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or stat.S_IMODE(s.st_mode) != 0o640:
        raise ValueError()
    rows = json.loads(docker('inspect', CONTAINER))
    if len(rows) != 1:
        raise ValueError()
    d = rows[0]
    e = dict(v.split('=', 1) for v in d['Config']['Env'])
    mounts = [m for m in d['Mounts'] if m['Destination'] == '/run/builderops/devui-gh']
    if (e.get('GH_CONFIG_DIR') != '/run/builderops/devui-gh'
        or e.get('GH_HOST') != 'github.com' or e.get('DEVUI_REPOSITORY') != REPO
        or any(k in e for k in ('GH_TOKEN', 'GITHUB_TOKEN'))
        or len(mounts) != 1 or mounts[0]['Source'] != str(BASE)
        or mounts[0]['Type'] != 'bind' or mounts[0]['RW']
        or not d['State']['Running']):
        raise ValueError()
    return d['Id']

def replace(data):
    info = HOSTS.stat()
    fd, name = tempfile.mkstemp(prefix='.hosts-', dir=BASE)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fchown(f.fileno(), info.st_uid, info.st_gid)
            os.fchmod(f.fileno(), stat.S_IMODE(info.st_mode))
            os.fsync(f.fileno())
        os.replace(name, HOSTS)
        d = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if os.path.exists(name): os.unlink(name)

def updated(original, token):
    # Keep every other byte, including other hosts and gh's account metadata.
    lines = original.decode().splitlines(keepends=True)
    stack = []
    found = {}
    active_user = None
    for i, line in enumerate(lines):
        match = re.match(r'^( *)([^\s:#]+):(?:\s+(.*?))?\s*$', line.rstrip('\n'))
        if not match: raise ValueError()
        indent, key, value = match.groups()
        while stack and stack[-1][0] >= len(indent): stack.pop()
        path = tuple(item[1] for item in stack) + (key,)
        if path == ('github.com', 'user'): active_user = value
        if key == 'oauth_token':
            if path in found: raise ValueError()
            found[path] = (i, indent)
        stack.append((len(indent), key))
    paths = [('github.com', 'oauth_token'),
             ('github.com', 'users', 'RasmusTho', 'oauth_token')]
    if active_user != 'RasmusTho' or any(p not in found for p in paths): raise ValueError()
    for path in paths:
        i, indent = found[path]
        lines[i] = indent + 'oauth_token: ' + token + '\n'
    return ''.join(lines).encode()

def record(receipt, operation_id, container_id, committed):
    result = {'operation_id': operation_id, 'kind': 'deploy', 'target': 'bob-1',
              'result': 'committed' if committed else 'aborted', 'source': 'remote-terminal',
              'container_id': container_id, 'github_reads': 'passed' if committed else 'failed'}
    fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(result, f, sort_keys=True)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    d = os.open(RECEIPTS, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(d)
    finally: os.close(d)
    print(json.dumps(result, sort_keys=True))

def main():
    action, operation_id = sys.argv[1:]
    container_id = preflight()
    if action == 'preflight':
        updated(HOSTS.read_bytes(), 'github_pat_preflight_placeholder_1234567890')
        print(json.dumps({'status': 'ready', 'container_id': container_id}))
        return
    if str(UUID(operation_id)) != operation_id: raise ValueError()
    receipt = RECEIPTS / ('devui-github-token-' + operation_id + '.json')
    if action == 'receipt':
        fd = os.open(receipt, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r') as f:
            s = os.fstat(f.fileno())
            if (not stat.S_ISREG(s.st_mode) or s.st_uid != 0
                or s.st_mode & 0o077 or s.st_nlink != 1 or s.st_size > 2048):
                raise ValueError()
            data = json.load(f)
            # A previous writer can leave parseable JSON before either fsync.
            # Re-establish both barriers under the same remote lock before it
            # becomes terminal authority, including after acknowledgement loss.
            os.fsync(f.fileno())
        d = os.open(RECEIPTS, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(d)
        finally: os.close(d)
        print(json.dumps(data, sort_keys=True))
        return
    if action != 'apply' or receipt.exists(): raise ValueError()
    token = sys.stdin.read(4097)
    if not re.fullmatch(r'(?:github_pat_|ghp_)[A-Za-z0-9_]{20,255}', token):
        record(receipt, operation_id, container_id, False)
        return
    # Real read checks before replacing the only active source. Response bodies
    # and HTTP exceptions are kept out of stdout/stderr.
    try:
        for route in ROUTES:
            req = urllib.request.Request('https://api.github.com/' + route,
                  headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'devui-secret-admin',
                           'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(req, timeout=20) as response:
                if response.status != 200: raise ValueError()
        original = HOSTS.read_bytes()
        candidate = updated(original, token)
    except Exception:
        record(receipt, operation_id, container_id, False)
        return
    replace(candidate)
    try:
        if preflight() != container_id: raise ValueError()
        for route in ROUTES:
            docker('exec', CONTAINER, 'gh', 'api', route, '--jq', 'type')
    except Exception:
        replace(original)
        record(receipt, operation_id, container_id, False)
        return
    # Durable, value-free terminal evidence; no old/new token or token digest.
    record(receipt, operation_id, container_id, True)

try:
    lock = os.open('/run/lock/builderops-devui-github.lock',
                   os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        main()
except Exception:
    print('DevUI credential operation refused', file=sys.stderr)
    sys.exit(1)
'''


def _remote(action: str, operation_id: str = '-', value: str | None = None) -> dict[str, Any]:
    command = shlex.join(['/usr/bin/sudo', '-n', '/usr/bin/python3', '-I', '-B',
                          '-c', REMOTE, action, operation_id])
    environment = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'PATH', 'SSH_AUTH_SOCK')
                   if k in os.environ}
    try:
        result = subprocess.run([
            '/usr/bin/ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=10', '-o', 'ConnectionAttempts=1',
            '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no',
            '--', 'bob-1-builder-system', command,
        ], input=value or '', text=True, capture_output=True, env=environment, timeout=240)
        if result.returncode or result.stderr or len(result.stdout) > 2048:
            raise SecretAdminError()
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise SecretAdminError()
        return data
    except Exception:
        raise SecretAdminError() from None


def _terminal(data: dict[str, Any], operation_id: str) -> TerminalEvidence:
    if (set(data) != {'operation_id', 'kind', 'target', 'result', 'source',
                      'container_id', 'github_reads'}
        or data['operation_id'] != operation_id or data['kind'] != 'deploy'
        or data['target'] != DEVUI_TARGET or data['result'] not in {'committed', 'aborted'}
        or data['source'] != 'remote-terminal'
        or data['github_reads'] != ('passed' if data['result'] == 'committed' else 'failed')):
        raise SecretAdminError()
    return TerminalEvidence(operation_id, 'deploy', DEVUI_TARGET, data['result'], 'remote-terminal')


def run_devui(action: str, *, source: TextIO, stdin_requested: bool,
              admin: Any = None) -> int:
    from app.ops.secret_admin import SecretAdmin
    if stdin_requested != (action == 'import'):
        raise SecretAdminError()
    if admin is None:
        # Existing discovery reads value-free channel metadata, then the admin
        # bearer directly from Demerzel's login Keychain through Security.framework.
        from app.ops.postgres_deploy_host import _configured_host_admin
        admin = SecretAdmin(_configured_host_admin())
    if action == 'rotate':
        import getpass
        import warnings
        # Refuse getpass's echoed-stdin fallback, even if a terminal loses its
        # echo-control capability. The caller must use a local interactive TTY.
        descriptor = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
        os.close(descriptor)
        run_devui('preflight', source=source, stdin_requested=False, admin=admin)
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            value = getpass.getpass('Regenerated DevUI GitHub token (hidden): ')
        run_devui('import', source=StringIO(value), stdin_requested=True, admin=admin)
        del value
        return run_devui('apply', source=source, stdin_requested=False, admin=admin)
    if action == 'import':
        # SecretAdmin supplies the existing protected history and unknown-send gate.
        admin.import_stdin(DEVUI_TARGET, DEVUI_SECRET, source)
        print(json.dumps({'status': 'imported'}))
        return 0
    if action == 'reconcile':
        admin.controller.reconcile(
            lambda operation_id, kind, target: _terminal(_remote('receipt', operation_id), operation_id),
            expected=('deploy', DEVUI_TARGET, None))
        print(json.dumps({'status': 'reconciled'}))
        return 0
    if action in {'check', 'preflight'}:
        with admin.controller.admit('check', DEVUI_TARGET) as op:
            try:
                copy = admin.provider.read('non-prod', DEVUI_IDENTITY)
                status = 'missing' if copy is None else (
                    'ok' if valid_devui_token(copy.value) else 'invalid')
                if action == 'preflight':
                    data = _remote('preflight')
                    if data.get('status') != 'ready':
                        raise SecretAdminError()
                print(json.dumps({'secret': DEVUI_IDENTITY, 'status': status,
                                  'runtime': 'ready' if action == 'preflight' else 'unchecked'}))
            finally:
                op.finish(TerminalEvidence(op.operation_id, op.kind, op.target,
                                           'committed', 'read-complete'))
        return 0 if status == 'ok' or action == 'preflight' else 1
    if action != 'apply':
        raise SecretAdminError()
    with admin.controller.deploy_operation(DEVUI_TARGET) as (op, pending):
        if pending:
            raise SecretAdminError()
        copy = admin.provider.read('non-prod', DEVUI_IDENTITY)
        if copy is None or not valid_devui_token(copy.value):
            raise SecretAdminError()
        op.prepare_mutation()
        try:
            _remote('apply', op.operation_id, copy.value)
        except SecretAdminError:
            pass  # Lost acknowledgement is resolved only by the receipt below.
        # Only the durable receipt is terminal authority, even after successful RPC.
        receipt = _remote('receipt', op.operation_id)
        op.finish(_terminal(receipt, op.operation_id))
        print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt['result'] == 'committed' else 1
