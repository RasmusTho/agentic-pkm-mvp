"""Explicit same-operator CKM export to the fixed private BOB-1 DevUI source."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import shlex
import subprocess
from typing import Any

from app.builderops.ckm.contracts import ResultEnvelope, canonical_json
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.config import load_paths
from app.builderops.devui_ckm_snapshot import build_private_snapshot, decode_private_snapshot

REPOSITORY = "rasmustho/agentic-pkm-mvp"

# Reviewed fixed receiver. Source bytes travel only through stdin. Validation
# executes as the actual non-root consumer before any host file is replaced.
REMOTE = r'''
import fcntl, json, os, socket, stat, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

BASE = Path('/opt/builderops/receipts')
TARGET = BASE / 'devui-ckm-capabilities.json'
MAX_BYTES = 8 * 1024 * 1024
DOCKER = ['/usr/bin/docker', '-H', 'unix:///run/docker-builderops.sock']
VALIDATE = """
import os, sys
from app.builderops.devui_ckm_snapshot import decode_private_snapshot
if os.geteuid() != 100 or os.getegid() != 101:
    raise ValueError('Consumer identity differs')
if os.environ['DEVUI_VM102_RECEIPT_DIR'] != '/run/builderops/devui-receipts':
    raise ValueError('Consumer receipt source differs')
value = decode_private_snapshot(sys.stdin.buffer.read(), repository=os.environ['DEVUI_REPOSITORY'])
if value.transfer['repository'] != 'rasmustho/agentic-pkm-mvp':
    raise ValueError('Consumer repository differs')
"""
READBACK = """
import os, sys
from pathlib import Path
from app.builderops.ckm.contracts import ResultEnvelope
from app.builderops.devui_ckm_snapshot import read_private_ckm
if os.geteuid() != 100 or os.getegid() != 101:
    raise ValueError('Consumer identity differs')
if os.environ['DEVUI_VM102_RECEIPT_DIR'] != '/run/builderops/devui-receipts':
    raise ValueError('Consumer receipt source differs')
value = read_private_ckm(Path('/run/builderops/devui-receipts'), repository=os.environ['DEVUI_REPOSITORY'])
if not isinstance(value.result, ResultEnvelope) or value.transfer is None:
    raise ValueError('Consumer refused the published snapshot')
if value.transfer['repository'] != 'rasmustho/agentic-pkm-mvp' or value.transfer['content_sha256'] != sys.argv[1]:
    raise ValueError('Consumer readback differs')
"""

try:
    if os.geteuid() != 0 or socket.gethostname() != 'builder-system':
        raise ValueError()
    for path in (Path('/opt'), BASE.parent, BASE):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError()
    mounts = json.loads(subprocess.run(
        DOCKER + ['inspect', '--format', '{{json .Mounts}}', 'builderops-devui-devui-1'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=True).stdout)
    selected = [mount for mount in mounts if mount['Destination'] == '/run/builderops/devui-receipts']
    if len(selected) != 1 or selected[0]['Source'] != str(BASE) or selected[0]['RW'] or selected[0]['Type'] != 'bind':
        raise ValueError()
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError()
    subprocess.run(DOCKER + ['exec', '-i', 'builderops-devui-devui-1', 'python', '-c', VALIDATE],
                   input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
    value = json.loads(raw)
    lock = os.open(BASE / '.devui-ckm-publish.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if TARGET.exists() or TARGET.is_symlink():
            info = TARGET.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o640 or info.st_gid != 101:
                raise ValueError()
            with TARGET.open('rb') as stream:
                previous_raw = stream.read(MAX_BYTES + 1)
            if len(previous_raw) > MAX_BYTES:
                raise ValueError()
            try:
                previous = json.loads(previous_raw)
                old_time = datetime.fromisoformat(previous['captured_at'])
                new_time = datetime.fromisoformat(value['captured_at'])
            except (ValueError, KeyError, TypeError):
                previous = None
            if previous is not None and (old_time > new_time or (old_time == new_time and previous != value)):
                raise ValueError()
        fd, name = tempfile.mkstemp(prefix='.devui-ckm-', dir=BASE)
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchown(stream.fileno(), 0, 101)
                os.fchmod(stream.fileno(), 0o640)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, TARGET)
            directory = os.open(BASE, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)
        with TARGET.open('rb') as stream:
            written = stream.read(MAX_BYTES + 1)
        if written != raw:
            raise ValueError()
        subprocess.run(DOCKER + ['exec', '-i', 'builderops-devui-devui-1', 'python', '-c',
                                 READBACK, value['content_sha256']],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=True)
    finally:
        os.close(lock)
    print(json.dumps({'status': 'published', 'content_sha256': value['content_sha256'],
                      'capability_count': len(value['result']['resources'])}))
except Exception:
    raise SystemExit('Private CKM publication refused; inspect the fixed source before retrying') from None
'''


def export_snapshot() -> bytes:
    """The existing implicit host-store admission chooses the source; no new selector."""
    result = CkmQueryService(load_paths().db_path).list_capabilities()
    if not isinstance(result, ResultEnvelope):
        raise ValueError("Local CKM query refused; no snapshot was published")
    value = build_private_snapshot(result, repository=REPOSITORY, captured_at=datetime.now(timezone.utc))
    return canonical_json(value).encode("utf-8")


def publish_snapshot(raw: bytes) -> dict[str, Any]:
    read = decode_private_snapshot(raw, repository=REPOSITORY)
    command = shlex.join(["sudo", "-n", "python3", "-c", REMOTE])
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--",
         "bob-1-builder-system", command],
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=True,
    )
    receipt = json.loads(result.stdout)
    if (not isinstance(receipt, dict)
            or set(receipt) != {"status", "content_sha256", "capability_count"}
            or receipt["status"] != "published"
            or read.transfer is None
            or receipt["content_sha256"] != read.transfer["content_sha256"]
            or not isinstance(read.result, ResultEnvelope)
            or type(receipt["capability_count"]) is not int
            or receipt["capability_count"] != len(read.result.resources)):
        raise ValueError("Private CKM publication readback differs")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "publish"))
    args = parser.parse_args()
    try:
        raw = export_snapshot()
        if args.action == "export":
            print(raw.decode())
        else:
            print(json.dumps(publish_snapshot(raw), sort_keys=True))
    except Exception:
        parser.exit(1, "Private CKM export/publication failed; no successful source claim. Reconcile the fixed file before retrying.\n")
    return 0
