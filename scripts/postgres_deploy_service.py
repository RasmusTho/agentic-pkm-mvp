#!/usr/bin/env python3
"""Operator-installed as /usr/local/libexec/yggdrasil-bws-deploy (root-owned)."""
import json
import os
from pathlib import Path
import stat
import sys


def run() -> int:
    try:
        action_counts = {
            'serve': 3,
            'rpc': 3,
            'guard': 3,
            'cleanup': 3,
            'token-push-inspect': 3,
            'token-push-status': 4,
            'token-push-worker': 5,
            'token-push': 6,
        }
        if (
            len(sys.argv) != action_counts.get(sys.argv[1], -1)
            or sys.argv[2] not in {'dev', 'test', 'prod'}
        ):
            return 78
        path = Path('/etc/yggdrasil/bws-deploy') / (sys.argv[2] + '.json')
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
                return 78
            root = Path(json.load(source)['root'])
        if not root.is_absolute() or root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o022:
            return 78
        os.chdir(root)
        sys.path.insert(0, str(root))
        from app.ops.postgres_deploy_linux import main
        return main(sys.argv[1:])
    except Exception:
        return 78


if __name__ == '__main__':
    raise SystemExit(run())
