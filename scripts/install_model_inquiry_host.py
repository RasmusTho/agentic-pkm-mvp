#!/usr/bin/env python3
"""Install and verify durable BuilderOps Model Inquiry role entrypoints."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shlex
import shutil
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SCHEMA_INSTALL = "builderops.model-inquiry-host-install.v1"
SCHEMA_CHECK = "builderops.model-inquiry-host-check.v1"
TRUSTED_REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONED_ADAPTER_SHA256 = "59bd9ec13f96ac990b0ba3f5ee1e08df760201e54255bbd5033b10df174a8e59"


@dataclass(frozen=True)
class RoleSpec:
    role: str
    entrypoint: str
    provider_command: str


ROLE_SPECS = (
    RoleSpec("fable", "fable-subscription-cli", "claude"),
    RoleSpec("gpt_codex", "codex-subscription-cli", "codex"),
)


class HostInstallError(RuntimeError):
    """Safe operator-facing installation error."""


@dataclass(frozen=True)
class Checkout:
    root: Path
    adapter: Path
    adapter_sha256: str
    root_identity: tuple[int, int]
    adapter_identity: tuple[int, int]


def _resolve_file(path: Path, *, label: str, executable: bool = False) -> Path:
    candidate = Path(os.path.abspath(path.expanduser()))
    try:
        details = os.stat(candidate)
    except OSError as exc:
        raise HostInstallError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(details.st_mode):
        raise HostInstallError(f"{label} must be a regular file")
    if executable and not os.access(candidate, os.X_OK):
        raise HostInstallError(f"{label} must be executable")
    return candidate


def _absolute_parts(path: Path, *, label: str) -> tuple[str, ...]:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise HostInstallError(f"{label} must be absolute")
    parts = expanded.parts[1:]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise HostInstallError(f"{label} is invalid")
    return parts


def _open_directory_chain(path: Path, *, label: str, create_final: bool = False) -> int:
    parts = _absolute_parts(path, label=label)
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    current_fd = os.open("/", flags)
    try:
        for index, part in enumerate(parts):
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create_final or index != len(parts) - 1:
                    raise HostInstallError(f"{label} is unavailable") from None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                    os.fsync(current_fd)
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise HostInstallError(f"unable to create {label}") from exc
            except OSError as exc:
                raise HostInstallError(f"{label} must not contain symlinks") from exc
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _directory_identity(directory_fd: int) -> tuple[int, int]:
    details = os.fstat(directory_fd)
    return (details.st_dev, details.st_ino)


def _assert_directory_identity(
    path: Path,
    expected: tuple[int, int],
    *,
    label: str,
) -> None:
    verification_fd = _open_directory_chain(path, label=label)
    try:
        if _directory_identity(verification_fd) != expected:
            raise HostInstallError(f"{label} identity changed during validation")
    finally:
        os.close(verification_fd)


def _read_regular_file_at(
    directory_fd: int,
    name: str,
    *,
    label: str,
    executable: bool = False,
) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise HostInstallError(f"{label} is unavailable or unsafe") from exc
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            raise HostInstallError(f"{label} must be a regular file")
        if executable and not details.st_mode & stat.S_IXUSR:
            raise HostInstallError(f"{label} must be executable")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks), details
    finally:
        os.close(fd)


def _resolve_repo_root(path: Path) -> Checkout:
    root_fd = _open_directory_chain(path, label="repo root")
    try:
        root_identity = _directory_identity(root_fd)
        resolved = Path(os.path.realpath(path.expanduser()))
        if resolved != TRUSTED_REPO_ROOT:
            raise HostInstallError("repo root must match the trusted installer checkout")
        _assert_directory_identity(resolved, root_identity, label="repo root")
        scripts_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            scripts_flags |= os.O_NOFOLLOW
        try:
            scripts_fd = os.open("scripts", scripts_flags, dir_fd=root_fd)
        except OSError as exc:
            raise HostInstallError("versioned adapter directory is unavailable or unsafe") from exc
        try:
            adapter_bytes, adapter_details = _read_regular_file_at(
                scripts_fd,
                "model_inquiry_subscription_adapter.py",
                label="versioned subscription adapter",
            )
        finally:
            os.close(scripts_fd)
        adapter_sha256 = hashlib.sha256(adapter_bytes).hexdigest()
        if adapter_sha256 != VERSIONED_ADAPTER_SHA256:
            raise HostInstallError(
                "versioned subscription adapter must match the installer digest"
            )
        _assert_directory_identity(resolved, root_identity, label="repo root")
        adapter = resolved / "scripts" / "model_inquiry_subscription_adapter.py"
        return Checkout(
            resolved,
            adapter,
            adapter_sha256,
            root_identity,
            (adapter_details.st_dev, adapter_details.st_ino),
        )
    finally:
        os.close(root_fd)


def _open_bin_dir(path: Path, *, create: bool) -> tuple[Path, int, tuple[int, int]]:
    try:
        directory_fd = _open_directory_chain(
            path,
            label="bin directory",
            create_final=create,
        )
    except HostInstallError:
        if not create and not path.expanduser().exists():
            raise
        raise
    details = os.fstat(directory_fd)
    if details.st_uid != os.getuid():
        os.close(directory_fd)
        raise HostInstallError("bin directory must be owned by the current user")
    if details.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        os.close(directory_fd)
        raise HostInstallError("bin directory must not be group/world writable")
    return (
        Path(os.path.realpath(path.expanduser())),
        directory_fd,
        _directory_identity(directory_fd),
    )


def _wrapper_content(
    *,
    role: str,
    python: Path,
    adapter: Path,
    adapter_sha256: str,
) -> str:
    return (
        "#!/bin/sh\n"
        f"# adapter-sha256={adapter_sha256}\n"
        "set -eu\n"
        f"INQUIRY_ROLE={shlex.quote(role)} "
        f"exec {shlex.quote(str(python))} {shlex.quote(str(adapter))}\n"
    )


def _assert_adapter_identity(checkout: Checkout) -> None:
    root_fd = _open_directory_chain(checkout.root, label="repo root")
    try:
        if _directory_identity(root_fd) != checkout.root_identity:
            raise HostInstallError("repo root identity changed during validation")
        scripts_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            scripts_flags |= os.O_NOFOLLOW
        try:
            scripts_fd = os.open("scripts", scripts_flags, dir_fd=root_fd)
        except OSError as exc:
            raise HostInstallError(
                "versioned adapter directory is unavailable or unsafe"
            ) from exc
        try:
            adapter_bytes, adapter_details = _read_regular_file_at(
                scripts_fd,
                "model_inquiry_subscription_adapter.py",
                label="versioned subscription adapter",
            )
        finally:
            os.close(scripts_fd)
    finally:
        os.close(root_fd)
    if (
        (adapter_details.st_dev, adapter_details.st_ino) != checkout.adapter_identity
        or hashlib.sha256(adapter_bytes).hexdigest() != checkout.adapter_sha256
    ):
        raise HostInstallError("versioned subscription adapter identity changed")


def _assert_checkout_authority(checkout: Checkout) -> None:
    _assert_directory_identity(
        checkout.root,
        checkout.root_identity,
        label="repo root",
    )
    _assert_adapter_identity(checkout)


def _expected_wrappers(*, checkout: Checkout, python: Path) -> dict[RoleSpec, str]:
    _assert_checkout_authority(checkout)
    wrappers = {
        spec: _wrapper_content(
            role=spec.role,
            python=python,
            adapter=checkout.adapter,
            adapter_sha256=checkout.adapter_sha256,
        )
        for spec in ROLE_SPECS
    }
    _assert_checkout_authority(checkout)
    return wrappers


def _entrypoint_matches(directory_fd: int, name: str, expected: str) -> bool:
    try:
        payload, details = _read_regular_file_at(
            directory_fd,
            name,
            label=f"entrypoint {name}",
            executable=True,
        )
    except HostInstallError:
        return False
    try:
        return (
            payload.decode("utf-8") == expected
            and details.st_uid == os.getuid()
            and stat.S_IMODE(details.st_mode) == 0o700
        )
    except UnicodeError:
        return False


def _install_no_overwrite(
    directory_fd: int,
    name: str,
    content: str,
) -> bool:
    temp = f".{name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    temp_created = False
    cleanup_error: OSError | None = None
    installed: bool | None = None
    try:
        fd = os.open(temp, flags, 0o700, dir_fd=directory_fd)
        temp_created = True
        payload = content.encode("utf-8")
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchmod(fd, 0o700)
        os.fsync(fd)
        try:
            os.link(
                temp,
                name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            os.fsync(directory_fd)
            installed = True
        except FileExistsError:
            if not _entrypoint_matches(directory_fd, name, content):
                raise HostInstallError(f"conflicting entrypoint: {name}") from None
            installed = False
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise HostInstallError("bin directory does not support atomic installation") from exc
        raise HostInstallError(f"unable to install entrypoint: {name}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if temp_created:
            try:
                os.unlink(temp, dir_fd=directory_fd)
                os.fsync(directory_fd)
            except FileNotFoundError:
                pass
            except OSError as exc:
                cleanup_error = exc
    if cleanup_error is not None:
        raise HostInstallError(f"temporary entrypoint cleanup failed: {name}") from cleanup_error
    if installed is None:
        raise HostInstallError(f"unable to install entrypoint: {name}")
    return installed


def install(*, repo_root: Path, bin_dir: Path, python: Path) -> dict[str, object]:
    checkout = _resolve_repo_root(repo_root)
    interpreter = _resolve_file(python, label="host Python", executable=True)
    wrappers = _expected_wrappers(checkout=checkout, python=interpreter)
    destination, directory_fd, destination_identity = _open_bin_dir(
        bin_dir,
        create=True,
    )
    try:
        _assert_checkout_authority(checkout)
        _assert_directory_identity(
            destination,
            destination_identity,
            label="bin directory",
        )
        states: dict[RoleSpec, str] = {}
        for spec, content in wrappers.items():
            try:
                os.stat(spec.entrypoint, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                states[spec] = "installed"
            else:
                if not _entrypoint_matches(directory_fd, spec.entrypoint, content):
                    raise HostInstallError(f"conflicting entrypoint: {spec.entrypoint}")
                states[spec] = "unchanged"

        for spec, content in wrappers.items():
            if states[spec] == "installed":
                installed = _install_no_overwrite(
                    directory_fd,
                    spec.entrypoint,
                    content,
                )
                if not installed:
                    states[spec] = "unchanged"
        _assert_directory_identity(
            destination,
            destination_identity,
            label="bin directory",
        )
        for spec, content in wrappers.items():
            if not _entrypoint_matches(directory_fd, spec.entrypoint, content):
                raise HostInstallError(
                    f"entrypoint changed during installation: {spec.entrypoint}"
                )
        _assert_directory_identity(
            destination,
            destination_identity,
            label="bin directory",
        )
        _assert_checkout_authority(checkout)
    finally:
        os.close(directory_fd)

    return {
        "schema": SCHEMA_INSTALL,
        "ok": True,
        "roles": {
            spec.role: {"entrypoint": spec.entrypoint, "status": states[spec]}
            for spec in ROLE_SPECS
        },
    }


def check(
    *,
    repo_root: Path,
    bin_dir: Path,
    python: Path,
    path: str | None = None,
) -> dict[str, object]:
    checkout = _resolve_repo_root(repo_root)
    interpreter = _resolve_file(python, label="host Python", executable=True)
    wrappers = _expected_wrappers(checkout=checkout, python=interpreter)
    try:
        destination, directory_fd, destination_identity = _open_bin_dir(
            bin_dir,
            create=False,
        )
    except HostInstallError:
        destination = Path(os.path.abspath(bin_dir.expanduser()))
        directory_fd = None
        destination_identity = None
    command_path = path if path is not None else os.environ.get("PATH", os.defpath)
    roles: dict[str, object] = {}
    ok = directory_fd is not None
    launcher_available = False
    try:
        _assert_checkout_authority(checkout)
        if destination_identity is not None:
            _assert_directory_identity(
                destination,
                destination_identity,
                label="bin directory",
            )
        for spec, content in wrappers.items():
            discovered = shutil.which(spec.entrypoint, path=command_path)
            expected_path = destination / spec.entrypoint
            path_matches = (
                discovered is not None
                and Path(os.path.abspath(discovered)) == expected_path
            )
            entrypoint_available = (
                directory_fd is not None
                and path_matches
                and _entrypoint_matches(directory_fd, spec.entrypoint, content)
            )
            provider_available = (
                shutil.which(spec.provider_command, path=command_path) is not None
            )
            role_ok = entrypoint_available and provider_available
            ok = ok and role_ok
            roles[spec.role] = {
                "entrypoint": spec.entrypoint,
                "entrypoint_status": "available" if entrypoint_available else "unavailable",
                "provider_command": spec.provider_command,
                "provider_status": "available" if provider_available else "unavailable",
            }
        launcher_available = (
            shutil.which("yggdrasil-model-inquiry", path=command_path) is not None
        )
        ok = ok and launcher_available
        if directory_fd is not None and destination_identity is not None:
            _assert_directory_identity(
                destination,
                destination_identity,
                label="bin directory",
            )
            for spec, content in wrappers.items():
                discovered = shutil.which(spec.entrypoint, path=command_path)
                expected_path = destination / spec.entrypoint
                final_available = (
                    discovered is not None
                    and Path(os.path.abspath(discovered)) == expected_path
                    and _entrypoint_matches(directory_fd, spec.entrypoint, content)
                )
                if not final_available:
                    ok = False
                    role_status = roles[spec.role]
                    if isinstance(role_status, dict):
                        role_status["entrypoint_status"] = "unavailable"
            _assert_directory_identity(
                destination,
                destination_identity,
                label="bin directory",
            )
        _assert_checkout_authority(checkout)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    return {
        "schema": SCHEMA_CHECK,
        "ok": ok,
        "launcher": {
            "command": "yggdrasil-model-inquiry",
            "status": "available" if launcher_available else "unavailable",
        },
        "roles": roles,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "check"))
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument(
        "--python",
        type=Path,
        help="Python executable for installed role entrypoints; defaults to <repo>/.venv/bin/python3",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    python = args.python or args.repo_root / ".venv" / "bin" / "python3"
    try:
        if args.operation == "install":
            payload = install(
                repo_root=args.repo_root,
                bin_dir=args.bin_dir,
                python=python,
            )
        else:
            payload = check(
                repo_root=args.repo_root,
                bin_dir=args.bin_dir,
                python=python,
            )
    except HostInstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True), flush=True)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
