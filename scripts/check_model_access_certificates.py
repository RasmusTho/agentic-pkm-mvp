#!/usr/bin/env python3
"""Check explicitly supplied public mTLS certificates; no live route is inferred."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, NoReturn

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

_BEGIN = b'-----BEGIN CERTIFICATE-----'
_END = b'-----END CERTIFICATE-----'
_BASE64 = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n')
_MAX_BYTES = 4096
_OPENSSL = '/usr/bin/openssl'


class Refused(Exception):
    """Inputs or verification could not be qualified."""


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink, info.st_mode)


class PublicFile:
    def __init__(self, path: str, stack: ExitStack) -> None:
        self.path = Path(path)
        self.fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        stack.callback(os.close, self.fd)
        info = os.fstat(self.fd)
        self.identity = _identity(info)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= _MAX_BYTES):
            raise Refused()
        remaining = info.st_size

        def read_input(count: int) -> bytes:
            nonlocal remaining
            if count > remaining:
                raise Refused()
            result = os.read(self.fd, count)
            remaining -= len(result)
            return result

        if read_input(len(_BEGIN)) != _BEGIN:
            raise Refused()
        # Stop at the certificate footer, then inspect trailing whitespace one
        # byte at a time. A second PEM block is refused before its body is read.
        data = bytearray(_BEGIN)
        while True:
            byte = read_input(1)
            if not byte or len(data) >= _MAX_BYTES:
                raise Refused()
            if byte == b'-':
                footer = byte + read_input(len(_END) - 1)
                if footer != _END:
                    raise Refused()
                data.extend(footer)
                break
            if byte[0] not in _BASE64:
                raise Refused()
            data.extend(byte)
        while remaining:
            trailing = read_input(1)
            if trailing not in (b' ', b'\t', b'\r', b'\n'):
                raise Refused()
        if os.read(self.fd, 1):
            raise Refused()
        self.pem = bytes(data) + b'\n'
        self.recheck()

    def recheck(self) -> None:
        named = os.stat(self.path, follow_symlinks=False)
        if _identity(os.fstat(self.fd)) != self.identity or _identity(named) != self.identity:
            raise Refused()


def _verify_chain(ca: bytes, leaf: bytes, purpose: str) -> None:
    """Verify only against the supplied CA; never capture raw tool output."""
    read_fd, write_fd = os.pipe()
    try:
        if os.write(write_fd, ca) != len(ca):
            raise Refused()
        os.close(write_fd)
        write_fd = -1
        result = subprocess.run(
            [_OPENSSL, 'verify', '-trusted', f'/dev/fd/{read_fd}', '-purpose', purpose], input=leaf, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            pass_fds=(read_fd,), check=False, timeout=5,
            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'},
        )
        if result.returncode != 0:
            raise Refused()
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def check_certificates(*, channel: str, server: str, client: str, ca: str,
                       server_ip: str, min_days: int, now: datetime | None = None) -> dict[str, Any]:
    """Return public-file evidence only, not consumer or runtime-health proof."""
    try:
        if channel not in {'dev', 'test'} or type(channel) is not str:
            raise Refused()
        if type(min_days) is not int or not 0 <= min_days <= 3650:
            raise Refused()
        address = ipaddress.ip_address(server_ip)
        current = now if now is not None else datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise Refused()
        with ExitStack() as stack:
            files = {name: PublicFile(path, stack) for name, path in
                     (('server', server), ('client', client), ('ca', ca))}
            certs = {name: x509.load_pem_x509_certificate(item.pem) for name, item in files.items()}
            for cert in certs.values():
                if (cert.not_valid_before_utc > current
                        or cert.not_valid_after_utc <= current + timedelta(days=min_days)):
                    raise Refused()
            san = certs['server'].extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            if address not in san.get_values_for_type(x509.IPAddress):
                raise Refused()
            _verify_chain(files['ca'].pem, files['server'].pem, 'sslserver')
            _verify_chain(files['ca'].pem, files['client'].pem, 'sslclient')
            for item in files.values():
                item.recheck()
            return {'status': 'valid_public_files', 'channel': channel,
                    'certificates': {name: {'sha256': hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest(),
                                            'not_after': cert.not_valid_after_utc.isoformat()}
                                     for name, cert in certs.items()}}
    except Exception:
        raise Refused() from None


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> NoReturn:
        raise Refused()


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    for argument in ('channel', 'server', 'client', 'ca', 'server-ip'):
        parser.add_argument('--' + argument, required=True)
    parser.add_argument('--min-days', type=int, default=30)
    try:
        args = parser.parse_args(argv)
        result = check_certificates(channel=args.channel, server=args.server, client=args.client,
                                    ca=args.ca, server_ip=args.server_ip, min_days=args.min_days)
    except Exception:
        print(json.dumps({'status': 'unqualified'}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
