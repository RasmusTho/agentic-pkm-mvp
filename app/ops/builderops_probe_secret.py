"""One-service bridge from a systemd encrypted credential to Heimdal's runtime file."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import re
from urllib.parse import urlsplit

CREDENTIAL = Path('/run/credentials/yggdrasil-builderops-probe.service/builderops-discord')
DIRECTORY = Path('/run/yggdrasil-builderops-probe')
RUNTIME = DIRECTORY / 'alerts.env'


def _metadata(path: Path, mode: int, *, directory: bool = False) -> None:
    info = path.lstat()
    if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode
        or (not stat.S_ISDIR(info.st_mode) if directory else
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
        raise ValueError()


def materialize() -> None:
    _metadata(DIRECTORY, 0o700, directory=True)
    descriptor = os.open(CREDENTIAL, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o400 or info.st_nlink != 1):
            raise ValueError()
        value = os.read(descriptor, 4097).decode()
    finally:
        os.close(descriptor)
    parsed = urlsplit(value)
    if (len(value) > 4096 or value != value.strip() or parsed.scheme != 'https'
        or parsed.netloc not in {'discord.com', 'discordapp.com'}
        or parsed.query or parsed.fragment
        or not re.fullmatch(r'/api/webhooks/[0-9]+/[A-Za-z0-9._-]+', parsed.path)):
        raise ValueError()
    if RUNTIME.exists() or RUNTIME.is_symlink():
        _metadata(RUNTIME, 0o600)
    descriptor, name = tempfile.mkstemp(prefix='.alerts-', dir=DIRECTORY)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write('DISCORD_WEBHOOK=' + value + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, RUNTIME)
    finally:
        Path(name).unlink(missing_ok=True)


def cleanup() -> None:
    _metadata(DIRECTORY, 0o700, directory=True)
    if RUNTIME.exists() or RUNTIME.is_symlink():
        _metadata(RUNTIME, 0o600)
        RUNTIME.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('materialize', 'cleanup'))
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'linux' or os.geteuid() != 0 or socket.gethostname() != 'builder-system':
            raise ValueError()
        if args.action == 'materialize':
            materialize()
        else:
            cleanup()
        return 0
    except Exception:
        print('builderops alert runtime refused', file=sys.stderr)
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
