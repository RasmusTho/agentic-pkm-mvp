"""Fail-closed systemd/cgroup-v2 containment for verification runs.

The scope name is launch-specific and allowlisted by the caller. Numeric PIDs
never confer signal authority: every target is bound to its Linux start-time
tick and exact cgroup-v2 scope, then revalidated through a pidfd immediately
before signalling.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.dispatcher.linux_launch_barrier import RELEASE_TOKEN


LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE = "linux-systemd-cgroup-v2-scope-v1"
_SCOPE_PREFIX = "yggdrasil-verification-"
_STABLE_SNAPSHOT_ATTEMPTS = 8


def validated_linux_containment_receipt(value: object) -> dict[str, object]:
    """Validate the complete secret-safe Linux containment allowlist."""

    if not isinstance(value, Mapping):
        raise ValueError("verification containment receipt is malformed")
    evidence = value.get("evidence_digests")
    hex64 = re.compile(r"[0-9a-f]{64}")
    scope_name = re.compile(r"yggdrasil-verification-[0-9a-f]{24}\.scope")
    if (
        set(value)
        != {
            "contract",
            "profile_name",
            "scope_identity",
            "evidence_digests",
            "outcome",
        }
        or value.get("contract") != "builderops_linux_containment.v1"
        or value.get("profile_name")
        != LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE
        or not isinstance(value.get("scope_identity"), str)
        or scope_name.fullmatch(str(value.get("scope_identity"))) is None
        or not isinstance(evidence, Mapping)
        or set(evidence) != {"attach", "cleanup"}
        or any(
            not isinstance(evidence.get(key), str)
            or hex64.fullmatch(str(evidence.get(key))) is None
            for key in ("attach", "cleanup")
        )
        or value.get("outcome") != "clean"
    ):
        raise ValueError("verification containment receipt is malformed")
    return dict(value)


@dataclass(frozen=True, order=True)
class LinuxProcessIdentity:
    """One PID generation and its observed cgroup-v2 membership."""

    pid: int
    start_time_ticks: int
    parent_pid: int
    cgroup_path: str


@dataclass(frozen=True)
class LinuxScopeIdentity:
    """One named transient scope bound to its cgroup filesystem object."""

    unit: str
    cgroup_path: str
    cgroup_device: int
    cgroup_inode: int


class LinuxCgroupKernel(Protocol):
    """Narrow injectable systemd/cgroup-v2 interface."""

    def preflight(self) -> None: ...

    def scope_command(
        self, scope_name: str, command: Sequence[str]
    ) -> list[str]: ...

    def scope_identity(self, scope_name: str) -> LinuxScopeIdentity: ...

    def inspect(self, pid: int) -> LinuxProcessIdentity | None: ...

    def scope_members(
        self, scope: LinuxScopeIdentity
    ) -> frozenset[LinuxProcessIdentity]: ...

    def signal(self, identity: LinuxProcessIdentity, sig: int) -> bool: ...

    def retire_scope(self, scope: LinuxScopeIdentity) -> bool: ...


def _parse_proc_stat(pid: int, payload: str) -> tuple[int, int]:
    closing = payload.rfind(")")
    if closing < 0 or not payload.startswith(f"{pid} ("):
        raise ValueError("Linux process identity is malformed")
    fields = payload[closing + 1 :].split()
    if len(fields) < 20:
        raise ValueError("Linux process identity is incomplete")
    try:
        parent_pid = int(fields[1])
        start_time_ticks = int(fields[19])
    except (TypeError, ValueError) as exc:
        raise ValueError("Linux process identity is malformed") from exc
    if parent_pid < 0 or start_time_ticks <= 0:
        raise ValueError("Linux process identity is malformed")
    return parent_pid, start_time_ticks


def _parse_unified_cgroup(payload: str) -> str:
    lines = [line for line in payload.splitlines() if line]
    if len(lines) != 1:
        raise ValueError("Linux unified cgroup membership is unavailable")
    hierarchy, controllers, cgroup_path = lines[0].split(":", 2)
    path = PurePosixPath(cgroup_path)
    if (
        hierarchy != "0"
        or controllers
        or not cgroup_path.startswith("/")
        or ".." in path.parts
    ):
        raise ValueError("Linux unified cgroup membership is unavailable")
    return cgroup_path


def _parse_systemctl_properties(payload: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in payload.splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in properties:
            raise ValueError("Linux systemd scope identity is malformed")
        properties[key] = value
    return properties


class SystemdCgroupV2Kernel:
    """Production adapter for one user-manager transient scope."""

    def __init__(
        self,
        *,
        proc_root: Path = Path("/proc"),
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._proc_root = proc_root
        self._cgroup_root = cgroup_root
        self._runner = runner
        self._systemd_run: str | None = None
        self._systemctl: str | None = None

    def _invoke(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return self._runner(
                list(command),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Linux systemd user manager is unavailable") from exc

    def preflight(self) -> None:
        systemd_run = shutil.which("systemd-run")
        systemctl = shutil.which("systemctl")
        if systemd_run is None or systemctl is None:
            raise ValueError("Linux systemd/cgroup-v2 prerequisites are unavailable")
        if not (self._cgroup_root / "cgroup.controllers").is_file():
            raise ValueError("Linux cgroup-v2 unified hierarchy is unavailable")
        try:
            own_cgroup = (self._proc_root / "self" / "cgroup").read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            raise ValueError("Linux cgroup-v2 unified hierarchy is unavailable") from exc
        _parse_unified_cgroup(own_cgroup)
        probe = self._invoke([systemctl, "--user", "show-environment"])
        if probe.returncode != 0:
            raise ValueError("Linux systemd user manager is unavailable")
        help_probe = self._invoke([systemd_run, "--help"])
        required = ("--scope", "--unit", "--user", "--property")
        if help_probe.returncode != 0 or not all(
            option in help_probe.stdout for option in required
        ):
            raise ValueError("Linux systemd scope attachment is unavailable")
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ValueError("Linux PID-version-bound signalling is unavailable")
        self._systemd_run = systemd_run
        self._systemctl = systemctl

    @staticmethod
    def _validate_scope_name(scope_name: str) -> None:
        suffix = scope_name.removeprefix(_SCOPE_PREFIX).removesuffix(".scope")
        if (
            not scope_name.startswith(_SCOPE_PREFIX)
            or not scope_name.endswith(".scope")
            or len(suffix) != 24
            or any(character not in "0123456789abcdef" for character in suffix)
        ):
            raise ValueError("Linux containment scope name is invalid")

    def scope_command(
        self, scope_name: str, command: Sequence[str]
    ) -> list[str]:
        self._validate_scope_name(scope_name)
        if self._systemd_run is None or not command:
            raise ValueError("Linux containment preflight is incomplete")
        return [
            self._systemd_run,
            "--user",
            "--scope",
            "--quiet",
            "--unit",
            scope_name,
            "--property=KillMode=control-group",
            "--property=CollectMode=inactive-or-failed",
            "--",
            *command,
        ]

    def _cgroup_directory(self, cgroup_path: str) -> Path:
        relative = PurePosixPath(cgroup_path)
        if not cgroup_path.startswith("/") or ".." in relative.parts:
            raise ValueError("Linux cgroup path is invalid")
        root = self._cgroup_root.resolve()
        candidate = (root / cgroup_path.lstrip("/")).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("Linux cgroup path escapes the unified hierarchy")
        return candidate

    def scope_identity(self, scope_name: str) -> LinuxScopeIdentity:
        self._validate_scope_name(scope_name)
        if self._systemctl is None:
            raise ValueError("Linux containment preflight is incomplete")
        result = self._invoke(
            [
                self._systemctl,
                "--user",
                "show",
                scope_name,
                "--no-pager",
                "--property=Id",
                "--property=ControlGroup",
                "--property=ActiveState",
                "--property=KillMode",
            ]
        )
        if result.returncode != 0:
            raise ValueError("Linux systemd scope identity is unavailable")
        properties = _parse_systemctl_properties(result.stdout)
        if (
            properties
            != {
                "Id": scope_name,
                "ControlGroup": properties.get("ControlGroup", ""),
                "ActiveState": "active",
                "KillMode": "control-group",
            }
            or not properties["ControlGroup"]
        ):
            raise ValueError("Linux systemd scope identity is unavailable")
        cgroup_path = properties["ControlGroup"]
        directory = self._cgroup_directory(cgroup_path)
        try:
            stat_result = directory.stat()
        except OSError as exc:
            raise ValueError("Linux systemd scope cgroup is unavailable") from exc
        return LinuxScopeIdentity(
            unit=scope_name,
            cgroup_path=cgroup_path,
            cgroup_device=stat_result.st_dev,
            cgroup_inode=stat_result.st_ino,
        )

    def inspect(self, pid: int) -> LinuxProcessIdentity | None:
        if pid <= 0:
            return None
        directory = self._proc_root / str(pid)
        try:
            stat_payload = (directory / "stat").read_text(encoding="utf-8")
            cgroup_payload = (directory / "cgroup").read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ValueError("Linux process identity is unavailable") from exc
        parent_pid, start_time_ticks = _parse_proc_stat(pid, stat_payload)
        return LinuxProcessIdentity(
            pid=pid,
            start_time_ticks=start_time_ticks,
            parent_pid=parent_pid,
            cgroup_path=_parse_unified_cgroup(cgroup_payload),
        )

    @staticmethod
    def _is_inside_scope(cgroup_path: str, scope_path: str) -> bool:
        return cgroup_path == scope_path or cgroup_path.startswith(scope_path + "/")

    def scope_members(
        self, scope: LinuxScopeIdentity
    ) -> frozenset[LinuxProcessIdentity]:
        directory = self._cgroup_directory(scope.cgroup_path)
        try:
            current_stat = directory.stat()
        except FileNotFoundError:
            return frozenset()
        except OSError as exc:
            raise ValueError("Linux systemd scope cgroup is unavailable") from exc
        if (current_stat.st_dev, current_stat.st_ino) != (
            scope.cgroup_device,
            scope.cgroup_inode,
        ):
            raise ValueError("Linux systemd scope identity changed")
        pids: set[int] = set()
        try:
            process_files = sorted(directory.rglob("cgroup.procs"))
            if not process_files:
                raise ValueError("Linux cgroup membership file is unavailable")
            for process_file in process_files:
                for raw_pid in process_file.read_text(encoding="utf-8").splitlines():
                    pid = int(raw_pid)
                    if pid <= 0 or pid in pids:
                        raise ValueError("Linux cgroup membership is malformed")
                    pids.add(pid)
        except (OSError, ValueError) as exc:
            raise ValueError("Linux cgroup membership is unavailable") from exc
        members: set[LinuxProcessIdentity] = set()
        for pid in pids:
            identity = self.inspect(pid)
            if identity is None or not self._is_inside_scope(
                identity.cgroup_path, scope.cgroup_path
            ):
                raise ValueError("Linux cgroup membership changed during inspection")
            members.add(identity)
        return frozenset(members)

    def signal(self, identity: LinuxProcessIdentity, sig: int) -> bool:
        fresh = self.inspect(identity.pid)
        if fresh != identity:
            return False
        pidfd_open = getattr(os, "pidfd_open", None)
        pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
        if not callable(pidfd_open) or not callable(pidfd_send_signal):
            return False
        try:
            pidfd = pidfd_open(identity.pid, 0)
        except OSError:
            return False
        try:
            if self.inspect(identity.pid) != identity:
                return False
            pidfd_send_signal(pidfd, sig)
        except OSError:
            return False
        finally:
            os.close(pidfd)
        return True

    def retire_scope(self, scope: LinuxScopeIdentity) -> bool:
        if self.scope_members(scope):
            return False
        directory = self._cgroup_directory(scope.cgroup_path)
        if not directory.exists():
            return True
        if self._systemctl is None:
            return False
        result = self._invoke([self._systemctl, "--user", "stop", scope.unit])
        return result.returncode == 0 and not directory.exists()


class LinuxLaunchBarrier:
    """Hold the systemd scope command until its identity is proven."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        kernel: LinuxCgroupKernel,
        scope_name: str,
    ) -> None:
        if not command:
            raise ValueError("Linux launch barrier command is empty")
        reader, writer = os.pipe()
        os.set_inheritable(reader, False)
        os.set_inheritable(writer, False)
        self._reader: int | None = reader
        self._writer: int | None = writer
        self._release_lock = threading.Lock()
        self._release_attempted = False
        self._may_have_released = False
        inner_command = [
            sys.executable,
            "-I",
            "-S",
            str(Path(__file__).with_name("linux_launch_barrier.py").resolve()),
            "--release-fd",
            str(reader),
            "--",
            *command,
        ]
        self.command = kernel.scope_command(scope_name, inner_command)
        self.pass_fds = (reader,)

    @property
    def may_have_released(self) -> bool:
        with self._release_lock:
            return self._may_have_released

    def after_spawn(self) -> None:
        if self._reader is None:
            raise ValueError("Linux launch barrier reader is unavailable")
        os.close(self._reader)
        self._reader = None

    def release(self) -> None:
        with self._release_lock:
            if self._release_attempted or self._reader is not None or self._writer is None:
                raise ValueError("Linux launch barrier is unavailable")
            self._release_attempted = True
            self._may_have_released = True
            try:
                written = os.write(self._writer, RELEASE_TOKEN)
            except BaseException:
                try:
                    os.close(self._writer)
                finally:
                    self._writer = None
                raise
            try:
                os.close(self._writer)
            finally:
                self._writer = None
            if written != len(RELEASE_TOKEN):
                raise OSError("Linux launch barrier release was partial")

    def close(self) -> None:
        for attribute in ("_reader", "_writer"):
            descriptor = getattr(self, attribute)
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass
            setattr(self, attribute, None)


def _scope_digest(
    scope: LinuxScopeIdentity,
    members: frozenset[LinuxProcessIdentity],
) -> str:
    evidence = {
        "scope": {
            "unit": scope.unit,
            "cgroup_path": scope.cgroup_path,
            "cgroup_device": scope.cgroup_device,
            "cgroup_inode": scope.cgroup_inode,
        },
        "members": [
            {
                "pid": member.pid,
                "start_time_ticks": member.start_time_ticks,
                "parent_pid": member.parent_pid,
                "cgroup_path": member.cgroup_path,
            }
            for member in sorted(members)
        ],
    }
    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _ancestry_closes_at_root(
    members: frozenset[LinuxProcessIdentity], root: LinuxProcessIdentity
) -> bool:
    by_pid = {member.pid: member for member in members}
    if len(by_pid) != len(members) or by_pid.get(root.pid) != root:
        return False
    for member in members:
        cursor = member
        visited: set[int] = set()
        while cursor.pid != root.pid:
            if cursor.pid in visited:
                return False
            visited.add(cursor.pid)
            parent = by_pid.get(cursor.parent_pid)
            if parent is None:
                return False
            cursor = parent
    return True


class LinuxSystemdScopeContainment:
    """Launch-scoped cleanup proven by one transient systemd scope."""

    profile_name = LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE
    cleanup_before_direct_reap = True

    def __init__(
        self,
        kernel: LinuxCgroupKernel,
        *,
        scope_name: str,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._kernel = kernel
        self._scope_name = scope_name
        self._sleeper = sleeper
        self._scope: LinuxScopeIdentity | None = None
        self._root: LinuxProcessIdentity | None = None
        self._attach_digest: str | None = None
        self._cleanup_digest: str | None = None
        self._outcome = "preflight"
        self._attached = False
        self._lock = threading.RLock()

    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        return dict(base)

    def launch_barrier(self, command: Sequence[str]) -> LinuxLaunchBarrier:
        return LinuxLaunchBarrier(
            command,
            kernel=self._kernel,
            scope_name=self._scope_name,
        )

    def _stable_members(
        self,
        scope: LinuxScopeIdentity,
        *,
        root: LinuxProcessIdentity | None,
        require_root: bool,
    ) -> frozenset[LinuxProcessIdentity]:
        prior: frozenset[LinuxProcessIdentity] | None = None
        for _attempt in range(_STABLE_SNAPSHOT_ATTEMPTS):
            try:
                try:
                    current_scope = self._kernel.scope_identity(scope.unit)
                except ValueError:
                    if require_root:
                        raise
                    current_scope = None
                members = self._kernel.scope_members(scope)
                if current_scope is None and members:
                    raise ValueError("Linux systemd scope identity is unavailable")
                if current_scope is not None and current_scope != scope:
                    raise ValueError("Linux systemd scope identity changed")
                if require_root and (
                    root is None
                    or root not in members
                    or not _ancestry_closes_at_root(members, root)
                ):
                    raise ValueError("Linux launch scope membership is unproven")
            except ValueError:
                prior = None
            else:
                if members == prior:
                    return members
                prior = members
            self._sleeper(0.05)
        raise ValueError("Linux scope membership did not converge")

    def capture_launch_root(self, root_pid: int) -> LinuxProcessIdentity:
        last_error: ValueError | None = None
        for _attempt in range(_STABLE_SNAPSHOT_ATTEMPTS):
            try:
                scope = self._kernel.scope_identity(self._scope_name)
                root = self._kernel.inspect(root_pid)
                if root is None or not SystemdCgroupV2Kernel._is_inside_scope(
                    root.cgroup_path, scope.cgroup_path
                ):
                    raise ValueError("Linux launch root scope membership is unavailable")
                self._stable_members(scope, root=root, require_root=True)
            except ValueError as exc:
                last_error = exc
                self._sleeper(0.05)
                continue
            self._scope = scope
            return root
        raise ValueError("Linux launch root scope membership is unavailable") from last_error

    def attach(
        self,
        root_pid: int,
        expected_root: LinuxProcessIdentity | None = None,
    ) -> None:
        with self._lock:
            if (
                expected_root is None
                or expected_root.pid != root_pid
                or self._scope is None
            ):
                raise ValueError("Linux containment launch identity is unavailable")
            if self._kernel.inspect(root_pid) != expected_root:
                raise ValueError("Linux containment launch identity changed")
            members = self._stable_members(
                self._scope, root=expected_root, require_root=True
            )
            self._root = expected_root
            self._attach_digest = _scope_digest(self._scope, members)
            self._outcome = "attached"
            self._attached = True

    def _wait_empty(self) -> frozenset[LinuxProcessIdentity] | None:
        assert self._scope is not None
        prior_empty = False
        for _attempt in range(_STABLE_SNAPSHOT_ATTEMPTS):
            try:
                members = self._kernel.scope_members(self._scope)
            except ValueError:
                prior_empty = False
            else:
                if not members:
                    if prior_empty:
                        return members
                    prior_empty = True
                else:
                    prior_empty = False
            self._sleeper(0.05)
        return None

    def _signal_snapshot(
        self,
        members: frozenset[LinuxProcessIdentity],
        sig: int,
    ) -> bool:
        assert self._scope is not None
        for member in sorted(members, key=lambda item: item.pid, reverse=True):
            fresh_scope = self._kernel.scope_identity(self._scope.unit)
            fresh = self._kernel.inspect(member.pid)
            if (
                fresh_scope != self._scope
                or fresh != member
                or not SystemdCgroupV2Kernel._is_inside_scope(
                    fresh.cgroup_path, self._scope.cgroup_path
                )
                or not self._kernel.signal(member, sig)
            ):
                return False
        return True

    def cleanup(self) -> bool:
        with self._lock:
            if not self._attached or self._scope is None:
                self._outcome = "cleanup_refused"
                return False
            try:
                members = self._stable_members(
                    self._scope, root=None, require_root=False
                )
                if members and not self._signal_snapshot(members, signal.SIGTERM):
                    self._outcome = "cleanup_refused"
                    return False
                empty = self._wait_empty()
                if empty is None:
                    members = self._stable_members(
                        self._scope, root=None, require_root=False
                    )
                    if members and not self._signal_snapshot(members, signal.SIGKILL):
                        self._outcome = "cleanup_refused"
                        return False
                    empty = self._wait_empty()
                if empty is None or not self._kernel.retire_scope(self._scope):
                    self._outcome = "cleanup_refused"
                    return False
                self._cleanup_digest = _scope_digest(self._scope, empty)
                self._outcome = "clean"
                return True
            except Exception:
                self._outcome = "cleanup_refused"
                return False

    def receipt(self) -> dict[str, object]:
        with self._lock:
            evidence = {
                key: value
                for key, value in (
                    ("attach", self._attach_digest),
                    ("cleanup", self._cleanup_digest),
                )
                if value is not None
            }
            return {
                "contract": "builderops_linux_containment.v1",
                "profile_name": self.profile_name,
                "scope_identity": self._scope_name,
                "evidence_digests": evidence,
                "outcome": self._outcome,
            }


def select_linux_verification_containment(
    *,
    kernel: LinuxCgroupKernel | None = None,
    scope_name: str | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> Callable[[], LinuxSystemdScopeContainment]:
    selected_kernel = kernel or SystemdCgroupV2Kernel()
    selected_kernel.preflight()
    selected_scope_name = scope_name or (
        f"{_SCOPE_PREFIX}{secrets.token_hex(12)}.scope"
    )

    def factory() -> LinuxSystemdScopeContainment:
        return LinuxSystemdScopeContainment(
            selected_kernel,
            scope_name=selected_scope_name,
            sleeper=sleeper,
        )

    return factory


__all__ = [
    "LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE",
    "LinuxCgroupKernel",
    "LinuxProcessIdentity",
    "LinuxScopeIdentity",
    "LinuxSystemdScopeContainment",
    "SystemdCgroupV2Kernel",
    "select_linux_verification_containment",
    "validated_linux_containment_receipt",
]
