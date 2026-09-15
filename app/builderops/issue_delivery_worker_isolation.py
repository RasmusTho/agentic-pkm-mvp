"""Fail-closed Linux/systemd isolation for one Codex Issue-delivery worker.

The protected repository credential is a host-executor input used only by the
forked read-denial probe.  It is deliberately absent from the systemd command,
the worker environment, the Codex prompt, and the isolation receipt.
"""

from __future__ import annotations

import errno
import grp
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Any

from app.builderops.epic_dispatch import CodexIssueSessionLauncher


ISOLATION_PROFILE_CONTRACT = "builderops_issue_delivery_worker_isolation_profile.v1"
ISOLATION_RECEIPT_CONTRACT = "builderops_issue_delivery_worker_isolation_receipt.v1"
_UNIT_PREFIX = "yggdrasil-issue-worker-"
_PROFILE_MAX_BYTES = 64 * 1024
_MAX_COMMAND_PARTS = 256
_MAX_COMMAND_PART_BYTES = 8 * 1024
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SAFE_PRINCIPAL = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}")
_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SAFE_UNIT_TOKEN = re.compile(r"[0-9a-f]{16}")
_ALLOWED_ENVIRONMENT_KEYS = frozenset({"LANG", "LC_ALL", "PATH"})
_GIT_INSPECTION_ENVIRONMENT = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "HOME": "/nonexistent",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin:/bin",
}
_SHELL_EXECUTABLES = frozenset({"ash", "bash", "csh", "dash", "fish", "ksh", "sh", "tcsh", "zsh"})

_REQUIRED_SYSTEMD_PROPERTY_TEMPLATE = (
    "User=<worker-uid>",
    "Group=<worker-gid>",
    "SupplementaryGroups=",
    "NoNewPrivileges=yes",
    "WorkingDirectory=<worktree>",
    "ProtectSystem=strict",
    "ProtectHome=read-only",
    "ReadWritePaths=<worktree>",
    "ReadWritePaths=<model-auth-home>",
    "ReadOnlyPaths=<worktree-git-control>",
    "ReadOnlyPaths=<worktree-git-directory>",
    "ReadOnlyPaths=<worktree-git-common-directory>",
    "PrivateTmp=yes",
    "PrivateDevices=yes",
    "ProtectControlGroups=yes",
    "ProtectKernelModules=yes",
    "ProtectKernelTunables=yes",
    "RestrictSUIDSGID=yes",
    "LockPersonality=yes",
    "RestrictRealtime=yes",
    "CapabilityBoundingSet=",
    "AmbientCapabilities=",
    "UMask=0077",
    "KillMode=control-group",
    "CollectMode=inactive-or-failed",
    "TimeoutStartSec=30",
    "RuntimeMaxSec=5400",
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


REQUIRED_SYSTEMD_PROPERTIES_SHA256 = _canonical_sha256(_REQUIRED_SYSTEMD_PROPERTY_TEMPLATE)


class IssueWorkerIsolationError(ValueError):
    """Raised before worker entry when exact isolation cannot be proven."""


class CredentialProbeResult(str, Enum):
    """Only values permitted to cross the private credential-probe pipe."""

    DENIED = "denied"
    READABLE = "readable"
    MISSING = "missing"
    FAILED = "failed"


class WorkerAccessProbeResult(str, Enum):
    """Only values permitted to cross the private filesystem probe pipe."""

    ADMITTED = "worktree-writable-git-denied"
    WORKTREE_DENIED = "worktree-denied"
    GIT_METADATA_WRITABLE = "git-metadata-writable"
    FAILED = "failed"


@dataclass(frozen=True)
class ResolvedPrincipal:
    user: str
    uid: int
    group: str
    gid: int
    supplementary_gids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ExecutableIdentity:
    path: str
    device: int
    inode: int
    sha256: str
    mode: int
    owner_uid: int
    owner_gid: int


@dataclass(frozen=True)
class CredentialProbeSyscalls:
    """Injectable child syscalls; the production probe still owns fork and pipe."""

    setgroups: Callable[[Sequence[int]], None]
    setresgid: Callable[[int, int, int], None] | None
    setresuid: Callable[[int, int, int], None] | None
    getuid: Callable[[], int]
    geteuid: Callable[[], int]
    getgid: Callable[[], int]
    getegid: Callable[[], int]
    getgroups: Callable[[], list[int]]
    open: Callable[[Path, int], int]
    close: Callable[[int], None]
    access: Callable[..., bool]


@dataclass(frozen=True)
class _PathIdentity:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True)
class _CredentialIdentity:
    path: Path
    device: int
    inode: int
    owner_uid: int
    owner_gid: int
    mode: int


@dataclass(frozen=True)
class _IsolationProfile:
    profile_id: str
    profile_version: int
    profile_sha256: str
    executor: ResolvedPrincipal
    worker: ResolvedPrincipal
    worktree: _PathIdentity
    worktree_head: str
    worktree_git_directory: _PathIdentity
    worktree_git_common_directory: _PathIdentity
    model_auth_home: _PathIdentity
    model_auth_reference: str
    protected_credential: _PathIdentity
    systemd_run: ExecutableIdentity
    environment_executable: ExecutableIdentity
    git_executable: ExecutableIdentity
    codex_executable: ExecutableIdentity
    command_sha256: str
    environment: Mapping[str, str]
    isolation_properties_sha256: str


def canonical_command_sha256(command: Sequence[str]) -> str:
    """Hash one direct argv vector without shell interpretation."""

    _validate_command_parts(command)
    return _canonical_sha256(list(command))


def _secure_file_bytes(path: Path) -> bytes:
    if not path.is_absolute() or _has_control_characters(str(path)):
        raise IssueWorkerIsolationError("worker isolation profile is unavailable")
    try:
        if path.resolve(strict=True) != path:
            raise IssueWorkerIsolationError("worker isolation profile is unavailable")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except (OSError, RuntimeError) as exc:
        raise IssueWorkerIsolationError("worker isolation profile is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > _PROFILE_MAX_BYTES
        ):
            raise IssueWorkerIsolationError("worker isolation profile is unavailable")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 16 * 1024))
            if not chunk:
                raise IssueWorkerIsolationError("worker isolation profile is unavailable")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise IssueWorkerIsolationError("worker isolation profile is unavailable")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def file_sha256(path: Path) -> str:
    """Return the exact bounded profile-file digest used for admission."""

    return hashlib.sha256(_secure_file_bytes(path)).hexdigest()


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _validate_systemd_path_value(path: Path, *, label: str) -> None:
    value = str(path)
    if any(character.isspace() or character in {"\\", "%"} for character in value):
        raise IssueWorkerIsolationError(f"worker isolation {label} path is invalid")


def _validated_text(
    value: object,
    *,
    label: str,
    pattern: re.Pattern[str] | None = None,
    maximum: int = 4096,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
        or _has_control_characters(value)
        or (pattern is not None and pattern.fullmatch(value) is None)
    ):
        raise IssueWorkerIsolationError(f"worker isolation {label} is invalid")
    return value


def _validated_nonnegative_int(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 2**31 - 1:
        raise IssueWorkerIsolationError(f"worker isolation {label} is invalid")
    return value


def _validated_positive_int(value: object, *, label: str) -> int:
    result = _validated_nonnegative_int(value, label=label)
    if result == 0:
        raise IssueWorkerIsolationError(f"worker isolation {label} is invalid")
    return result


def _strict_mapping(
    value: object,
    *,
    keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise IssueWorkerIsolationError(f"worker isolation {label} is invalid")
    return value


def _profile_principal(value: object, *, label: str) -> ResolvedPrincipal:
    document = _strict_mapping(
        value,
        keys=frozenset({"user", "uid", "group", "gid", "supplementary_gids"}),
        label=label,
    )
    gid = _validated_nonnegative_int(document["gid"], label=f"{label} gid")
    raw_supplementary_gids = document["supplementary_gids"]
    if not isinstance(raw_supplementary_gids, list):
        raise IssueWorkerIsolationError(
            f"worker isolation {label} supplementary groups are invalid"
        )
    supplementary_gids = tuple(
        _validated_nonnegative_int(value, label=f"{label} supplementary gid")
        for value in raw_supplementary_gids
    )
    if supplementary_gids != tuple(sorted(set(supplementary_gids))) or gid in supplementary_gids:
        raise IssueWorkerIsolationError(
            f"worker isolation {label} supplementary groups are invalid"
        )
    return ResolvedPrincipal(
        user=_validated_text(document["user"], label=f"{label} user", pattern=_SAFE_PRINCIPAL),
        uid=_validated_nonnegative_int(document["uid"], label=f"{label} uid"),
        group=_validated_text(document["group"], label=f"{label} group", pattern=_SAFE_PRINCIPAL),
        gid=gid,
        supplementary_gids=supplementary_gids,
    )


def _profile_path(value: object, *, label: str) -> _PathIdentity:
    document = _strict_mapping(
        value,
        keys=frozenset({"path", "device", "inode"}),
        label=label,
    )
    raw_path = _validated_text(document["path"], label=f"{label} path")
    path = Path(raw_path)
    if not path.is_absolute() or str(path) != raw_path:
        raise IssueWorkerIsolationError(f"worker isolation {label} path is invalid")
    return _PathIdentity(
        path=path,
        device=_validated_nonnegative_int(document["device"], label=f"{label} device"),
        inode=_validated_positive_int(document["inode"], label=f"{label} inode"),
    )


def _profile_executable(value: object, *, label: str) -> ExecutableIdentity:
    document = _strict_mapping(
        value,
        keys=frozenset({"path", "device", "inode", "sha256", "mode", "owner_uid", "owner_gid"}),
        label=label,
    )
    identity = _profile_path(
        {key: document[key] for key in ("path", "device", "inode")},
        label=label,
    )
    digest = _validated_text(document["sha256"], label=f"{label} hash", pattern=_HEX_64)
    mode = _validated_nonnegative_int(document["mode"], label=f"{label} mode")
    if mode > 0o7777 or mode & 0o111 == 0 or mode & 0o6022:
        raise IssueWorkerIsolationError(f"worker isolation {label} mode is invalid")
    return ExecutableIdentity(
        path=str(identity.path),
        device=identity.device,
        inode=identity.inode,
        sha256=digest,
        mode=mode,
        owner_uid=_validated_nonnegative_int(document["owner_uid"], label=f"{label} owner uid"),
        owner_gid=_validated_nonnegative_int(document["owner_gid"], label=f"{label} owner gid"),
    )


def _load_profile(path: Path, expected_sha256: str) -> _IsolationProfile:
    if _HEX_64.fullmatch(expected_sha256) is None:
        raise IssueWorkerIsolationError("worker isolation profile hash is invalid")
    payload = _secure_file_bytes(path)
    observed_hash = hashlib.sha256(payload).hexdigest()
    if observed_hash != expected_sha256:
        raise IssueWorkerIsolationError("worker isolation profile changed")
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IssueWorkerIsolationError("worker isolation profile is invalid") from exc
    document = _strict_mapping(
        parsed,
        keys=frozenset(
            {
                "contract",
                "profile_id",
                "profile_version",
                "executor",
                "worker",
                "worktree",
                "model_auth",
                "protected_github_credential",
                "systemd_run",
                "environment_executable",
                "git_executable",
                "codex_executable",
                "command_sha256",
                "environment",
                "isolation_properties_sha256",
            }
        ),
        label="profile",
    )
    if document["contract"] != ISOLATION_PROFILE_CONTRACT:
        raise IssueWorkerIsolationError("worker isolation profile contract is invalid")
    profile_id = _validated_text(document["profile_id"], label="profile id", pattern=_SAFE_ID)
    if document["profile_version"] != 1:
        raise IssueWorkerIsolationError("worker isolation profile version is unsupported")
    executor = _profile_principal(document["executor"], label="executor principal")
    worker = _profile_principal(document["worker"], label="worker principal")
    if (
        worker.uid == 0
        or worker.gid == 0
        or worker.uid == executor.uid
        or worker.gid == executor.gid
        or worker.supplementary_gids
    ):
        raise IssueWorkerIsolationError(
            "worker isolation requires a distinct unprivileged principal"
        )
    worktree_document = _strict_mapping(
        document["worktree"],
        keys=frozenset(
            {
                "path",
                "device",
                "inode",
                "git_head",
                "git_directory",
                "git_common_directory",
            }
        ),
        label="worktree",
    )
    worktree = _profile_path(
        {key: worktree_document[key] for key in ("path", "device", "inode")},
        label="worktree",
    )
    worktree_head = _validated_text(
        worktree_document["git_head"], label="worktree head", pattern=re.compile(r"[0-9a-f]{40}")
    )
    worktree_git_directory = _profile_path(
        worktree_document["git_directory"], label="worktree Git directory"
    )
    worktree_git_common_directory = _profile_path(
        worktree_document["git_common_directory"],
        label="worktree Git common directory",
    )
    model_document = _strict_mapping(
        document["model_auth"],
        keys=frozenset({"home", "reference", "device", "inode"}),
        label="model auth",
    )
    model_auth_home = _profile_path(
        {
            "path": model_document["home"],
            "device": model_document["device"],
            "inode": model_document["inode"],
        },
        label="model auth home",
    )
    model_auth_reference = _validated_text(
        model_document["reference"],
        label="model auth reference",
        pattern=_SAFE_REFERENCE,
    )
    protected_credential = _profile_path(
        document["protected_github_credential"],
        label="protected credential",
    )
    environment_document = document["environment"]
    if (
        not isinstance(environment_document, Mapping)
        or set(environment_document) != _ALLOWED_ENVIRONMENT_KEYS
    ):
        raise IssueWorkerIsolationError("worker isolation environment is invalid")
    environment: dict[str, str] = {}
    for key in sorted(_ALLOWED_ENVIRONMENT_KEYS):
        environment[key] = _validated_text(environment_document[key], label=f"environment {key}")
    for component in environment["PATH"].split(":"):
        if not component or not Path(component).is_absolute() or ".." in PurePath(component).parts:
            raise IssueWorkerIsolationError("worker isolation environment PATH is invalid")
    command_sha256 = _validated_text(
        document["command_sha256"], label="command hash", pattern=_HEX_64
    )
    isolation_hash = _validated_text(
        document["isolation_properties_sha256"],
        label="properties hash",
        pattern=_HEX_64,
    )
    if isolation_hash != REQUIRED_SYSTEMD_PROPERTIES_SHA256:
        raise IssueWorkerIsolationError("worker isolation properties changed")
    executables = {
        "systemd": _profile_executable(document["systemd_run"], label="systemd"),
        "environment executable": _profile_executable(
            document["environment_executable"], label="environment executable"
        ),
        "Git executable": _profile_executable(document["git_executable"], label="Git executable"),
        "Codex executable": _profile_executable(
            document["codex_executable"], label="Codex executable"
        ),
    }
    if any(
        identity.owner_uid not in {0, executor.uid} or identity.owner_uid == worker.uid
        for identity in executables.values()
    ):
        raise IssueWorkerIsolationError("worker isolation executable owner is invalid")
    return _IsolationProfile(
        profile_id=profile_id,
        profile_version=1,
        profile_sha256=observed_hash,
        executor=executor,
        worker=worker,
        worktree=worktree,
        worktree_head=worktree_head,
        worktree_git_directory=worktree_git_directory,
        worktree_git_common_directory=worktree_git_common_directory,
        model_auth_home=model_auth_home,
        model_auth_reference=model_auth_reference,
        protected_credential=protected_credential,
        systemd_run=executables["systemd"],
        environment_executable=executables["environment executable"],
        git_executable=executables["Git executable"],
        codex_executable=executables["Codex executable"],
        command_sha256=command_sha256,
        environment=environment,
        isolation_properties_sha256=isolation_hash,
    )


def resolve_principal(user: str, group: str) -> ResolvedPrincipal:
    """Resolve one named account and its exact primary group from the live host."""

    try:
        user_entry = pwd.getpwnam(user)
        group_entry = grp.getgrnam(group)
    except KeyError as exc:
        raise IssueWorkerIsolationError("worker isolation principal is unavailable") from exc
    if user_entry.pw_gid != group_entry.gr_gid:
        raise IssueWorkerIsolationError("worker isolation principal group is invalid")
    try:
        supplementary_gids = tuple(
            sorted(set(os.getgrouplist(user, group_entry.gr_gid)) - {group_entry.gr_gid})
        )
    except OSError as exc:
        raise IssueWorkerIsolationError(
            "worker isolation principal groups are unavailable"
        ) from exc
    return ResolvedPrincipal(
        user=user,
        uid=user_entry.pw_uid,
        group=group,
        gid=group_entry.gr_gid,
        supplementary_gids=supplementary_gids,
    )


def resolve_executable(path: str) -> ExecutableIdentity:
    """Bind one executable to canonical inode, content, mode, and ownership."""

    candidate = Path(path)
    if not candidate.is_absolute() or _has_control_characters(path):
        raise IssueWorkerIsolationError("worker isolation executable is unavailable")
    try:
        resolved = candidate.resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
    except (OSError, RuntimeError) as exc:
        raise IssueWorkerIsolationError("worker isolation executable is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            resolved != candidate
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or mode & 0o111 == 0
            or mode & 0o6022
        ):
            raise IssueWorkerIsolationError("worker isolation executable is unavailable")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        repeated = os.fstat(descriptor)
        if (
            repeated.st_dev,
            repeated.st_ino,
            repeated.st_size,
            repeated.st_mode,
            repeated.st_uid,
            repeated.st_gid,
            repeated.st_mtime_ns,
            repeated.st_ctime_ns,
        ) != (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        ):
            raise IssueWorkerIsolationError("worker isolation executable changed during admission")
        return ExecutableIdentity(
            path=str(candidate),
            device=metadata.st_dev,
            inode=metadata.st_ino,
            sha256=digest.hexdigest(),
            mode=mode,
            owner_uid=metadata.st_uid,
            owner_gid=metadata.st_gid,
        )
    finally:
        os.close(descriptor)


def systemd_preflight() -> ExecutableIdentity:
    """Prove the Linux system manager and required transient-unit CLI surface."""

    if platform.system().lower() != "linux":
        raise IssueWorkerIsolationError("worker isolation host is unsupported")
    selected = shutil.which("systemd-run")
    if selected is None:
        raise IssueWorkerIsolationError("worker isolation systemd is unavailable")
    identity = resolve_executable(str(Path(selected).resolve(strict=True)))
    if (
        not Path("/run/systemd/system").is_dir()
        or not Path("/sys/fs/cgroup/cgroup.controllers").is_file()
    ):
        raise IssueWorkerIsolationError("worker isolation systemd is unavailable")
    try:
        probe = subprocess.run(
            [identity.path, "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise IssueWorkerIsolationError("worker isolation systemd is unavailable") from exc
    required = ("--wait", "--pipe", "--collect", "--unit", "--property")
    if probe.returncode != 0 or not all(option in probe.stdout for option in required):
        raise IssueWorkerIsolationError("worker isolation systemd is unavailable")
    return identity


def resolve_worktree_head(path: Path, git_executable: str) -> str:
    """Resolve the exact canonical Git worktree and immutable current head."""

    git_identity = resolve_executable(git_executable)
    try:
        result = subprocess.run(
            [
                git_identity.path,
                "-C",
                str(path),
                "rev-parse",
                "--show-toplevel",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env=dict(_GIT_INSPECTION_ENVIRONMENT),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise IssueWorkerIsolationError("worker isolation worktree is unavailable") from exc
    lines = result.stdout.splitlines()
    if (
        result.returncode != 0
        or len(lines) != 2
        or Path(lines[0]) != path
        or re.fullmatch(r"[0-9a-f]{40}", lines[1]) is None
    ):
        raise IssueWorkerIsolationError("worker isolation worktree is unavailable")
    try:
        status_result = subprocess.run(
            [
                git_identity.path,
                "-C",
                str(path),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env=dict(_GIT_INSPECTION_ENVIRONMENT),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise IssueWorkerIsolationError("worker isolation worktree is unavailable") from exc
    if status_result.returncode != 0 or status_result.stdout:
        raise IssueWorkerIsolationError("worker isolation worktree is not frozen")
    return lines[1]


def resolve_worktree_git_topology(path: Path, git_executable: str) -> tuple[Path, Path]:
    """Resolve a linked worktree's exact per-worktree and common Git directories."""

    git_identity = resolve_executable(git_executable)
    try:
        result = subprocess.run(
            [
                git_identity.path,
                "-C",
                str(path),
                "rev-parse",
                "--absolute-git-dir",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env=dict(_GIT_INSPECTION_ENVIRONMENT),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise IssueWorkerIsolationError("worker isolation Git directory is unavailable") from exc
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != 2:
        raise IssueWorkerIsolationError("worker isolation Git directory is unavailable")
    git_directory, common_directory = (Path(line) for line in lines)
    for candidate in (git_directory, common_directory):
        try:
            resolved = candidate.resolve(strict=True)
            metadata = candidate.lstat()
        except (OSError, RuntimeError) as exc:
            raise IssueWorkerIsolationError(
                "worker isolation Git directory is unavailable"
            ) from exc
        if (
            not candidate.is_absolute()
            or candidate == Path("/")
            or resolved != candidate
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise IssueWorkerIsolationError("worker isolation Git directory is unavailable")
    if (
        git_directory == common_directory
        or git_directory.is_relative_to(path)
        or path.is_relative_to(git_directory)
        or common_directory.is_relative_to(path)
        or path.is_relative_to(common_directory)
        or not git_directory.is_relative_to(common_directory / "worktrees")
    ):
        raise IssueWorkerIsolationError("worker isolation requires a linked Git worktree")
    return git_directory, common_directory


def _validate_directory(
    identity: _PathIdentity,
    *,
    label: str,
    lstat_resolver: Callable[[Path], os.stat_result] = lambda path: path.lstat(),
    owner: ResolvedPrincipal | None = None,
    required_mode: int | None = None,
) -> None:
    try:
        resolved = identity.path.resolve(strict=True)
        metadata = lstat_resolver(identity.path)
    except OSError as exc:
        raise IssueWorkerIsolationError(f"worker isolation {label} is unavailable") from exc
    if (
        resolved != identity.path
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != (identity.device, identity.inode)
        or (owner is not None and metadata.st_uid != owner.uid)
        or (owner is not None and metadata.st_gid != owner.gid)
        or (required_mode is not None and stat.S_IMODE(metadata.st_mode) != required_mode)
    ):
        raise IssueWorkerIsolationError(f"worker isolation {label} changed")


def _git_metadata_denial_targets(profile: _IsolationProfile) -> tuple[Path, ...]:
    control_file = profile.worktree.path / ".git"
    targets = (
        control_file,
        profile.worktree_git_directory.path,
        profile.worktree_git_directory.path / "HEAD",
        profile.worktree_git_directory.path / "index",
        profile.worktree_git_common_directory.path,
        profile.worktree_git_common_directory.path / "objects",
        profile.worktree_git_common_directory.path / "refs",
    )
    expected_directories = {targets[1], targets[4], targets[5], targets[6]}
    for target in targets:
        try:
            resolved = target.resolve(strict=True)
            metadata = target.lstat()
        except (OSError, RuntimeError) as exc:
            raise IssueWorkerIsolationError("worker isolation Git metadata is unavailable") from exc
        expected_type = (
            stat.S_ISDIR(metadata.st_mode)
            if target in expected_directories
            else stat.S_ISREG(metadata.st_mode)
        )
        if resolved != target or not expected_type:
            raise IssueWorkerIsolationError("worker isolation Git metadata is unavailable")
    expected_control = f"gitdir: {profile.worktree_git_directory.path}\n".encode("utf-8")
    if _secure_file_bytes(control_file) != expected_control:
        raise IssueWorkerIsolationError("worker isolation Git metadata is unavailable")
    return targets


def _validate_credential(
    identity: _PathIdentity,
    *,
    executor: ResolvedPrincipal,
    worktree: Path,
    worktree_git_directory: Path,
    worktree_git_common_directory: Path,
    model_auth_home: Path,
) -> _CredentialIdentity:
    try:
        resolved = identity.path.resolve(strict=True)
        metadata = identity.path.lstat()
    except OSError:
        raise IssueWorkerIsolationError(
            "worker isolation protected credential is unavailable"
        ) from None
    try:
        overlaps_worker_path = (
            identity.path.is_relative_to(worktree)
            or identity.path.is_relative_to(worktree_git_directory)
            or identity.path.is_relative_to(worktree_git_common_directory)
            or identity.path.is_relative_to(model_auth_home)
        )
    except ValueError:
        overlaps_worker_path = True
    if (
        resolved != identity.path
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or (metadata.st_dev, metadata.st_ino) != (identity.device, identity.inode)
        or metadata.st_uid != executor.uid
        or metadata.st_gid != executor.gid
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or overlaps_worker_path
    ):
        raise IssueWorkerIsolationError("worker isolation protected credential is unavailable")
    return _CredentialIdentity(
        path=identity.path,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        owner_uid=metadata.st_uid,
        owner_gid=metadata.st_gid,
        mode=stat.S_IMODE(metadata.st_mode),
    )


def _validate_host_profile_file(
    path: Path,
    *,
    executor: ResolvedPrincipal,
    worktree: Path,
    worktree_git_directory: Path,
    worktree_git_common_directory: Path,
    model_auth_home: Path,
) -> None:
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as exc:
        raise IssueWorkerIsolationError("worker isolation profile is unavailable") from exc
    if (
        resolved != path
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != executor.uid
        or metadata.st_gid != executor.gid
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or path.is_relative_to(worktree)
        or path.is_relative_to(worktree_git_directory)
        or path.is_relative_to(worktree_git_common_directory)
        or path.is_relative_to(model_auth_home)
    ):
        raise IssueWorkerIsolationError("worker isolation profile is unavailable")


def _write_probe_result(descriptor: int, result: CredentialProbeResult) -> None:
    try:
        os.write(descriptor, result.value.encode("ascii"))
    except OSError:
        pass


def _write_worker_access_probe_result(descriptor: int, result: WorkerAccessProbeResult) -> None:
    try:
        os.write(descriptor, result.value.encode("ascii"))
    except OSError:
        pass


def _production_probe_syscalls() -> CredentialProbeSyscalls:
    return CredentialProbeSyscalls(
        setgroups=os.setgroups,
        setresgid=getattr(os, "setresgid", None),
        setresuid=getattr(os, "setresuid", None),
        getuid=os.getuid,
        geteuid=os.geteuid,
        getgid=os.getgid,
        getegid=os.getegid,
        getgroups=os.getgroups,
        open=os.open,
        close=os.close,
        access=os.access,
    )


def _drop_principal_and_probe(
    secret_path: Path,
    worker: ResolvedPrincipal,
    syscalls: CredentialProbeSyscalls,
) -> CredentialProbeResult:
    if not callable(syscalls.setresgid) or not callable(syscalls.setresuid):
        return CredentialProbeResult.FAILED
    try:
        syscalls.setgroups([])
        syscalls.setresgid(worker.gid, worker.gid, worker.gid)
        syscalls.setresuid(worker.uid, worker.uid, worker.uid)
        if (
            syscalls.getuid() != worker.uid
            or syscalls.geteuid() != worker.uid
            or syscalls.getgid() != worker.gid
            or syscalls.getegid() != worker.gid
            or syscalls.getgroups()
        ):
            return CredentialProbeResult.FAILED
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            descriptor = syscalls.open(secret_path, flags)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                return CredentialProbeResult.DENIED
            if exc.errno == errno.ENOENT:
                return CredentialProbeResult.MISSING
            return CredentialProbeResult.FAILED
        syscalls.close(descriptor)
        return CredentialProbeResult.READABLE
    except BaseException:
        return CredentialProbeResult.FAILED


def _drop_principal_and_probe_write_access(
    writable_roots: Sequence[Path],
    denied_git_metadata: Sequence[Path],
    worker: ResolvedPrincipal,
    syscalls: CredentialProbeSyscalls,
) -> WorkerAccessProbeResult:
    if not callable(syscalls.setresgid) or not callable(syscalls.setresuid):
        return WorkerAccessProbeResult.FAILED
    try:
        syscalls.setgroups([])
        syscalls.setresgid(worker.gid, worker.gid, worker.gid)
        syscalls.setresuid(worker.uid, worker.uid, worker.uid)
        if (
            syscalls.getuid() != worker.uid
            or syscalls.geteuid() != worker.uid
            or syscalls.getgid() != worker.gid
            or syscalls.getegid() != worker.gid
            or syscalls.getgroups()
        ):
            return WorkerAccessProbeResult.FAILED
        denied_set = set(denied_git_metadata)
        for root in writable_roots:
            walk_errors: list[OSError] = []
            for directory, child_directories, child_files in os.walk(
                root,
                topdown=True,
                onerror=walk_errors.append,
                followlinks=False,
            ):
                directory_path = Path(directory)
                if not syscalls.access(
                    directory_path,
                    os.W_OK | os.X_OK,
                    effective_ids=True,
                ):
                    return WorkerAccessProbeResult.WORKTREE_DENIED
                for name in (*child_directories, *child_files):
                    candidate = directory_path / name
                    try:
                        metadata = candidate.lstat()
                    except OSError:
                        return WorkerAccessProbeResult.FAILED
                    if (
                        stat.S_ISREG(metadata.st_mode)
                        and candidate not in denied_set
                        and not syscalls.access(candidate, os.W_OK, effective_ids=True)
                    ):
                        return WorkerAccessProbeResult.WORKTREE_DENIED
            if walk_errors:
                return WorkerAccessProbeResult.FAILED
        for path in denied_git_metadata:
            if syscalls.access(path, os.W_OK, effective_ids=True):
                return WorkerAccessProbeResult.GIT_METADATA_WRITABLE
        return WorkerAccessProbeResult.ADMITTED
    except BaseException:
        return WorkerAccessProbeResult.FAILED


def probe_credential_denial(
    secret_path: Path,
    worker: ResolvedPrincipal,
    executor: ResolvedPrincipal,
    *,
    syscalls: CredentialProbeSyscalls | None = None,
) -> CredentialProbeResult:
    """Fork, irreversibly drop to the worker IDs, and probe only read denial."""

    del executor  # The child needs no executor identity after admission.
    if not hasattr(os, "fork"):
        return CredentialProbeResult.FAILED
    operations = syscalls or _production_probe_syscalls()
    try:
        reader, writer = os.pipe()
        os.set_inheritable(reader, False)
        os.set_inheritable(writer, False)
        child_pid = os.fork()
    except OSError:
        return CredentialProbeResult.FAILED
    if child_pid == 0:  # pragma: no branch - child exits through one bounded result.
        try:
            os.close(reader)
            outcome = _drop_principal_and_probe(secret_path, worker, operations)
            _write_probe_result(writer, outcome)
        except BaseException:
            _write_probe_result(writer, CredentialProbeResult.FAILED)
        finally:
            try:
                os.close(writer)
            except OSError:
                pass
        os._exit(0)
    os.close(writer)
    try:
        payload = os.read(reader, 32)
        trailing = os.read(reader, 1)
    except OSError:
        payload = b""
        trailing = b""
    finally:
        os.close(reader)
    try:
        _pid, status = os.waitpid(child_pid, 0)
    except OSError:
        return CredentialProbeResult.FAILED
    if trailing or not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        return CredentialProbeResult.FAILED
    try:
        return CredentialProbeResult(payload.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return CredentialProbeResult.FAILED


def probe_worker_write_access(
    writable_roots: Sequence[Path],
    denied_git_metadata: Sequence[Path],
    worker: ResolvedPrincipal,
    executor: ResolvedPrincipal,
    *,
    syscalls: CredentialProbeSyscalls | None = None,
) -> WorkerAccessProbeResult:
    """Fork, drop to the worker IDs, and prove effective W+X path access."""

    del executor
    if (
        not hasattr(os, "fork")
        or len(writable_roots) != 2
        or len(denied_git_metadata) != 7
        or len(set((*writable_roots, *denied_git_metadata)))
        != len((*writable_roots, *denied_git_metadata))
        or any(
            not isinstance(path, Path)
            or not path.is_absolute()
            or _has_control_characters(str(path))
            for path in (*writable_roots, *denied_git_metadata)
        )
    ):
        return WorkerAccessProbeResult.FAILED
    operations = syscalls or _production_probe_syscalls()
    try:
        reader, writer = os.pipe()
        os.set_inheritable(reader, False)
        os.set_inheritable(writer, False)
        child_pid = os.fork()
    except OSError:
        return WorkerAccessProbeResult.FAILED
    if child_pid == 0:  # pragma: no branch - child exits through one bounded result.
        try:
            os.close(reader)
            outcome = _drop_principal_and_probe_write_access(
                writable_roots, denied_git_metadata, worker, operations
            )
            _write_worker_access_probe_result(writer, outcome)
        except BaseException:
            _write_worker_access_probe_result(writer, WorkerAccessProbeResult.FAILED)
        finally:
            try:
                os.close(writer)
            except OSError:
                pass
        os._exit(0)
    os.close(writer)
    try:
        payload = os.read(reader, 32)
        trailing = os.read(reader, 1)
    except OSError:
        payload = b""
        trailing = b""
    finally:
        os.close(reader)
    try:
        _pid, status = os.waitpid(child_pid, 0)
    except OSError:
        return WorkerAccessProbeResult.FAILED
    if trailing or not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        return WorkerAccessProbeResult.FAILED
    try:
        return WorkerAccessProbeResult(payload.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return WorkerAccessProbeResult.FAILED


def _validate_command_parts(command: Sequence[str]) -> None:
    if isinstance(command, (str, bytes)) or not command or len(command) > _MAX_COMMAND_PARTS:
        raise IssueWorkerIsolationError("worker isolation command is invalid")
    for part in command:
        if (
            not isinstance(part, str)
            or not part
            or len(part.encode("utf-8")) > _MAX_COMMAND_PART_BYTES
            or _has_control_characters(part)
        ):
            raise IssueWorkerIsolationError("worker isolation command is invalid")


def _validate_direct_codex_command(command: Sequence[str], *, worktree: Path) -> None:
    _validate_command_parts(command)
    executable = Path(command[0]).name
    if executable in _SHELL_EXECUTABLES:
        raise IssueWorkerIsolationError("worker isolation shell command is forbidden")
    if (
        command[0] != "codex"
        or len(command) < 4
        or command[1] != "exec"
        or command[-1] != "-"
        or command.count("-C") != 1
        or command[command.index("-C") + 1] != str(worktree)
        or "--add-dir" in command
    ):
        raise IssueWorkerIsolationError("worker isolation direct Codex command is invalid")


def _systemd_properties(profile: _IsolationProfile) -> tuple[str, ...]:
    return (
        f"User={profile.worker.uid}",
        f"Group={profile.worker.gid}",
        "SupplementaryGroups=",
        "NoNewPrivileges=yes",
        f"WorkingDirectory={profile.worktree.path}",
        "ProtectSystem=strict",
        "ProtectHome=read-only",
        f"ReadWritePaths={profile.worktree.path}",
        f"ReadWritePaths={profile.model_auth_home.path}",
        f"ReadOnlyPaths={profile.worktree.path / '.git'}",
        f"ReadOnlyPaths={profile.worktree_git_directory.path}",
        f"ReadOnlyPaths={profile.worktree_git_common_directory.path}",
        "PrivateTmp=yes",
        "PrivateDevices=yes",
        "ProtectControlGroups=yes",
        "ProtectKernelModules=yes",
        "ProtectKernelTunables=yes",
        "RestrictSUIDSGID=yes",
        "LockPersonality=yes",
        "RestrictRealtime=yes",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "UMask=0077",
        "KillMode=control-group",
        "CollectMode=inactive-or-failed",
        "TimeoutStartSec=30",
        "RuntimeMaxSec=5400",
    )


def _path_identity_digest(identity: _PathIdentity, **extra: object) -> str:
    return _canonical_sha256({"device": identity.device, "inode": identity.inode, **extra})


def _executable_set_digest(profile: _IsolationProfile) -> str:
    return _canonical_sha256(
        {
            role: {
                "device": identity.device,
                "inode": identity.inode,
                "sha256": identity.sha256,
                "mode": identity.mode,
                "owner_uid": identity.owner_uid,
                "owner_gid": identity.owner_gid,
            }
            for role, identity in (
                ("systemd", profile.systemd_run),
                ("environment", profile.environment_executable),
                ("git", profile.git_executable),
                ("codex", profile.codex_executable),
            )
        }
    )


class _SystemdWorkerRunner:
    def __init__(
        self,
        *,
        profile_file: Path,
        expected_profile_sha256: str,
        principal_resolver: Callable[[str, str], ResolvedPrincipal],
        current_identity: Callable[[], tuple[int, int]],
        credential_probe: Callable[
            [Path, ResolvedPrincipal, ResolvedPrincipal], CredentialProbeResult
        ],
        worker_access_probe: Callable[
            [
                Sequence[Path],
                Sequence[Path],
                ResolvedPrincipal,
                ResolvedPrincipal,
            ],
            WorkerAccessProbeResult,
        ],
        worktree_head_resolver: Callable[[Path, str], str],
        worktree_git_topology_resolver: Callable[[Path, str], tuple[Path, Path]],
        systemd_preflight_resolver: Callable[[], ExecutableIdentity],
        executable_resolver: Callable[[str], ExecutableIdentity],
        path_lstat_resolver: Callable[[Path], os.stat_result],
        runner: Callable[..., subprocess.CompletedProcess[str]],
        unit_token: Callable[[], str],
        clock: Callable[[], str],
        platform_name: str,
    ) -> None:
        self._profile_file = profile_file
        self._expected_profile_sha256 = expected_profile_sha256
        self._principal_resolver = principal_resolver
        self._current_identity = current_identity
        self._credential_probe = credential_probe
        self._worker_access_probe = worker_access_probe
        self._worktree_head_resolver = worktree_head_resolver
        self._worktree_git_topology_resolver = worktree_git_topology_resolver
        self._systemd_preflight = systemd_preflight_resolver
        self._executable_resolver = executable_resolver
        self._path_lstat_resolver = path_lstat_resolver
        self._runner = runner
        self._unit_token = unit_token
        self._clock = clock
        self._platform_name = platform_name.lower()
        self.receipt: dict[str, object] | None = None

    @staticmethod
    def _require_principal(
        configured: ResolvedPrincipal,
        resolved: ResolvedPrincipal,
    ) -> None:
        if resolved != configured:
            raise IssueWorkerIsolationError("worker isolation principal changed")

    def _validate_executable_set(self, profile: _IsolationProfile) -> None:
        for label, configured in (
            ("systemd", profile.systemd_run),
            ("environment", profile.environment_executable),
            ("Git", profile.git_executable),
            ("Codex", profile.codex_executable),
        ):
            if self._executable_resolver(configured.path) != configured:
                raise IssueWorkerIsolationError(
                    f"worker isolation {label} executable identity changed"
                )

    def _validate_live(
        self, profile: _IsolationProfile
    ) -> tuple[_CredentialIdentity, ExecutableIdentity]:
        executor = self._principal_resolver(profile.executor.user, profile.executor.group)
        worker = self._principal_resolver(profile.worker.user, profile.worker.group)
        self._require_principal(profile.executor, executor)
        self._require_principal(profile.worker, worker)
        if self._current_identity() != (executor.uid, executor.gid):
            raise IssueWorkerIsolationError("worker isolation executor principal changed")
        _validate_host_profile_file(
            self._profile_file,
            executor=executor,
            worktree=profile.worktree.path,
            worktree_git_directory=profile.worktree_git_directory.path,
            worktree_git_common_directory=profile.worktree_git_common_directory.path,
            model_auth_home=profile.model_auth_home.path,
        )
        if file_sha256(self._profile_file) != profile.profile_sha256:
            raise IssueWorkerIsolationError("worker isolation profile changed")
        _validate_directory(profile.worktree, label="worktree")
        _validate_directory(profile.worktree_git_directory, label="worktree Git directory")
        _validate_directory(
            profile.worktree_git_common_directory,
            label="worktree Git common directory",
        )
        _validate_directory(
            profile.model_auth_home,
            label="model auth home",
            lstat_resolver=self._path_lstat_resolver,
            owner=worker,
            required_mode=0o700,
        )
        _validate_systemd_path_value(profile.worktree.path, label="worktree")
        _validate_systemd_path_value(profile.worktree.path / ".git", label="worktree Git control")
        _validate_systemd_path_value(
            profile.worktree_git_directory.path, label="worktree Git directory"
        )
        _validate_systemd_path_value(
            profile.worktree_git_common_directory.path,
            label="worktree Git common directory",
        )
        _validate_systemd_path_value(profile.model_auth_home.path, label="model auth home")
        if (
            profile.worktree_git_directory.path == profile.worktree.path
            or profile.worktree.path.is_relative_to(profile.worktree_git_directory.path)
            or profile.worktree_git_common_directory.path.is_relative_to(profile.worktree.path)
            or profile.worktree.path.is_relative_to(profile.worktree_git_common_directory.path)
            or profile.worktree.path == profile.model_auth_home.path
            or profile.worktree.path.is_relative_to(profile.model_auth_home.path)
            or profile.model_auth_home.path.is_relative_to(profile.worktree.path)
            or profile.worktree_git_directory.path.is_relative_to(profile.model_auth_home.path)
            or profile.model_auth_home.path.is_relative_to(profile.worktree_git_directory.path)
            or profile.worktree_git_common_directory.path.is_relative_to(
                profile.model_auth_home.path
            )
            or profile.model_auth_home.path.is_relative_to(
                profile.worktree_git_common_directory.path
            )
        ):
            raise IssueWorkerIsolationError("worker isolation writable paths overlap")
        self._validate_executable_set(profile)
        if (
            self._worktree_head_resolver(profile.worktree.path, profile.git_executable.path)
            != profile.worktree_head
        ):
            raise IssueWorkerIsolationError("worker isolation worktree head changed")
        if self._worktree_git_topology_resolver(
            profile.worktree.path, profile.git_executable.path
        ) != (
            profile.worktree_git_directory.path,
            profile.worktree_git_common_directory.path,
        ):
            raise IssueWorkerIsolationError("worker isolation Git directory changed")
        _git_metadata_denial_targets(profile)
        systemd_identity = self._systemd_preflight()
        if systemd_identity != profile.systemd_run:
            raise IssueWorkerIsolationError("worker isolation systemd identity changed")
        credential = _validate_credential(
            profile.protected_credential,
            executor=executor,
            worktree=profile.worktree.path,
            worktree_git_directory=profile.worktree_git_directory.path,
            worktree_git_common_directory=profile.worktree_git_common_directory.path,
            model_auth_home=profile.model_auth_home.path,
        )
        return credential, systemd_identity

    def reset(self) -> None:
        self.receipt = None

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        input: str,
        capture_output: bool,
        text: bool,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        self.receipt = None
        if self._platform_name != "linux":
            raise IssueWorkerIsolationError("worker isolation host is unsupported")
        profile = _load_profile(self._profile_file, self._expected_profile_sha256)
        if cwd.resolve() != profile.worktree.path:
            raise IssueWorkerIsolationError("worker isolation worktree changed")
        if capture_output is not True or text is not True or check is not False:
            raise IssueWorkerIsolationError("worker isolation process boundary is invalid")
        _validate_direct_codex_command(command, worktree=profile.worktree.path)
        direct_command = [profile.codex_executable.path, *command[1:]]
        if canonical_command_sha256(direct_command) != profile.command_sha256:
            raise IssueWorkerIsolationError("worker isolation command changed")
        protected_path = str(profile.protected_credential.path)
        if protected_path in input or any(protected_path in part for part in direct_command):
            raise IssueWorkerIsolationError("worker isolation prompt or command is invalid")
        token = self._unit_token()
        if not isinstance(token, str) or _SAFE_UNIT_TOKEN.fullmatch(token) is None:
            raise IssueWorkerIsolationError("worker isolation unit identity is invalid")
        unit = f"{_UNIT_PREFIX}{token}.service"
        credential, systemd_identity = self._validate_live(profile)
        repeated_credential, repeated_systemd = self._validate_live(profile)
        if repeated_credential != credential or repeated_systemd != systemd_identity:
            raise IssueWorkerIsolationError("worker isolation host identity changed")
        try:
            probe_result = self._credential_probe(credential.path, profile.worker, profile.executor)
        except Exception:
            raise IssueWorkerIsolationError(
                "worker isolation credential denial is unproven"
            ) from None
        if probe_result is not CredentialProbeResult.DENIED:
            raise IssueWorkerIsolationError("worker isolation credential denial is unproven")
        writable_paths = (
            profile.worktree.path,
            profile.model_auth_home.path,
        )
        denied_git_metadata = _git_metadata_denial_targets(profile)
        try:
            worker_access_result = self._worker_access_probe(
                writable_paths,
                denied_git_metadata,
                profile.worker,
                profile.executor,
            )
        except Exception:
            raise IssueWorkerIsolationError(
                "worker isolation effective write access is unproven"
            ) from None
        if worker_access_result is not WorkerAccessProbeResult.ADMITTED:
            raise IssueWorkerIsolationError(
                "worker isolation worktree access or Git metadata denial is unproven"
            )
        # Re-stat the protected file and re-hash every executable after the
        # forked identity probes. No external command runs before systemd entry.
        post_probe_credential = _validate_credential(
            profile.protected_credential,
            executor=profile.executor,
            worktree=profile.worktree.path,
            worktree_git_directory=profile.worktree_git_directory.path,
            worktree_git_common_directory=profile.worktree_git_common_directory.path,
            model_auth_home=profile.model_auth_home.path,
        )
        if post_probe_credential != credential:
            raise IssueWorkerIsolationError("worker isolation protected credential changed")
        self._validate_executable_set(profile)
        child_environment = {
            "CODEX_HOME": str(profile.model_auth_home.path),
            "HOME": str(profile.model_auth_home.path),
            **profile.environment,
        }
        if protected_path in child_environment.values():
            raise IssueWorkerIsolationError("worker isolation environment is invalid")
        properties = _systemd_properties(profile)
        emitted_properties_sha256 = _canonical_sha256(list(properties))
        systemd_command = [
            systemd_identity.path,
            "--wait",
            "--pipe",
            "--collect",
            "--quiet",
            "--service-type=exec",
            f"--unit={unit}",
            *(f"--property={value}" for value in properties),
            "--",
            profile.environment_executable.path,
            "-i",
            *(f"{key}={value}" for key, value in sorted(child_environment.items())),
            *direct_command,
        ]
        _validate_command_parts(systemd_command)
        if any(protected_path in part for part in systemd_command):
            raise IssueWorkerIsolationError("worker isolation command is invalid")
        entered_at = _validated_text(
            self._clock(),
            label="receipt time",
            pattern=re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"),
            maximum=20,
        )
        result = self._runner(
            systemd_command,
            cwd=profile.worktree.path,
            input=input,
            capture_output=True,
            text=True,
            check=False,
            env={
                "LANG": profile.environment["LANG"],
                "LC_ALL": profile.environment["LC_ALL"],
            },
            timeout=5460,
        )
        self.receipt = {
            "contract": ISOLATION_RECEIPT_CONTRACT,
            "profile_id": profile.profile_id,
            "profile_version": profile.profile_version,
            "profile_sha256": profile.profile_sha256,
            "executor": {
                "uid": profile.executor.uid,
                "gid": profile.executor.gid,
                "supplementary_gids": list(profile.executor.supplementary_gids),
            },
            "worker": {
                "uid": profile.worker.uid,
                "gid": profile.worker.gid,
                "supplementary_gids": list(profile.worker.supplementary_gids),
            },
            "unit_identity": unit,
            "worktree_identity_sha256": _path_identity_digest(
                profile.worktree,
                git_head=profile.worktree_head,
                git_directory_device=profile.worktree_git_directory.device,
                git_directory_inode=profile.worktree_git_directory.inode,
                git_common_directory_device=profile.worktree_git_common_directory.device,
                git_common_directory_inode=profile.worktree_git_common_directory.inode,
            ),
            "executable_set_identity_sha256": _executable_set_digest(profile),
            "model_auth_reference": profile.model_auth_reference,
            "model_auth_identity_sha256": _path_identity_digest(
                profile.model_auth_home,
                reference=profile.model_auth_reference,
            ),
            "protected_credential_identity_sha256": _canonical_sha256(
                {
                    "device": credential.device,
                    "inode": credential.inode,
                    "owner_uid": credential.owner_uid,
                    "owner_gid": credential.owner_gid,
                    "mode": credential.mode,
                }
            ),
            "probe_result": probe_result.value,
            "worker_write_access_probe_result": worker_access_result.value,
            "git_metadata_write_denied": True,
            "command_sha256": profile.command_sha256,
            "isolation_properties_sha256": emitted_properties_sha256,
            "isolation_template_sha256": profile.isolation_properties_sha256,
            "no_new_privileges": True,
            "child_environment_keys": sorted(child_environment),
            "entered_at": entered_at,
        }
        return result


class LinuxSystemdCodexIssueSessionLauncher(CodexIssueSessionLauncher):
    """Existing Codex launcher composed with the fail-closed systemd runner."""

    def __init__(
        self,
        *,
        repo_root: Path,
        profile_file: Path,
        expected_profile_sha256: str,
        adapter_path: Path | None = None,
        provider_census_path: Path | None = None,
        builder_channel: str = "dev",
        principal_resolver: Callable[[str, str], ResolvedPrincipal] = resolve_principal,
        current_identity: Callable[[], tuple[int, int]] = lambda: (
            os.geteuid(),
            os.getegid(),
        ),
        credential_probe: Callable[
            [Path, ResolvedPrincipal, ResolvedPrincipal], CredentialProbeResult
        ] = probe_credential_denial,
        worker_access_probe: Callable[
            [
                Sequence[Path],
                Sequence[Path],
                ResolvedPrincipal,
                ResolvedPrincipal,
            ],
            WorkerAccessProbeResult,
        ] = probe_worker_write_access,
        worktree_head_resolver: Callable[[Path, str], str] = resolve_worktree_head,
        worktree_git_topology_resolver: Callable[
            [Path, str], tuple[Path, Path]
        ] = resolve_worktree_git_topology,
        systemd_preflight: Callable[[], ExecutableIdentity] = systemd_preflight,
        executable_resolver: Callable[[str], ExecutableIdentity] = resolve_executable,
        path_lstat_resolver: Callable[[Path], os.stat_result] = lambda path: path.lstat(),
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        unit_token: Callable[[], str] = lambda: os.urandom(8).hex(),
        clock: Callable[[], str] = lambda: __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        platform_name: str = platform.system(),
    ) -> None:
        self._isolation_runner = _SystemdWorkerRunner(
            profile_file=profile_file,
            expected_profile_sha256=expected_profile_sha256,
            principal_resolver=principal_resolver,
            current_identity=current_identity,
            credential_probe=credential_probe,
            worker_access_probe=worker_access_probe,
            worktree_head_resolver=worktree_head_resolver,
            worktree_git_topology_resolver=worktree_git_topology_resolver,
            systemd_preflight_resolver=systemd_preflight,
            executable_resolver=executable_resolver,
            path_lstat_resolver=path_lstat_resolver,
            runner=runner,
            unit_token=unit_token,
            clock=clock,
            platform_name=platform_name,
        )
        super().__init__(
            repo_root=repo_root,
            adapter_path=adapter_path,
            provider_census_path=provider_census_path,
            builder_channel=builder_channel,
            runner=self._isolation_runner,
            precreated_worktree_only=True,
        )

    def launch(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self._isolation_runner.reset()
        result = dict(super().launch(context_pack, execution_routing=execution_routing))
        receipt = self._isolation_runner.receipt
        if receipt is None:
            raise IssueWorkerIsolationError("worker isolation entry receipt is unavailable")
        result["isolation_receipt"] = dict(receipt)
        return result


__all__ = [
    "ISOLATION_PROFILE_CONTRACT",
    "ISOLATION_RECEIPT_CONTRACT",
    "REQUIRED_SYSTEMD_PROPERTIES_SHA256",
    "CredentialProbeResult",
    "CredentialProbeSyscalls",
    "ExecutableIdentity",
    "IssueWorkerIsolationError",
    "LinuxSystemdCodexIssueSessionLauncher",
    "ResolvedPrincipal",
    "WorkerAccessProbeResult",
    "canonical_command_sha256",
    "file_sha256",
    "probe_credential_denial",
    "probe_worker_write_access",
    "resolve_executable",
    "resolve_principal",
    "resolve_worktree_git_topology",
    "resolve_worktree_head",
    "systemd_preflight",
]
