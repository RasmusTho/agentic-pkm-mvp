"""Fail-closed Darwin resource-coalition containment for verification runs.

The profile deliberately uses ``proc_listallpids`` for PID enumeration and
``proc_listcoalitions`` only as a kernel task-count witness.  A PID is never an
identity by itself: every signal is fenced by a fresh PID-version and resource
coalition read.
"""

from __future__ import annotations

import ctypes
import errno
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol


DARWIN_LAUNCHD_COALITION_PROFILE = (
    "darwin-launchd-resource-coalition-v1"
)

_PROC_PIDUNIQIDENTIFIERINFO = 17
_PROC_PIDCOALITIONINFO = 20
_LISTCOALITIONS_SINGLE_TYPE = 2
_COALITION_TYPE_RESOURCE = 0
_COALITION_NUM_TYPES = 2
_STABLE_SNAPSHOT_ATTEMPTS = 8


@dataclass(frozen=True, order=True)
class ProcessIdentity:
    """One PID-version bound to its current resource coalition and parent."""

    pid: int
    pid_version: int
    unique_id: int
    parent_unique_id: int
    coalition_id: int


@dataclass(frozen=True)
class CoalitionSnapshot:
    coalition_id: int
    members: frozenset[ProcessIdentity]
    kernel_task_count: int


class DarwinCoalitionKernel(Protocol):
    """Narrow injectable kernel interface used by the containment profile."""

    def list_pids(self) -> tuple[int, ...]: ...

    def inspect(self, pid: int) -> ProcessIdentity | None: ...

    def coalition_task_count(self, coalition_id: int) -> int: ...

    def signal(self, identity: ProcessIdentity, sig: int) -> bool: ...


class _ProcUniqIdentifierInfo(ctypes.Structure):
    _fields_ = [
        ("p_uuid", ctypes.c_ubyte * 16),
        ("p_uniqueid", ctypes.c_uint64),
        ("p_puniqueid", ctypes.c_uint64),
        ("p_idversion", ctypes.c_int32),
        ("p_orig_ppidversion", ctypes.c_int32),
        ("p_reserve2", ctypes.c_uint64),
        ("p_reserve3", ctypes.c_uint64),
    ]


class _ProcPidCoalitionInfo(ctypes.Structure):
    _fields_ = [
        ("coalition_id", ctypes.c_uint64 * _COALITION_NUM_TYPES),
        ("reserved1", ctypes.c_uint64),
        ("reserved2", ctypes.c_uint64),
        ("reserved3", ctypes.c_uint64),
    ]


class _ProcInfoCoalition(ctypes.Structure):
    _fields_ = [
        ("coalition_id", ctypes.c_uint64),
        ("coalition_type", ctypes.c_uint32),
        ("coalition_tasks", ctypes.c_uint32),
    ]


class _AuditToken(ctypes.Structure):
    _fields_ = [("val", ctypes.c_uint32 * 8)]


class DarwinLibprocKernel:
    """Availability-checked adapter for the allowlisted Darwin private ABI."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise ValueError("Darwin containment is unavailable on this platform")
        try:
            library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            list_all_pids = library.proc_listallpids
            pid_info = library.proc_pidinfo
            list_coalitions = library.proc_listcoalitions
            signal_with_audit_token = library.proc_signal_with_audittoken
        except (OSError, AttributeError) as exc:
            raise ValueError(
                "Darwin containment private symbols are unavailable"
            ) from exc
        list_all_pids.argtypes = [ctypes.c_void_p, ctypes.c_int]
        list_all_pids.restype = ctypes.c_int
        pid_info.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        pid_info.restype = ctypes.c_int
        list_coalitions.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        list_coalitions.restype = ctypes.c_int
        signal_with_audit_token.argtypes = [
            ctypes.POINTER(_AuditToken),
            ctypes.c_int,
        ]
        signal_with_audit_token.restype = ctypes.c_int
        self._library = library
        self._list_all_pids = list_all_pids
        self._pid_info = pid_info
        self._list_coalitions = list_coalitions
        self._signal_with_audit_token = signal_with_audit_token

    def list_pids(self) -> tuple[int, ...]:
        count = self._list_all_pids(None, 0)
        if count <= 0:
            raise ValueError("Darwin containment PID enumeration failed")
        for _ in range(2):
            capacity = count + 64
            buffer = (ctypes.c_int * capacity)()
            observed = self._list_all_pids(buffer, ctypes.sizeof(buffer))
            if 0 < observed < capacity:
                return tuple(
                    sorted({int(buffer[index]) for index in range(observed) if buffer[index] > 0})
                )
            count = max(count * 2, observed)
        raise ValueError("Darwin containment PID enumeration did not converge")

    def _read_pid_info(
        self,
        pid: int,
        flavor: int,
        value: ctypes.Structure,
    ) -> int:
        return int(
            self._pid_info(
                pid,
                flavor,
                0,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        )

    def inspect(self, pid: int) -> ProcessIdentity | None:
        if pid <= 0:
            return None
        first = _ProcUniqIdentifierInfo()
        coalition = _ProcPidCoalitionInfo()
        second = _ProcUniqIdentifierInfo()
        if self._read_pid_info(pid, _PROC_PIDUNIQIDENTIFIERINFO, first) != ctypes.sizeof(first):
            return None
        if self._read_pid_info(pid, _PROC_PIDCOALITIONINFO, coalition) != ctypes.sizeof(coalition):
            return None
        if self._read_pid_info(pid, _PROC_PIDUNIQIDENTIFIERINFO, second) != ctypes.sizeof(second):
            return None
        if (
            first.p_idversion != second.p_idversion
            or first.p_uniqueid != second.p_uniqueid
            or first.p_puniqueid != second.p_puniqueid
        ):
            return None
        coalition_id = int(coalition.coalition_id[_COALITION_TYPE_RESOURCE])
        if coalition_id <= 0 or first.p_idversion < 0:
            return None
        return ProcessIdentity(
            pid=pid,
            pid_version=int(first.p_idversion),
            unique_id=int(first.p_uniqueid),
            parent_unique_id=int(first.p_puniqueid),
            coalition_id=coalition_id,
        )

    def coalition_task_count(self, coalition_id: int) -> int:
        record_size = ctypes.sizeof(_ProcInfoCoalition)
        required = int(
            self._list_coalitions(
                _LISTCOALITIONS_SINGLE_TYPE,
                _COALITION_TYPE_RESOURCE,
                None,
                0,
            )
        )
        if required <= 0 or required % record_size:
            raise ValueError("Darwin containment coalition witness is malformed")
        buffer = ctypes.create_string_buffer(required)
        observed = int(
            self._list_coalitions(
                _LISTCOALITIONS_SINGLE_TYPE,
                _COALITION_TYPE_RESOURCE,
                buffer,
                required,
            )
        )
        if observed != required:
            raise ValueError("Darwin containment coalition witness changed")
        records = (
            _ProcInfoCoalition * (observed // record_size)
        ).from_buffer(buffer)
        matches = [
            int(record.coalition_tasks)
            for record in records
            if int(record.coalition_id) == coalition_id
            and int(record.coalition_type) == _COALITION_TYPE_RESOURCE
        ]
        if len(matches) != 1 or matches[0] <= 0:
            raise ValueError("Darwin containment coalition witness is unavailable")
        return matches[0]

    def signal(self, identity: ProcessIdentity, sig: int) -> bool:
        token = _AuditToken()
        # libproc's own wrappers consume audit_token.val[5] as PID and val[7]
        # as PID-version.  The kernel signal call compares that identity
        # atomically, so PID reuse after pre-signal inspection cannot redirect
        # the signal to a new process.
        token.val[5] = identity.pid
        token.val[7] = identity.pid_version
        result = int(self._signal_with_audit_token(ctypes.byref(token), sig))
        return result in (0, errno.ESRCH)


def _sample_coalition(
    kernel: DarwinCoalitionKernel,
    coalition_id: int,
) -> CoalitionSnapshot:
    members = frozenset(
        identity
        for pid in kernel.list_pids()
        if (identity := kernel.inspect(pid)) is not None
        and identity.coalition_id == coalition_id
    )
    kernel_count = kernel.coalition_task_count(coalition_id)
    if kernel_count != len(members):
        raise ValueError("Darwin containment coalition task count mismatched")
    return CoalitionSnapshot(coalition_id, members, kernel_count)


def _stable_snapshot(
    kernel: DarwinCoalitionKernel,
    coalition_id: int,
) -> CoalitionSnapshot:
    prior: CoalitionSnapshot | None = None
    for _ in range(_STABLE_SNAPSHOT_ATTEMPTS):
        try:
            current = _sample_coalition(kernel, coalition_id)
        except ValueError:
            prior = None
            continue
        if current == prior:
            return current
        prior = current
    raise ValueError("Darwin containment snapshots did not converge")


def _trusted_baseline(
    kernel: DarwinCoalitionKernel,
    *,
    current_pid: int,
) -> tuple[int, frozenset[ProcessIdentity]]:
    current = kernel.inspect(current_pid)
    if current is None:
        raise ValueError("Darwin containment cannot inspect the current CLI")
    stable = _stable_snapshot(kernel, current.coalition_id)
    by_unique_id = {
        identity.unique_id: identity for identity in stable.members
    }
    if len(by_unique_id) != len(stable.members):
        raise ValueError("Darwin containment process identities are ambiguous")
    baseline: set[ProcessIdentity] = set()
    cursor = current
    visited: set[int] = set()
    while True:
        if (
            cursor.unique_id in visited
            or by_unique_id.get(cursor.unique_id) != cursor
        ):
            raise ValueError("Darwin containment ancestor chain is unproven")
        visited.add(cursor.unique_id)
        baseline.add(cursor)
        if cursor.parent_unique_id <= 0:
            break
        parent = by_unique_id.get(cursor.parent_unique_id)
        if parent is None:
            outside_matches = [
                identity
                for pid in kernel.list_pids()
                if (identity := kernel.inspect(pid)) is not None
                and identity.unique_id == cursor.parent_unique_id
            ]
            if len(outside_matches) != 1:
                raise ValueError("Darwin containment ancestor is uninspectable")
            if outside_matches[0].coalition_id == current.coalition_id:
                raise ValueError("Darwin containment ancestor chain is incomplete")
            break
        if parent.coalition_id != current.coalition_id:
            break
        cursor = parent
    if stable.members != frozenset(baseline):
        raise ValueError("Darwin containment coalition has unrelated members")
    return current.coalition_id, frozenset(baseline)


class DarwinLaunchdCoalitionContainment:
    """Launch-scoped cleanup proven by resource-coalition snapshots."""

    def __init__(
        self,
        kernel: DarwinCoalitionKernel,
        *,
        coalition_id: int,
        baseline: frozenset[ProcessIdentity],
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._kernel = kernel
        self._coalition_id = coalition_id
        self._baseline = baseline
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._attached = False

    def _assert_baseline_only(self) -> None:
        stable = _stable_snapshot(self._kernel, self._coalition_id)
        if stable.members != self._baseline:
            raise ValueError("Darwin containment baseline changed before launch")

    def environment(self, base: Mapping[str, str]) -> dict[str, str]:
        self._assert_baseline_only()
        return dict(base)

    def attach(self, root_pid: int) -> None:
        stable = _stable_snapshot(self._kernel, self._coalition_id)
        if not self._baseline.issubset(stable.members):
            raise ValueError("Darwin containment baseline escaped")
        root = next(
            (member for member in stable.members if member.pid == root_pid),
            None,
        )
        if root is None or root in self._baseline:
            raise ValueError("Darwin containment launch root is unproven")
        by_unique_id = {
            member.unique_id: member for member in stable.members
        }
        for member in stable.members - self._baseline:
            cursor = member
            visited: set[int] = set()
            while cursor != root:
                if cursor.unique_id in visited:
                    raise ValueError("Darwin containment launch ancestry cycled")
                visited.add(cursor.unique_id)
                parent = by_unique_id.get(cursor.parent_unique_id)
                if parent is None or parent in self._baseline:
                    raise ValueError(
                        "Darwin containment launch ancestry escaped root"
                    )
                cursor = parent
        self._attached = True

    def _signal_identity(self, identity: ProcessIdentity, sig: int) -> bool:
        fresh = self._kernel.inspect(identity.pid)
        if fresh != identity or fresh.coalition_id != self._coalition_id:
            return False
        try:
            return self._kernel.signal(identity, sig)
        except (OSError, PermissionError, ValueError):
            return False

    def _wait_for_snapshot(
        self,
        *,
        timeout: float,
        baseline_only: bool,
    ) -> CoalitionSnapshot | None:
        deadline = self._monotonic() + timeout
        prior: CoalitionSnapshot | None = None
        while True:
            try:
                current = _sample_coalition(
                    self._kernel, self._coalition_id
                )
            except ValueError:
                prior = None
            else:
                eligible = (
                    not baseline_only or current.members == self._baseline
                )
                if eligible and current == prior:
                    return current
                prior = current if eligible else None
            if self._monotonic() >= deadline:
                return None
            self._sleeper(0.05)

    def cleanup(self) -> bool:
        if not self._attached:
            return False
        try:
            stable = self._wait_for_snapshot(
                timeout=1.0, baseline_only=False
            )
            if stable is None or not self._baseline.issubset(stable.members):
                return False
            targets = sorted(stable.members - self._baseline)
            if not targets:
                return self._wait_for_snapshot(
                    timeout=1.0, baseline_only=True
                ) is not None
            if not all(
                self._signal_identity(target, signal.SIGTERM)
                for target in targets
            ):
                return False
            if self._wait_for_snapshot(
                timeout=1.0, baseline_only=True
            ) is not None:
                return True
            stable = self._wait_for_snapshot(
                timeout=1.0, baseline_only=False
            )
            if stable is None or not self._baseline.issubset(stable.members):
                return False
            targets = sorted(stable.members - self._baseline)
            if not all(
                self._signal_identity(target, signal.SIGKILL)
                for target in targets
            ):
                return False
            return self._wait_for_snapshot(
                timeout=5.0, baseline_only=True
            ) is not None
        except Exception:
            return False


def select_verification_containment(
    profile: str | None,
    *,
    platform: str = sys.platform,
    kernel: DarwinCoalitionKernel | None = None,
    current_pid: int | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Callable[[], DarwinLaunchdCoalitionContainment]:
    """Preflight and return the one allowlisted production containment factory."""

    if profile != DARWIN_LAUNCHD_COALITION_PROFILE:
        raise ValueError("verification containment profile is absent or unsupported")
    if platform != "darwin":
        raise ValueError("verification containment profile is unsupported on this platform")
    selected_kernel = kernel or DarwinLibprocKernel()
    coalition_id, baseline = _trusted_baseline(
        selected_kernel,
        current_pid=current_pid if current_pid is not None else os.getpid(),
    )

    def factory() -> DarwinLaunchdCoalitionContainment:
        return DarwinLaunchdCoalitionContainment(
            selected_kernel,
            coalition_id=coalition_id,
            baseline=baseline,
            sleeper=sleeper,
            monotonic=monotonic,
        )

    return factory
