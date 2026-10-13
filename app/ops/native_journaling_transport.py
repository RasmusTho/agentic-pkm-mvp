"""Finite native TLS byte relay, not a Product client/provider replacement.

The candidate keeps the configured private-IP endpoint and original mTLS. Its
network-none namespace has only an operation-local /32 loopback alias; only
this native-owned listener can reach the one configured remote executor.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
import ipaddress
import os
from pathlib import Path
import select
import socket
from threading import Event, Thread
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.ops.native_web_acceptance import NativeWebRefusal
from app.ops.pg_acceptance_runner import _command

MAX_CONNECTIONS = 64
MAX_BYTES = 64 * 1024 * 1024
DEADLINE = 1800
REFERENCE_FILE = Path('/etc/yggdrasil/model-access/runtime.env')
REFERENCE_KEYS = ('MODEL_ACCESS_CODEX_VLAN_ENDPOINT', 'MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE',
                  'MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT', 'MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY')


def process_identity(pid: int) -> dict[str, Any] | None:
    """Read-only Linux owner identity; never use a PID to kill or authorize effects."""
    if type(pid) is not int or pid < 1:
        raise NativeWebRefusal('native_provider_owner_identity_unknown')
    try:
        boot = str(UUID(Path('/proc/sys/kernel/random/boot_id').read_text().strip()))
        fields = Path('/proc/' + str(pid) + '/stat').read_text().rsplit(') ', 1)[1].split()
        started = fields[19]
        if not started.isdecimal():
            raise ValueError()
        return {'pid': pid, 'boot_id': boot, 'start_ticks': started}
    except FileNotFoundError:
        # Only an absent exact proc entry proves that owner no longer exists.
        if Path('/proc/sys/kernel/random/boot_id').exists():
            return None
        raise NativeWebRefusal('native_provider_owner_identity_unknown') from None
    except Exception:
        raise NativeWebRefusal('native_provider_owner_identity_unknown') from None


def owner_alive(proof: Any) -> bool:
    if (not isinstance(proof, dict) or set(proof) != {'pid', 'boot_id', 'start_ticks'}
        or type(proof['pid']) is not int or proof['pid'] < 1
        or not isinstance(proof['start_ticks'], str) or not proof['start_ticks'].isdecimal()):
        raise NativeWebRefusal('native_provider_owner_identity_unknown')
    try:
        if str(UUID(proof['boot_id'])) != proof['boot_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise NativeWebRefusal('native_provider_owner_identity_unknown') from None
    return process_identity(proof['pid']) == proof


def selected_references() -> dict[str, str]:
    """The existing protected four-key file only; no shell/env/provider override."""
    try:
        if REFERENCE_FILE.is_symlink():
            raise ValueError()
        metadata = REFERENCE_FILE.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022 or metadata.st_size > 65536:
            raise ValueError()
        values = {}
        for line in REFERENCE_FILE.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, separator, value = line.partition('=')
            if not separator or key not in REFERENCE_KEYS or key in values or not value:
                raise ValueError()
            values[key] = value
        if set(values) != set(REFERENCE_KEYS):
            raise ValueError()
        endpoint = urlsplit(values[REFERENCE_KEYS[0]])
        address = ipaddress.ip_address(endpoint.hostname or '')
        if (endpoint.scheme != 'https' or address.version != 4 or not address.is_private
            or address.is_loopback or address.is_unspecified or address.is_multicast
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or endpoint.path not in {'', '/'} or endpoint.port in {5432, 8000, 8090}):
            raise ValueError()
        for key in REFERENCE_KEYS[1:]:
            source = Path(values[key])
            if not source.is_absolute() or any(path.is_symlink() for path in (source, *source.parents)):
                raise ValueError()
            info = source.stat()
            if info.st_uid != 0 or info.st_mode & 0o022 or not source.is_file() or info.st_size > 65536:
                raise ValueError()
        return values
    except Exception:
        raise NativeWebRefusal('actual_product_provider_references_unavailable') from None


class ProviderRelay(AbstractContextManager['ProviderRelay']):
    def __init__(self, namespace_fd: int, endpoint: str) -> None:
        parsed = urlsplit(endpoint)
        self.target = (str(ipaddress.ip_address(parsed.hostname or '')), parsed.port or 443)
        self.namespace_fd = namespace_fd
        self.stop = Event()
        self.failed = False
        self.cleanup_confirmed = False
        self.connections = 0
        self.bytes = 0
        self.worker: Thread | None = None
        self.listener: socket.socket | None = None

    def __enter__(self) -> ProviderRelay:
        if not hasattr(os, 'setns') or self.namespace_fd < 0:
            raise NativeWebRefusal('native_provider_transport_unavailable')
        # The trusted owner holds Docker's exact namespace inode, not a PID
        # pathname that could be recycled between readback and this effect.
        namespace = '/proc/' + str(os.getpid()) + '/fd/' + str(self.namespace_fd)
        _command(['nsenter', '--net=' + namespace, 'ip', 'address',
                  'add', self.target[0] + '/32', 'dev', 'lo'])
        host = os.open('/proc/self/ns/net', os.O_RDONLY)
        try:
            os.setns(self.namespace_fd, 0)
            try:
                self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.listener.bind(self.target)
                self.listener.listen(1)
                self.listener.settimeout(1)
            finally:
                os.setns(host, 0)
        finally:
            os.close(host)
        self.worker = Thread(target=self._run, daemon=True)
        self.worker.start()
        return self

    def _run(self) -> None:
        assert self.listener is not None
        deadline = time.monotonic() + DEADLINE
        try:
            while not self.stop.is_set() and time.monotonic() < deadline:
                try:
                    client, _ = self.listener.accept()
                except socket.timeout:
                    continue
                with client:
                    self.connections += 1
                    if self.connections > MAX_CONNECTIONS:
                        raise ValueError()
                    # This socket is made after restoration of the host namespace.
                    with socket.create_connection(self.target, timeout=10) as remote:
                        client.setblocking(False)
                        remote.setblocking(False)
                        while not self.stop.is_set() and time.monotonic() < deadline:
                            readable, _, _ = select.select([client, remote], [], [], 1)
                            closed = False
                            for source in readable:
                                data = source.recv(65536)
                                if not data:
                                    closed = True
                                    break
                                self.bytes += len(data)
                                if self.bytes > MAX_BYTES:
                                    raise ValueError()
                                destination = remote if source is client else client
                                destination.settimeout(10)
                                destination.sendall(data)
                                destination.setblocking(False)
                            if closed:
                                break
        except Exception:
            self.failed = True

    def __exit__(self, *args: Any) -> None:
        self.stop.set()
        try:
            if self.worker is not None:
                self.worker.join(timeout=12)
        finally:
            if self.listener is not None:
                self.listener.close()
        if self.worker is not None and self.worker.is_alive():
            self.failed = True
            raise NativeWebRefusal('native_provider_transport_cleanup_unknown')
        self.cleanup_confirmed = True

    def readback(self) -> dict[str, Any]:
        if self.failed or self.connections < 1:
            raise NativeWebRefusal('actual_product_provider_transport_incomplete')
        return {'transport': 'unchanged-product-mtls-byte-relay.v1',
                'connections': self.connections, 'bytes': self.bytes,
                'limits': {'connections': MAX_CONNECTIONS, 'bytes': MAX_BYTES}}
