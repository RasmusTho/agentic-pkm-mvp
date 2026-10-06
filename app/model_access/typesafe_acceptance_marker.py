"""Durable, owner-separated one-shot admission for TypeSafe dev acceptance."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
import stat
from typing import Final, Literal

from app.ops.host_secret_controller import HostSecretController


TYPESAFE_ACCEPTANCE_STATE_DIRECTORY: Final[str] = "TYPESAFE_ACCEPTANCE_STATE_DIRECTORY"
PRODUCT_ACCEPTANCE_CONSUMER: Final[str] = "product"
BUILDER_ACCEPTANCE_CONSUMER: Final[str] = "builder"
_CONSUMERS = frozenset({PRODUCT_ACCEPTANCE_CONSUMER, BUILDER_ACCEPTANCE_CONSUMER})
_MARKER_NAMES = {
    PRODUCT_ACCEPTANCE_CONSUMER: "product.acceptance.json",
    BUILDER_ACCEPTANCE_CONSUMER: "builder.acceptance.json",
}
_MARKER_SCHEMA: Final[int] = 1


class AcceptanceMarkerError(RuntimeError):
    """The durable acceptance state cannot authorize another call."""


def acceptance_state_directory_from_environment(
    environment: Mapping[str, str] | None,
) -> Path | None:
    """Return the explicitly configured persistent state directory.

    A missing directory is deliberately different from a temporary default: an
    acceptance server without an operator-selected durable location is refused.
    """

    if environment is None:
        environment = os.environ
    configured = environment.get(TYPESAFE_ACCEPTANCE_STATE_DIRECTORY)
    return Path(configured) if configured else None


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate marker key")
        result[key] = value
    return result


def _validate_state_directory(path: Path) -> None:
    if not path.is_absolute() or any(
        part in {"Mobile Documents", "CloudStorage", ".git"} for part in path.parts
    ):
        raise AcceptanceMarkerError()
    for parent in (path, *path.parents):
        if parent.is_symlink() or (parent / ".git").exists():
            raise AcceptanceMarkerError()


def _validate_marker_file(descriptor: int, consumer: Literal["product", "builder"]) -> None:
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise AcceptanceMarkerError()
    raw = os.read(descriptor, 4097)
    if not 1 <= len(raw) <= 4096:
        raise AcceptanceMarkerError()
    try:
        marker = json.loads(
            raw.decode("utf-8", errors="strict"), object_pairs_hook=_strict_object
        )
    except Exception:
        raise AcceptanceMarkerError() from None
    if marker != {
        "consumer": consumer,
        "schema": _MARKER_SCHEMA,
        "state": "consumed",
    }:
        raise AcceptanceMarkerError()


def _validate_created_file(descriptor: int) -> None:
    info = os.fstat(descriptor)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise AcceptanceMarkerError()


def _write_all(descriptor: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(descriptor, raw[offset:])
        if written <= 0:
            raise AcceptanceMarkerError()
        offset += written


def consume_acceptance_once(
    consumer: Literal["product", "builder"],
    directory: Path | None,
) -> bool:
    """Atomically consume a durable Product or Builder allowance.

    The marker is created before BWS lookup or provider dispatch. A successful
    return means the marker bytes and containing directory entry were fsynced.
    Any create, validation, or durability failure raises and leaves the caller
    fail-closed. Existing valid or malformed markers never get removed or reset.
    """

    if consumer not in _CONSUMERS or directory is None:
        raise AcceptanceMarkerError()
    _validate_state_directory(directory)
    directory_fd = None
    marker_fd = None
    try:
        directory_fd = HostSecretController._durable_directory(directory)
        directory_info = os.fstat(directory_fd)
        if (
            directory_info.st_uid != os.geteuid()
            or stat.S_IMODE(directory_info.st_mode) != 0o700
        ):
            raise AcceptanceMarkerError()
        name = _MARKER_NAMES[consumer]
        try:
            marker_fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            marker_fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            _validate_marker_file(marker_fd, consumer)
            return False
        raw = (
            json.dumps(
                {"consumer": consumer, "schema": _MARKER_SCHEMA, "state": "consumed"},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
        _write_all(marker_fd, raw)
        _validate_created_file(marker_fd)
        os.fsync(marker_fd)
        os.close(marker_fd)
        marker_fd = None
        marker_fd = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        _validate_marker_file(marker_fd, consumer)
        os.fsync(directory_fd)
        return True
    except AcceptanceMarkerError:
        raise
    except Exception:
        raise AcceptanceMarkerError() from None
    finally:
        for descriptor in (marker_fd, directory_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


__all__ = [
    "AcceptanceMarkerError",
    "BUILDER_ACCEPTANCE_CONSUMER",
    "PRODUCT_ACCEPTANCE_CONSUMER",
    "TYPESAFE_ACCEPTANCE_STATE_DIRECTORY",
    "acceptance_state_directory_from_environment",
    "consume_acceptance_once",
]
