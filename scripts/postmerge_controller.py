"""Stdlib-only startup boundary for the installed, reviewed controller pin."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY = 'RasmusTho/agentic-pkm-mvp'
ROOT = Path(__file__).resolve().parents[1]
# These are the real poller, native child and lazy receipt-validation producers.
REQUIRED_MODULES = (
    'scripts.postmerge_dev_test', 'app.ops.postgres_deploy_host',
    'app.ops.postgres_deploy_linux', 'app.ops.heavy_acceptance',
    'app.ops.native_source_bootstrap',
)


def self_check(sha: str) -> None:
    installation = ROOT.parent
    pin = json.loads((installation / 'pin.json').read_text())
    executable = installation / 'runtime/bin/python'
    if (re.fullmatch(r'[0-9a-f]{40}', sha) is None or installation.name != sha
        or ROOT.name != 'source' or pin != {
            'source_sha': sha, 'python_version': sys.version,
            'python_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
        } or Path(sys.executable).absolute() != executable
        or not sys.flags.isolated or not sys.flags.no_site):
        raise ValueError('tooling_identity_refused')
    # -I -S removes cwd, PYTHONPATH, user site and .pth execution. Only the
    # independently installed reviewed snapshot is added to the import path.
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    for name in REQUIRED_MODULES:
        importlib.import_module(name)
    for name, module in tuple(sys.modules.items()):
        if name.split('.')[0] not in {'app', 'scripts'}:
            continue
        origin = getattr(module, '__file__', None)
        if origin is not None and not Path(origin).resolve().is_relative_to(ROOT):
            raise ValueError('tooling_import_refused')


def report_startup_failure() -> None:
    # This path must keep working even when app or the controller cannot import.
    # The host retains only its existing repo-only Actions-write permission.
    result = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/git/ref/heads/main'],
                            capture_output=True, text=True, check=True, timeout=60)
    sha = json.loads(result.stdout)['object']['sha']
    if not isinstance(sha, str) or re.fullmatch(r'[0-9a-f]{40}', sha) is None:
        raise ValueError('liveness_identity_refused')
    payload = {'protocol': 'dev-delivery-liveness.v1', 'sha': sha,
               'observed_at': datetime.now(timezone.utc).isoformat(), 'startup': 'failed'}
    subprocess.run(['gh', 'workflow', 'run', 'dev-delivery-liveness.yml',
                    '--repo', REPOSITORY, '--ref', 'main', '-f', 'kind=heartbeat',
                    '-f', 'payload=' + json.dumps(payload, sort_keys=True)],
                   capture_output=True, check=True, timeout=60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tooling-sha', required=True)
    parser.add_argument('--self-check', action='store_true')
    args, controller_args = parser.parse_known_args(argv)
    try:
        self_check(args.tooling_sha)
    except Exception:
        signal = 'sent'
        try:
            report_startup_failure()
        except Exception:
            # Missing transport is also observable through the existing watchdog.
            signal = 'failed'
        print(json.dumps({'result': 'startup_self_check_failed', 'liveness_signal': signal}, sort_keys=True))
        return 78
    if args.self_check:
        print(json.dumps({'result': 'startup_self_check_passed', 'tooling_sha': args.tooling_sha}, sort_keys=True))
        return 0
    from scripts.postmerge_dev_test import main as controller_main
    return controller_main(controller_args)


if __name__ == '__main__':
    raise SystemExit(main())
