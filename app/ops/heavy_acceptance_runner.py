"""Disposable heavy-test effects on the ygg `test` VM (#6158).

The candidate runs in the admitted image with a network-none namespace, a
read-only root, dropped capabilities and a writable depth-1 Git checkout of
the exact candidate SHA at `/work`. The host Docker CLI and compose plugin are mounted
read-only without a socket so `docker compose config` tests execute instead of
skipping. Docker and Git object access stay in the trusted VM worker.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import Any

from app.ops.acceptance_memory import MemoryLimit
from app.ops.heavy_acceptance import (
    PROFILE_DEADLINE, RESULT_PREFIX, HeavyAcceptanceError, classify, identity,
)
from app.ops.pg_acceptance import IMAGE_REPOSITORY

COMPOSE_PLUGIN_PATHS = (
    '/usr/libexec/docker/cli-plugins/docker-compose',
    '/usr/lib/docker/cli-plugins/docker-compose',
    '/usr/local/lib/docker/cli-plugins/docker-compose',
)
CONTAINER_DOCKER = '/usr/local/bin/docker'
CONTAINER_COMPOSE = '/usr/local/lib/docker/cli-plugins/docker-compose'


def _command(argv: list[str], *, timeout: int = 60) -> bytes:
    # No HOME, credential helper, Docker context override or Git overlay.
    environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                   'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1'}
    try:
        result = subprocess.run(argv, env=environment, capture_output=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HeavyAcceptanceError('heavy_deadline_exceeded') from None
    except Exception:
        raise HeavyAcceptanceError('heavy_command_failed') from None
    if len(result.stdout) > 128 * 1024 * 1024:
        raise HeavyAcceptanceError('heavy_output_too_large')
    if result.returncode and argv[:3] != ['docker', 'start', '--attach']:
        raise HeavyAcceptanceError('heavy_command_failed')
    return result.stdout


def host_docker_cli() -> tuple[Path, Path]:
    docker = shutil.which('docker', path='/usr/local/bin:/usr/bin:/bin')
    compose = next((Path(p) for p in COMPOSE_PLUGIN_PATHS if Path(p).is_file()), None)
    if docker is None or compose is None:
        raise HeavyAcceptanceError('docker_cli_unavailable')
    return Path(docker).resolve(), compose.resolve()


class HeavyAcceptanceRunner:
    def __init__(self, repository: Path, journal_directory: Path, *, sha: str, digest: str,
                 channel: str, operation_id: str, memory_limit: MemoryLimit | None = None) -> None:
        self.identity = identity(sha, digest, channel, operation_id)
        self.memory_limit = memory_limit
        self.repository = repository
        self.name = 'ygg-heavy-' + channel + '-' + operation_id
        self.parent = journal_directory / 'heavy-acceptance'
        self.directory = self.parent / self.name
        self.image = IMAGE_REPOSITORY + ':' + sha + '@' + digest
        self.labels = {'io.yggdrasil.heavy.' + key: value for key, value in self.identity.items()}

    def _docker(self, *arguments: str, timeout: int = 60) -> bytes:
        return _command(['docker', *arguments], timeout=timeout)

    def _git(self, *arguments: str) -> bytes:
        return _command(['git', '-c', 'safe.directory=' + str(self.repository),
                         '-C', str(self.repository), *arguments])

    def _owned(self) -> dict[str, Any] | None:
        name = self.name + '-tests'
        observed = self._docker('container', 'ls', '--all', '--no-trunc', '--filter',
                                'name=^/' + name + '$', '--format', '{{.ID}}').decode().strip()
        if not observed:
            return None
        if re.fullmatch(r'[0-9a-f]{64}', observed) is None:
            raise HeavyAcceptanceError('heavy_cleanup_refused')
        rows = json.loads(self._docker('inspect', '--type', 'container', observed))
        row = rows[0] if isinstance(rows, list) and len(rows) == 1 else {}
        labels = row.get('Config', {}).get('Labels') or {}
        if (row.get('Id') != observed or row.get('Name') != '/' + name
            or any(labels.get(k) != v for k, v in self.labels.items())):
            raise HeavyAcceptanceError('heavy_cleanup_refused')
        return row

    def _require_private(self, path: Path) -> None:
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
            raise HeavyAcceptanceError('heavy_directory_unqualified')

    def cleanup(self) -> None:
        # Exact name plus every identity label; never a prefix or prune.
        row = self._owned()
        if row is not None:
            self._docker('rm', '--force', row['Id'])
            if self._owned() is not None:
                raise HeavyAcceptanceError('heavy_cleanup_refused')
        if self.directory.exists() or self.directory.is_symlink():
            self._require_private(self.directory)
            shutil.rmtree(self.directory)

    def _work_tree(self) -> tuple[Path, str]:
        revision = self.identity['source_sha']
        if self._git('rev-parse', revision + '^{commit}').decode().strip() != revision:
            raise HeavyAcceptanceError('heavy_candidate_missing')
        tree = self._git('rev-parse', revision + '^{tree}').decode().strip()
        if re.fullmatch(r'[0-9a-f]{40}', tree) is None:
            raise HeavyAcceptanceError('heavy_candidate_missing')
        # A depth-1 checkout of the exact SHA, like the GitHub-hosted run's
        # `actions/checkout`: suites that read the candidate's own Git
        # metadata (`git rev-parse HEAD`) see the candidate, not a bare tree.
        work = self.directory / 'work'
        work.mkdir(mode=0o700)

        def git(*arguments: str, timeout: int = 60) -> bytes:
            return _command(['git', '-c', 'safe.directory=' + str(work), '-C', str(work), *arguments],
                            timeout=timeout)

        git('init', '-q')
        git('fetch', '-q', '--depth', '1', '--no-tags', 'file://' + str(self.repository), revision, timeout=300)
        git('checkout', '-q', '--detach', revision)
        if (git('rev-parse', 'HEAD').decode().strip() != revision
            or git('rev-parse', 'HEAD^{tree}').decode().strip() != tree
            or git('status', '--porcelain').strip()):
            raise HeavyAcceptanceError('heavy_candidate_missing')
        if not (work / 'scripts/select_pr_tests.py').is_file():
            raise HeavyAcceptanceError('heavy_selector_unavailable')
        return work, tree

    def verify(self) -> dict[str, Any]:
        self.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._require_private(self.parent)
        lock = os.open(self.parent / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise HeavyAcceptanceError('heavy_run_in_progress') from None
            self.cleanup()
            try:
                return self._verify()
            finally:
                self.cleanup()
        finally:
            os.close(lock)

    def _verify(self) -> dict[str, Any]:
        images = json.loads(self._docker('image', 'inspect', self.image))
        image = images[0] if isinstance(images, list) and len(images) == 1 else {}
        if (image.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision')
                != self.identity['source_sha']
            or IMAGE_REPOSITORY + '@' + self.identity['image_digest'] not in image.get('RepoDigests', [])
            or re.fullmatch(r'sha256:[0-9a-f]{64}', str(image.get('Id'))) is None):
            raise HeavyAcceptanceError('heavy_image_unqualified')
        docker, compose = host_docker_cli()
        self.directory.mkdir(mode=0o700)
        work, tree = self._work_tree()
        manifest = self.directory / 'heavy-manifest.json'
        manifest.write_text(json.dumps({**self.identity, 'resource_tree': tree}, sort_keys=True))
        labels = [argument for key, value in self.labels.items() for argument in ('--label', key + '=' + value)]
        environment = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/work', 'HOME': '/tmp',
                       'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1', 'LANG': 'C.UTF-8'}
        container = self._docker(
            'create', '--name', self.name + '-tests', *labels,
            *(self.memory_limit.docker_args() if self.memory_limit is not None else []),
            '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--pids-limit', '4096', '--no-healthcheck', '--user', '0:0', '--workdir', '/work',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=2g',
            '--mount', f'type=bind,src={work},dst=/work',
            '--mount', f'type=bind,src={manifest},dst=/heavy-manifest.json,readonly',
            '--mount', f'type=bind,src={docker},dst={CONTAINER_DOCKER},readonly',
            '--mount', f'type=bind,src={compose},dst={CONTAINER_COMPOSE},readonly',
            '--entrypoint', '/usr/bin/env', self.image, '-i',
            *(key + '=' + value for key, value in environment.items()),
            'python', '-m', 'app.ops.heavy_acceptance', '--manifest', '/heavy-manifest.json',
        ).decode().strip()
        row = self._owned()
        config = (row or {}).get('HostConfig', {})
        if (row is None or row['Id'] != container or row.get('Image') != image['Id']
            or config.get('NetworkMode') != 'none' or config.get('Privileged')
            or config.get('ReadonlyRootfs') is not True or config.get('CapDrop') != ['ALL']
            or config.get('Binds') or config.get('PortBindings')
            or (self.memory_limit is not None and not self.memory_limit.applied(config))
            or any(m.get('Type') not in {'bind', 'tmpfs'} for m in row.get('Mounts', []))
            or any(str(m.get('Source', '')).endswith('docker.sock') for m in row.get('Mounts', []))):
            raise HeavyAcceptanceError('heavy_container_unqualified')
        output = self._docker('start', '--attach', container, timeout=PROFILE_DEADLINE).decode(errors='replace')
        finished = self._owned()
        state = (finished or {}).get('State', {})
        if (finished is None or finished['Id'] != container or not isinstance(state, dict)
            or (self.memory_limit is not None and not self.memory_limit.applied(finished.get('HostConfig')))
            or state.get('OOMKilled') is not False or type(state.get('ExitCode')) is not int
            or state.get('ExitCode') != 0 or state.get('Running') is not False):
            raise HeavyAcceptanceError('heavy_memory_or_process_failed')
        rows = [line for line in output.splitlines() if line.startswith(RESULT_PREFIX)]
        if len(rows) != 1 or rows[0] == RESULT_PREFIX + 'refused':
            raise HeavyAcceptanceError('heavy_evidence_refused')
        return classify(json.loads(rows[0][len(RESULT_PREFIX):]), self.identity)
