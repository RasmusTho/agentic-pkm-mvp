"""Install the existing private macOS host's post-merge poller without secrets.

The generated LaunchAgent stays host-local. Its checkout must be clean and
contained in reviewed main before installation; its exact source is archived
into a separate tooling pin with an isolated stdlib runtime. Candidates never
update that pin.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LABEL = 'se.yggdrasil.postmerge-dev-test'
REPOSITORY = 'RasmusTho/agentic-pkm-mvp'
CANONICAL_ORIGINS = {
    prefix + REPOSITORY + suffix
    for prefix in ('https://github.com/', 'git@github.com:', 'ssh://git@github.com/')
    for suffix in ('', '.git')
}


def launch_agent(checkout: Path, python: Path, gh: Path, state: Path, sha: str) -> dict:
    return {
        'Label': LABEL,
        'ProgramArguments': [str(python), '-I', '-S', str(checkout / 'scripts/postmerge_controller.py'),
                             '--tooling-sha', sha, '--latest', '--state-directory', str(state)],
        'WorkingDirectory': str(checkout),
        'EnvironmentVariables': {'PATH': os.pathsep.join(dict.fromkeys(
            (str(python.parent), str(gh.parent), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin')))},
        'RunAtLoad': True,
        'StartInterval': 60,
        'ProcessType': 'Background',
        'StandardOutPath': str(state / 'controller.log'),
        'StandardErrorPath': str(state / 'controller.log'),
    }


def require_reviewed_checkout(checkout: Path, python: Path) -> str:
    git_environment = {key: os.environ[key] for key in
                       ('HOME', 'USER', 'LOGNAME', 'PATH', 'SSH_AUTH_SOCK') if key in os.environ}
    # Verify the stored commit graph, not local replacement/graft overlays or
    # an ambient GIT_DIR/GIT_WORK_TREE selecting another checkout.
    git_environment['GIT_GRAFT_FILE'] = os.devnull
    def git(*arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(['git', '--no-replace-objects', '-C', str(checkout), *arguments],
                              env=git_environment, capture_output=True,
                              text=True, check=True, timeout=30)

    if (not checkout.is_absolute() or checkout.resolve() != checkout
        or not python.is_absolute() or not os.access(python, os.X_OK)
        or git('status', '--porcelain').stdout
        or not (checkout / 'scripts/postmerge_dev_test.py').is_file()):
        raise ValueError('reviewed checkout required')
    if any(line[0].islower() or line[0] == 'S'
           for line in git('ls-files', '-v').stdout.splitlines()):
        raise ValueError('unmasked reviewed checkout required')
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
    subprocess.run([str(python), '-I', '-S', '-c',
                    'import sys; sys.path.insert(0, sys.argv[1]); '
                    'import app.ops.postgres_deploy_host; import app.ops.postgres_deploy_linux',
                    str(checkout)], cwd=checkout, capture_output=True, check=True, timeout=30)
    return git('rev-parse', 'HEAD').stdout.strip()


def install_tooling(checkout: Path, python: Path, state: Path, sha: str) -> tuple[Path, Path]:
    """Retain reviewed bytes and a private stdlib runtime; never follow a candidate."""
    tooling = state / 'tooling'
    tooling.mkdir(mode=0o700, exist_ok=True)
    if tooling.is_symlink():
        raise ValueError('tooling directory refused')
    installation = tooling / sha
    if not installation.exists():
        # Publish the complete installation atomically. An interrupted producer
        # never leaves a partial pin that a later LaunchAgent can mistake as ready.
        with tempfile.TemporaryDirectory(prefix='.install-', dir=tooling) as temporary:
            staging = Path(temporary) / sha
            source = staging / 'source'
            source.mkdir(parents=True, mode=0o700)
            environment = {key: os.environ[key] for key in ('HOME', 'PATH') if key in os.environ}
            environment['GIT_GRAFT_FILE'] = os.devnull
            archive = subprocess.run(['git', '--no-replace-objects', '-C', str(checkout),
                                      'archive', '--format=tar', sha], env=environment,
                                     capture_output=True, check=True, timeout=60)
            with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
                # Reviewed source needs no links or special files. Do not allow
                # extraction outside the installation even for a future archive.
                if any(not (member.isdir() or member.isfile()) for member in bundle.getmembers()):
                    raise ValueError('tooling archive refused')
                bundle.extractall(source, filter='data')
            runtime = staging / 'runtime'
            subprocess.run([str(python), '-I', '-S', '-m', 'venv', '--without-pip', '--copies', str(runtime)],
                           capture_output=True, check=True, timeout=60)
            executable = runtime / 'bin/python'
            version = subprocess.run([str(executable), '-I', '-S', '-c', 'import sys; print(sys.version)'],
                                     capture_output=True, text=True, check=True, timeout=30).stdout.strip()
            (staging / 'pin.json').write_text(json.dumps({
                'source_sha': sha, 'python_version': version,
                'python_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            }, sort_keys=True))
            os.rename(staging, installation)
    source = installation / 'source'
    executable = installation / 'runtime/bin/python'
    # Check the actual installed entrypoint/runtime, including retained pins,
    # before replacing or enabling the LaunchAgent.
    subprocess.run([str(executable), '-I', '-S', str(source / 'scripts/postmerge_controller.py'),
                    '--tooling-sha', sha, '--self-check'], capture_output=True, check=True, timeout=60)
    return source, executable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--enable', action='store_true', help='load the installed host-local LaunchAgent')
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'darwin':
            raise ValueError('macOS host required')
        sha = require_reviewed_checkout(args.checkout, args.python)
        gh = shutil.which('gh')
        if not gh:
            raise ValueError('GitHub read client required')
        state = Path.home() / '.local/state/yggdrasil/secret-controller/postmerge'
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        from scripts.postmerge_dev_test import checkpoint_lock
        with checkpoint_lock(state):
            tooling, runtime = install_tooling(args.checkout, args.python, state, sha)
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
                plistlib.dump(launch_agent(tooling, runtime, Path(gh), state, sha), target)
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
