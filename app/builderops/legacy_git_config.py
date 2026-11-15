"""Bounded Git config screening for the coordinated legacy pickup only.

The operator must prevent config changes throughout the transition. This check
is not a lock and does not protect against direct or concurrent file writes.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
from pathlib import Path
import stat
import subprocess
import tempfile


QUALIFIED_COMMON = Path('/Users/rasmus/agentic-pkm-mvp/.git')


class ConfigError(ValueError):
    """Git configuration cannot safely be used for legacy pickup."""


def _read(path: Path, *, optional: bool = False) -> bytes | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if optional:
            return None
        raise ConfigError('Git configuration is unavailable') from None
    except OSError:
        raise ConfigError('Git configuration is unavailable') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            raise ConfigError('Git configuration is unsupported')
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(fd, min(65536, 1_000_001 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > 1_000_000:
                raise ConfigError('Git configuration is unsupported')
        return b''.join(chunks)
    finally:
        os.close(fd)


def _gitdir(root: Path) -> Path:
    if not root.is_absolute() or root != root.resolve(strict=True):
        raise ConfigError('Git checkout path is invalid')
    dot = root / '.git'
    if dot.is_symlink():
        raise ConfigError('Git directory is unsupported')
    if dot.is_dir():
        return dot.resolve(strict=True)
    raw = _read(dot)
    try:
        text = raw.decode('utf-8').strip() if raw is not None else ''
        if not text.startswith('gitdir: ') or '\n' in text:
            raise ConfigError('Git directory is unsupported')
        target = Path(text[8:])
        return (target if target.is_absolute() else root / target).resolve(strict=True)
    except (UnicodeError, OSError):
        raise ConfigError('Git directory is unavailable') from None


def _common(gitdir: Path) -> Path:
    raw = _read(gitdir / 'commondir', optional=True)
    if raw is None:
        return gitdir
    try:
        text = raw.decode('utf-8').strip()
        if not text or '\n' in text:
            raise ConfigError('Git common directory is unsupported')
        path = Path(text)
        return (path if path.is_absolute() else gitdir / path).resolve(strict=True)
    except (UnicodeError, OSError):
        raise ConfigError('Git common directory is unavailable') from None


def _qualified_credential_helper(key: bytes, value: bytes) -> bool:
    if key not in (b'credential.https://github.com.helper', b'credential.https://gist.github.com.helper'):
        return False
    if not value:
        return True
    # Restrict the shell expression to a literal absolute executable and two
    # fixed arguments. No shell metacharacter, expansion or quoting is needed.
    match = re.fullmatch(rb'!(/[A-Za-z0-9_./+-]+) auth git-credential', value)
    if match is None:
        return False
    executable = shutil.which('gh')
    if executable is None:
        return False
    try:
        return Path(os.fsdecode(match.group(1))).resolve(strict=True) == Path(executable).resolve(strict=True)
    except OSError:
        return False


def _screen(data: bytes, *, global_config: bool = False,
            absent_worktree_configs: bool = False) -> None:
    # Git parses bounded bytes on stdin in a neutral directory; never emit values.
    with tempfile.TemporaryDirectory(prefix='legacy-config-') as temp:
        try:
            result = subprocess.run(['git', 'config', '--no-includes', '--file', '-', '--null', '--list'],
                input=data, cwd=temp, env={'PATH': os.defpath, 'HOME': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
                               'GIT_CONFIG_GLOBAL': '/dev/null'}, capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            raise ConfigError('Git configuration cannot be checked') from None
        if result.returncode or len(result.stdout) > 2_000_000:
            raise ConfigError('Git configuration cannot be checked')
        for entry in result.stdout.split(b'\0'):
            if not entry:
                continue
            key, _, value = entry.partition(b'\n')
            key = key.lower()
            if global_config and _qualified_credential_helper(key, value):
                continue
            if global_config and key == b'credential.helper' and value in (b'', b'osxkeychain'):
                continue
            if (key.startswith((b'include.', b'includeif.', b'filter.', b'pager.'))
                    or key in {b'core.fsmonitor', b'core.hookspath', b'diff.external',
                               b'credential.helper', b'core.sshcommand', b'core.editor',
                               b'sequence.editor', b'core.attributesfile', b'core.excludesfile',
                               b'core.pager', b'interactive.difffilter'}
                    or key.endswith((b'.helper', b'.command', b'.process', b'.clean', b'.smudge', b'.program', b'.driver'))
                    or (key == b'extensions.worktreeconfig' and
                        (value.lower() not in (b'', b'true', b'yes', b'on', b'1', b'false', b'no', b'off', b'0')
                         or (not absent_worktree_configs
                             and value.lower() not in (b'false', b'no', b'off', b'0'))))):
                raise ConfigError('Git configuration contains unsupported directives')


def _check_environment() -> None:
    if any(key.startswith('GIT_') and key != 'GIT_PAGER' for key in os.environ):
        raise ConfigError('inherited Git environment is unsupported')


def check(*, cwd: Path, worktree: Path) -> None:
    """Screen both checkout configs; caller holds operator config quiescence."""
    _check_environment()
    try:
        common = QUALIFIED_COMMON
        if not common.is_absolute() or common != common.resolve(strict=True) or not common.is_dir():
            raise ConfigError('qualified Git common directory is unavailable')
        source, candidate = _gitdir(cwd), _gitdir(worktree)
        for directory in {source, candidate}:
            if directory != common and directory.parent != common / 'worktrees':
                raise ConfigError('linked worktree configuration is unsupported')
        for directory in {source, candidate}:
            if _common(directory) != common:
                raise ConfigError('Git checkout common directories differ')
            if _read(directory / 'config.worktree', optional=True) is not None:
                raise ConfigError('worktree configuration is unsupported')
        data = _read(common / 'config')
        if data is None:
            raise ConfigError('Git configuration is unavailable')
        _screen(data, absent_worktree_configs=True)
    except OSError:
        raise ConfigError('Git configuration is unavailable') from None


def check_host_config() -> None:
    """Qualify this host's normal global/system authority without changing it.

    The operator must also prevent changes to both files and Git's environment
    for the whole transition; this is not a fence against uncoordinated writers.
    """
    git = shutil.which('git')
    if git is None or Path(git).resolve() != Path('/usr/bin/git').resolve():
        raise ConfigError('host Git executable is unsupported')
    _check_environment()
    if Path.home() != Path('/Users/rasmus') or os.environ.get('XDG_CONFIG_HOME'):
        raise ConfigError('host Git configuration environment is unsupported')
    global_path = Path('/Users/rasmus/.gitconfig')
    system_path = Path('/etc/gitconfig')
    xdg_path = Path('/Users/rasmus/.config/git/config')
    if _read(system_path, optional=True) is not None or _read(xdg_path, optional=True) is not None:
        raise ConfigError('host Git configuration has changed')
    data = _read(global_path)
    if data is None:
        raise ConfigError('host Git configuration is unavailable')
    _screen(data, global_config=True)
    env = {'PATH': os.defpath, 'HOME': '/Users/rasmus', 'LC_ALL': 'C'}
    with tempfile.TemporaryDirectory(prefix='legacy-host-config-') as temp:
        try:
            version = subprocess.run(['/usr/bin/git', '--version'], cwd=temp, env=env,
                                     capture_output=True, timeout=10, check=False)
            system = subprocess.run(['/usr/bin/git', 'config', '--system', '--no-includes', '--list'],
                                    cwd=temp, env=env, capture_output=True, timeout=10, check=False)
            glob = subprocess.run(['/usr/bin/git', 'config', '--global', '--no-includes', '--list',
                                   '--show-origin', '--null'], cwd=temp, env=env,
                                  capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            raise ConfigError('host Git identity is unavailable') from None
        if (version.returncode or not version.stdout.startswith(b'git version 2.50.1 (Apple Git-')
                or system.returncode != 128 or b'/etc/gitconfig' not in system.stderr
                or b'No such file or directory' not in system.stderr
                or glob.returncode or len(glob.stdout) > 2_000_000):
            raise ConfigError('host Git identity or configuration has changed')
        fields = glob.stdout.split(b'\0')
        if not fields or fields[-1] != b'' or len(fields) % 2 != 1:
            raise ConfigError('host Git configuration is unsupported')
        if any(origin != b'file:/Users/rasmus/.gitconfig' for origin in fields[:-1:2]):
            raise ConfigError('host Git configuration origin has changed')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--worktree', type=Path, required=True)
    args = parser.parse_args()
    try:
        check_host_config()
        check(cwd=args.cwd, worktree=args.worktree)
    except (ConfigError, OSError):
        print('legacy Git configuration precheck failed')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
