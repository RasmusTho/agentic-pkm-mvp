"""One fixed Docker Engine connection for an admitted source image pull.

This is not an image-retention authority.  The caller owns the source
installation and must persist its operation binding and hold its capacity
reservation before invoking the effect on this connection.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import re
import select
import socket
import stat
import struct
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4

from app.ops.pg_acceptance import IMAGE_REPOSITORY

_SOCKET = "/var/run/docker.sock"
_MAX_RESPONSE = 8 * 1024 * 1024


class SourceImageCacheRefused(RuntimeError):
    """No daemon output or registry material is exposed to callers."""

    def __init__(self) -> None:
        super().__init__("source_image_cache_refused")


class SourceImageCapacityUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("capacity_guard_unavailable")


def require_capacity_guard() -> None:
    """Production remains closed until the real capacity guard is delivered."""
    raise SourceImageCapacityUnavailable()


@contextmanager
def reserve_capacity(_store: dict[str, object], _channel: str, _operation_id: str,
                     _digest: str) -> Iterator[None]:
    """The successor must reserve all qualified backing resources here."""
    raise SourceImageCapacityUnavailable()
    yield  # pragma: no cover


def prepare_image(owner: Any, revision: str, digest: str) -> None:
    """Bind and pull once while the existing source owner holds admission."""
    with SourceImageCacheSession() as session:
        if session.store is None:
            raise SourceImageCacheRefused()
        with reserve_capacity(session.store, owner.channel, owner.operation_id, digest):
            session.pull_and_inspect(owner, revision, digest)


def _root_identity(path: str) -> tuple[int, int]:
    root = Path(path)
    if (not root.is_absolute() or str(root) != path or root == Path("/")
            or any(part in {".", ".."} for part in root.parts) or len(path) > 1024):
        raise SourceImageCacheRefused()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in root.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise SourceImageCacheRefused()
        info = os.fstat(descriptor)
        if info.st_ino <= 0:
            raise SourceImageCacheRefused()
        return info.st_dev, info.st_ino
    finally:
        os.close(descriptor)


def _connected_peer_inode(stream: socket.socket) -> int:
    """Use Linux SOCK_DIAG to identify the other end of this exact socket."""
    family = getattr(socket, "AF_NETLINK", None)
    if type(family) is not int:
        raise SourceImageCacheRefused()
    client_inode = os.fstat(stream.fileno()).st_ino
    request = struct.pack("=BBHIIIII", socket.AF_UNIX, 0, 0, 0xFFFFFFFF,
                          client_inode, 4, 0xFFFFFFFF, 0xFFFFFFFF)
    header = struct.pack("=IHHII", 16 + len(request), 20, 1, 1, 0)
    with socket.socket(family, socket.SOCK_RAW, 4) as diagnostic:
        diagnostic.settimeout(5)
        diagnostic.send(header + request)
        raw = diagnostic.recv(8192)
    if len(raw) < 32:
        raise SourceImageCacheRefused()
    length, kind, _flags, sequence, _sender = struct.unpack_from("=IHHII", raw)
    if length != len(raw) or kind != 20 or sequence != 1:
        raise SourceImageCacheRefused()
    family_read, _type, _state, _pad, inode, _cookie1, _cookie2 = struct.unpack_from("=BBBBIII", raw, 16)
    if family_read != socket.AF_UNIX or inode != client_inode:
        raise SourceImageCacheRefused()
    offset = 32
    peer = None
    while offset + 4 <= length:
        size, attribute = struct.unpack_from("=HH", raw, offset)
        if size < 4 or offset + size > length:
            raise SourceImageCacheRefused()
        if attribute == 2:
            if size != 8 or peer is not None:
                raise SourceImageCacheRefused()
            peer = struct.unpack_from("=I", raw, offset + 4)[0]
        offset += (size + 3) & ~3
    if offset != length or peer is None or peer == 0:
        raise SourceImageCacheRefused()
    return peer


def _process_has_socket(pid: int, inode: int) -> bool:
    for descriptor in Path(f"/proc/{pid}/fd").iterdir():
        try:
            if os.readlink(descriptor) == f"socket:[{inode}]":
                return True
        except FileNotFoundError:
            continue
    return False


def _qualified_daemon(stream: socket.socket, peer_pid: int) -> tuple[int, int, str, str]:
    """Qualify a dockerd peer, including a systemd-inherited listener."""
    if peer_pid == 1:
        result = subprocess.run(
            ["/usr/bin/systemctl", "show", "docker.service", "--property=MainPID", "--value"],
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
            stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=5,
        )
        value = result.stdout.strip()
        if result.returncode != 0 or result.stderr or not value.isdigit():
            raise SourceImageCacheRefused()
        daemon_pid = int(value)
        if daemon_pid <= 1:
            raise SourceImageCacheRefused()
        server_inode = _connected_peer_inode(stream)
        if not _process_has_socket(daemon_pid, server_inode):
            raise SourceImageCacheRefused()
    else:
        daemon_pid = peer_pid
    peer_namespace = os.stat(f"/proc/{daemon_pid}/ns/mnt")
    self_namespace = os.stat("/proc/self/ns/mnt")
    peer_root = os.stat(f"/proc/{daemon_pid}/root")
    self_root = os.stat("/proc/self/root")
    if (daemon_pid <= 1 or os.stat(f"/proc/{daemon_pid}").st_uid != 0
            or (peer_namespace.st_dev, peer_namespace.st_ino)
            != (self_namespace.st_dev, self_namespace.st_ino)
            or (peer_root.st_dev, peer_root.st_ino) != (self_root.st_dev, self_root.st_ino)
            or Path(f"/proc/{daemon_pid}/comm").read_text().strip() != "dockerd"):
        raise SourceImageCacheRefused()
    pidfd_open = getattr(os, "pidfd_open", None)
    if not callable(pidfd_open):
        raise SourceImageCacheRefused()
    before = Path(f"/proc/{daemon_pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if str(UUID(boot_id)) != boot_id:
        raise SourceImageCacheRefused()
    descriptor = int(pidfd_open(daemon_pid, 0))
    try:
        after = Path(f"/proc/{daemon_pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
        if not before.isdecimal() or before != after:
            raise SourceImageCacheRefused()
        if peer_pid == 1 and not _process_has_socket(daemon_pid, server_inode):
            raise SourceImageCacheRefused()
        return descriptor, daemon_pid, before, boot_id
    except Exception:
        os.close(descriptor)
        raise


class SourceImageCacheSession:
    """Read identity, pull and inspect over one non-reconnecting Unix socket."""

    def __init__(self) -> None:
        self._connection: http.client.HTTPConnection | None = None
        self._socket: socket.socket | None = None
        self._daemon_pidfd: int | None = None
        self.store: dict[str, object] | None = None
        self._spent = False

    def __enter__(self) -> SourceImageCacheSession:
        try:
            stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket = stream
            stream.settimeout(600)
            # A named abstract client is visible to SOCK_DIAG; it has no
            # filesystem entry and vanishes when this descriptor closes.
            stream.bind("\0yggdrasil-source-" + uuid4().hex)
            stream.connect(_SOCKET)
            peer_option = getattr(socket, "SO_PEERCRED", None)
            if type(peer_option) is not int:
                raise SourceImageCacheRefused()
            peer = stream.getsockopt(socket.SOL_SOCKET, peer_option, struct.calcsize("3i"))
            pid, uid, _gid = struct.unpack("3i", peer)
            if pid <= 0 or uid != 0:
                raise SourceImageCacheRefused()
            connection = http.client.HTTPConnection("localhost", timeout=600)
            connection.auto_open = 0
            connection.sock = stream
            self._connection = connection
            info = self._json("GET", "/info")
            self._daemon_pidfd, daemon_pid, daemon_start, boot_id = _qualified_daemon(stream, pid)
            self._check_daemon()
            daemon_id, root = info.get("ID"), info.get("DockerRootDir")
            driver, raw_status = info.get("Driver"), info.get("DriverStatus")
            if (type(raw_status) is not list or any(type(row) is not list or len(row) != 2
                    or any(type(value) is not str for value in row) for row in raw_status)):
                raise SourceImageCacheRefused()
            status = dict(raw_status)
            if len(status) != len(raw_status):
                raise SourceImageCacheRefused()
            driver_type = status.get("driver-type", "legacy")
            if (type(daemon_id) is not str or re.fullmatch(r"[A-Za-z0-9:._-]{1,256}", daemon_id) is None
                    or type(root) is not str or (driver, driver_type) not in {
                        ("overlay2", "legacy"), ("overlayfs", "io.containerd.snapshotter.v1"),
                    }):
                raise SourceImageCacheRefused()
            device, inode = _root_identity(root)
            self.store = {"daemon_id": daemon_id, "data_root": root, "device": device, "inode": inode,
                          "driver": driver, "driver_type": driver_type, "daemon_pid": daemon_pid,
                          "daemon_start_ticks": daemon_start, "daemon_boot_id": boot_id}
            return self
        except Exception:
            self.close()
            raise SourceImageCacheRefused() from None

    def _response(self, method: str, target: str) -> http.client.HTTPResponse:
        if self._connection is None or self._socket is None or self._connection.sock is not self._socket:
            raise SourceImageCacheRefused()
        self._connection.request(method, target)
        response = self._connection.getresponse()
        if response.status != 200 or response.will_close:
            raise SourceImageCacheRefused()
        return response

    def _check_daemon(self) -> None:
        if self._daemon_pidfd is None:
            raise SourceImageCacheRefused()
        poller = select.poll()
        poller.register(self._daemon_pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
        if poller.poll(0):
            raise SourceImageCacheRefused()

    def _json(self, method: str, target: str) -> dict[str, Any]:
        response = self._response(method, target)
        raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE or self._connection is None or self._connection.sock is not self._socket:
            raise SourceImageCacheRefused()
        value = json.loads(raw)
        if type(value) is not dict:
            raise SourceImageCacheRefused()
        return value

    def pull_and_inspect(self, owner: Any, revision: str, digest: str) -> None:
        if (re.fullmatch(r"[0-9a-f]{40}", revision) is None
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None or self.store is None
                or self._spent or owner.candidate_sha != revision or owner.image_digest != digest):
            raise SourceImageCacheRefused()
        reference = IMAGE_REPOSITORY + "@" + digest
        timer = None
        deadline = time.monotonic() + 600
        try:
            self._check_daemon()
            owner.bind_image_cache(self.store)
            self._check_daemon()
            self._spent = True
            stream = self._socket
            if stream is None:
                raise SourceImageCacheRefused()

            def interrupt() -> None:
                try:
                    stream.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(600, interrupt)
            timer.daemon = True
            timer.start()
            response = self._response("POST", "/images/create?" + urlencode({"fromImage": reference}))
            consumed = 0
            while True:
                line = response.readline(65537)
                if not line:
                    break
                consumed += len(line)
                if len(line) > 65536 or consumed > _MAX_RESPONSE:
                    raise SourceImageCacheRefused()
                message = json.loads(line)
                if type(message) is not dict or message.get("error") or message.get("errorDetail"):
                    raise SourceImageCacheRefused()
            image = self._json("GET", "/images/" + quote(reference, safe="") + "/json")
            self._check_daemon()
            config = image.get("Config")
            labels = config.get("Labels") if type(config) is dict else None
            repo_digests = image.get("RepoDigests")
            if (type(labels) is not dict or labels.get("org.opencontainers.image.revision") != revision
                    or type(repo_digests) is not list or any(type(item) is not str for item in repo_digests)
                    or reference not in repo_digests
                    or _root_identity(str(self.store["data_root"])) != (self.store["device"], self.store["inode"])
                    or time.monotonic() >= deadline):
                raise SourceImageCacheRefused()
            owner.finish_image_pull()
        except Exception:
            self.close()
            raise SourceImageCacheRefused() from None
        finally:
            if timer is not None:
                timer.cancel()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        elif self._socket is not None:
            self._socket.close()
        self._socket = None
        if self._daemon_pidfd is not None:
            os.close(self._daemon_pidfd)
            self._daemon_pidfd = None

    def __exit__(self, *_args: object) -> None:
        self.close()
