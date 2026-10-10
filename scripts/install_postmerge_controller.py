"""Install the existing private macOS host's post-merge poller without secrets.

The generated LaunchAgent stays host-local. Its checkout must be clean and
contained in reviewed main before installation; it is retained as tooling, not
updated from a candidate or a PR during deployment.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LABEL = 'se.yggdrasil.postmerge-dev-test'
REPOSITORY = 'RasmusTho/agentic-pkm-mvp'
CANONICAL_ORIGINS = {
    prefix + REPOSITORY + suffix
    for prefix in ('https://github.com/', 'git@github.com:', 'ssh://git@github.com/')
    for suffix in ('', '.git')
}


def launch_agent(checkout: Path, python: Path, gh: Path, state: Path) -> dict:
    return {
        'Label': LABEL,
        'ProgramArguments': [str(python), str(checkout / 'scripts/postmerge_dev_test.py'),
                             '--latest', '--state-directory', str(state)],
        'WorkingDirectory': str(checkout),
        'EnvironmentVariables': {'PATH': os.pathsep.join(dict.fromkeys(
            (str(python.parent), str(gh.parent), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin')))},
        'RunAtLoad': True,
        'StartInterval': 60,
        'ProcessType': 'Background',
        'StandardOutPath': str(state / 'controller.log'),
        'StandardErrorPath': str(state / 'controller.log'),
    }


def require_reviewed_checkout(checkout: Path, python: Path) -> None:
    def git(*arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(['git', '-C', str(checkout), *arguments], capture_output=True,
                              text=True, check=True, timeout=30)

    if (not checkout.is_absolute() or checkout.resolve() != checkout
        or not python.is_absolute() or not os.access(python, os.X_OK)
        or git('status', '--porcelain').stdout
        or not (checkout / 'scripts/postmerge_dev_test.py').is_file()):
        raise ValueError('reviewed checkout required')
    # get-url expands Git URL rewrites. Bind both effective authorities before
    # fetching or importing any code from the supplied checkout.
    for options in (('--all',), ('--push', '--all')):
        urls = git('remote', 'get-url', *options, 'origin').stdout.splitlines()
        if len(urls) != 1 or urls[0] not in CANONICAL_ORIGINS:
            raise ValueError('canonical reviewed repository required')
    git('fetch', '--no-tags', '--no-recurse-submodules', 'origin', 'refs/heads/main')
    # FETCH_HEAD is the requested remote main, independently of a stale or
    # locally forged origin/main and configured remote tracking refspecs.
    git('merge-base', '--is-ancestor', 'HEAD', 'FETCH_HEAD')
    # Resolve required host dependencies before creating or loading anything.
    subprocess.run([str(python), '-c',
                    'import app.ops.postgres_deploy_host; import app.ops.postgres_deploy_linux'],
                   cwd=checkout, capture_output=True, check=True, timeout=30)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--enable', action='store_true', help='load the installed host-local LaunchAgent')
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'darwin':
            raise ValueError('macOS host required')
        require_reviewed_checkout(args.checkout, args.python)
        gh = shutil.which('gh')
        if not gh:
            raise ValueError('GitHub read client required')
        state = Path.home() / '.local/state/yggdrasil/secret-controller/postmerge'
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        from scripts.postmerge_dev_test import checkpoint_lock
        with checkpoint_lock(state):
            log = state / 'controller.log'
            descriptor = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            os.close(descriptor)
            agents = Path.home() / 'Library/LaunchAgents'
            agents.mkdir(parents=True, exist_ok=True)
            path = agents / (LABEL + '.plist')
            if path.is_symlink():
                raise ValueError('LaunchAgent path refused')
            with path.open('wb') as target:
                os.chmod(path, 0o600)
                plistlib.dump(launch_agent(args.checkout, args.python, Path(gh), state), target)
            if args.enable:
                domain = 'gui/' + str(os.getuid())
                # Hold the poller's lock through replacement so a new poll
                # cannot start between configuration and bootout.
                result = subprocess.run(['/bin/launchctl', 'print', domain + '/' + LABEL],
                                        capture_output=True, check=False)
                if result.returncode == 0:
                    subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + LABEL],
                                   capture_output=True, check=True)
                subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(path)],
                               capture_output=True, check=True)
        print('post-merge controller ' + ('enabled' if args.enable else 'installed'))
        return 0
    except Exception:
        print('post-merge controller installation refused', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
