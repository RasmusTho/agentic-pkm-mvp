"""Cross-process per-binding shared/exclusive effect leases (MVR-05A6)."""

from __future__ import annotations

import copy
import ctypes
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, TypedDict, cast
from uuid import uuid4

from app.instance._storage_boundary import _StorageMutationCapability
from app.instance.ownership_ledger import OwnershipLedger
from app.instance.vault_registry import VaultRegistryStore


LEASE_SCHEMA = "agentic-pkm.binding-effect-lease.v1"
JOURNAL_SCHEMA = "agentic-pkm.binding-effect-lease-journal.v1"


_LEASE_LOCK_FDS: set[int] = set()
_LEASE_LOCK_FDS_LOCK = threading.Lock()


def _lease_locks_before_fork() -> None:
    _LEASE_LOCK_FDS_LOCK.acquire()


def _lease_locks_after_fork_parent() -> None:
    _LEASE_LOCK_FDS_LOCK.release()


def _lease_locks_after_fork_child() -> None:
    try:
        for descriptor in _LEASE_LOCK_FDS:
            try:
                os.close(descriptor)
            except OSError:
                pass
        _LEASE_LOCK_FDS.clear()
    finally:
        _LEASE_LOCK_FDS_LOCK.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_lease_locks_before_fork,
        after_in_parent=_lease_locks_after_fork_parent,
        after_in_child=_lease_locks_after_fork_child,
    )


def _open_lease_descriptor(path: Path, flags: int, mode: int = 0o600) -> int:
    with _LEASE_LOCK_FDS_LOCK:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                flags | getattr(os, "O_CLOEXEC", 0),
                mode,
            )
            os.set_inheritable(descriptor, False)
            _LEASE_LOCK_FDS.add(descriptor)
            return descriptor
        except BaseException:
            if descriptor is not None:
                _LEASE_LOCK_FDS.discard(descriptor)
                os.close(descriptor)
            raise


def _close_lease_descriptor(descriptor: int) -> None:
    with _LEASE_LOCK_FDS_LOCK:
        _LEASE_LOCK_FDS.discard(descriptor)
        os.close(descriptor)


class _DarwinProcBsdInfo(ctypes.Structure):
    """Native ``proc_bsdinfo`` layout from Darwin ``sys/proc_info.h``."""

    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


class _DarwinProcBsdShortInfo(ctypes.Structure):
    """Native ``proc_bsdshortinfo`` used to identify an unreaped zombie."""

    _fields_ = [
        ("pbsi_pid", ctypes.c_uint32),
        ("pbsi_ppid", ctypes.c_uint32),
        ("pbsi_pgid", ctypes.c_uint32),
        ("pbsi_status", ctypes.c_uint32),
        ("pbsi_comm", ctypes.c_char * 16),
        ("pbsi_flags", ctypes.c_uint32),
        ("pbsi_uid", ctypes.c_uint32),
        ("pbsi_gid", ctypes.c_uint32),
        ("pbsi_ruid", ctypes.c_uint32),
        ("pbsi_rgid", ctypes.c_uint32),
        ("pbsi_svuid", ctypes.c_uint32),
        ("pbsi_svgid", ctypes.c_uint32),
        ("pbsi_rfu", ctypes.c_uint32),
    ]


class BindingEffectLeaseError(RuntimeError):
    """The binding effect window cannot be entered or recovered safely."""


class BindingEffectLeaseTimeout(BindingEffectLeaseError):
    """The requested effect window did not become available in time."""


class _HolderState(TypedDict):
    holderId: str
    pid: int
    processStart: str
    ticket: int
    mode: str


class _LeaseState(TypedDict):
    schema: str
    vaultBindingId: str
    generation: int
    nextTicket: int
    sharedHolders: list[_HolderState]
    exclusivePending: list[_HolderState]
    exclusiveHolder: _HolderState | None


@dataclass(frozen=True)
class BindingEffectLeaseObservation:
    vault_binding_id: str
    generation: int
    shared_count: int
    exclusive_pending_count: int
    exclusive_held: bool


@dataclass
class _HeldLease:
    vault_binding_id: str
    holder_id: str
    mode: str
    descriptor: int
    owner_pid: int


class BindingEffectLeaseManager:
    """Persist fairness state while `flock` owns effect-window exclusion."""

    def __init__(
        self,
        *,
        registry_store: VaultRegistryStore,
        ownership_ledger: OwnershipLedger,
        state_root: Path,
        capability: _StorageMutationCapability,
        poll_interval: float = 0.02,
    ) -> None:
        self.registry_store = registry_store
        self.ownership_ledger = ownership_ledger
        self.state_root = Path(state_root)
        self.capability = capability
        self.poll_interval = poll_interval

    @contextmanager
    def shared_effect(
        self,
        vault_binding_id: str,
        *,
        channel_id: str,
        root: Path,
        timeout: float | None = None,
    ) -> Iterator[BindingEffectLeaseObservation]:
        with self._acquire(
            vault_binding_id,
            mode="shared",
            channel_id=channel_id,
            root=root,
            timeout=timeout,
        ):
            yield self.observe(vault_binding_id)

    @contextmanager
    def exclusive_change(
        self,
        vault_binding_id: str,
        *,
        channel_id: str,
        root: Path,
        timeout: float | None = None,
    ) -> Iterator[BindingEffectLeaseObservation]:
        with self._acquire(
            vault_binding_id,
            mode="exclusive",
            channel_id=channel_id,
            root=root,
            timeout=timeout,
        ):
            yield self.observe(vault_binding_id)

    def observe(self, vault_binding_id: str) -> BindingEffectLeaseObservation:
        with self._state_locked(vault_binding_id):
            state = self._load_reconciled_locked(vault_binding_id)
            return BindingEffectLeaseObservation(
                vault_binding_id=vault_binding_id,
                generation=int(state["generation"]),
                shared_count=len(state["sharedHolders"]),
                exclusive_pending_count=len(state["exclusivePending"]),
                exclusive_held=state["exclusiveHolder"] is not None,
            )

    def persisted_state(self, vault_binding_id: str) -> dict[str, object]:
        with self._state_locked(vault_binding_id):
            return dict(copy.deepcopy(self._load_reconciled_locked(vault_binding_id)))

    def wait_for_exclusive_pending(self, vault_binding_id: str, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.observe(vault_binding_id).exclusive_pending_count:
                return True
            time.sleep(self.poll_interval)
        return False

    @contextmanager
    def _acquire(
        self,
        vault_binding_id: str,
        *,
        mode: str,
        channel_id: str,
        root: Path,
        timeout: float | None,
    ) -> Iterator[_HeldLease]:
        if not vault_binding_id.strip() or mode not in {"shared", "exclusive"}:
            raise BindingEffectLeaseError("binding and lease mode must be explicit")
        self._ensure_state_root()
        holder_id = ""
        pending: _HolderState | None = None
        pending_descriptor: int | None = None
        descriptor: int | None = None
        held: _HeldLease | None = None
        try:
            descriptor = self._open_private_lease_lock(self._gate_path(vault_binding_id))
            holder_id = f"holder-{uuid4()}"
            deadline = None if timeout is None else time.monotonic() + timeout
            if mode == "exclusive":
                with self.ownership_ledger.active_binding_fence(
                    vault_binding_id, channel_id=channel_id, root=root
                ):
                    with self._state_locked(vault_binding_id):
                        current = self._load_reconciled_locked(vault_binding_id)
                        pending_descriptor = self._open_pending_activity(
                            vault_binding_id, holder_id, create=True
                        )
                        try:
                            fcntl.flock(
                                pending_descriptor,
                                fcntl.LOCK_EX | fcntl.LOCK_NB,
                            )
                        except BlockingIOError as exc:
                            raise BindingEffectLeaseError(
                                "exclusive waiter activity identity is already locked"
                            ) from exc
                        pending = self._holder(
                            holder_id,
                            ticket=int(current["nextTicket"]),
                            mode="pending",
                        )
                        updated = copy.deepcopy(current)
                        updated["nextTicket"] = int(current["nextTicket"]) + 1
                        updated["exclusivePending"].append(pending)
                        self._commit_locked(vault_binding_id, current, updated)

            while True:
                with self.ownership_ledger.active_binding_fence(
                    vault_binding_id, channel_id=channel_id, root=root
                ):
                    with self._state_locked(vault_binding_id):
                        current = self._load_reconciled_locked(vault_binding_id)
                        if mode == "shared":
                            available = (
                                not current["exclusivePending"]
                                and current["exclusiveHolder"] is None
                            )
                            lock_mode = fcntl.LOCK_SH
                        else:
                            queue = current["exclusivePending"]
                            available = (
                                bool(queue)
                                and queue[0]["holderId"] == holder_id
                                and not current["sharedHolders"]
                                and current["exclusiveHolder"] is None
                            )
                            lock_mode = fcntl.LOCK_EX
                        if available:
                            try:
                                fcntl.flock(descriptor, lock_mode | fcntl.LOCK_NB)
                            except BlockingIOError:
                                pass
                            else:
                                holder = self._holder(
                                    holder_id,
                                    ticket=(
                                        int(pending["ticket"])
                                        if pending is not None
                                        else int(current["nextTicket"])
                                    ),
                                    mode=mode,
                                )
                                updated = copy.deepcopy(current)
                                if mode == "shared":
                                    updated["nextTicket"] = int(current["nextTicket"]) + 1
                                    updated["sharedHolders"].append(holder)
                                else:
                                    updated["exclusivePending"] = [
                                        item
                                        for item in current["exclusivePending"]
                                        if item["holderId"] != holder_id
                                    ]
                                    updated["exclusiveHolder"] = holder
                                    if pending_descriptor is None:
                                        raise BindingEffectLeaseError(
                                            "exclusive waiter activity identity is missing"
                                        )
                                    self._unlink_pending_activity_locked(
                                        vault_binding_id,
                                        holder_id,
                                        pending_descriptor,
                                    )
                                self._commit_locked(vault_binding_id, current, updated)
                                if pending_descriptor is not None:
                                    self._close_pending_activity(
                                        pending_descriptor,
                                    )
                                    pending_descriptor = None
                                    pending = None
                                held = _HeldLease(
                                    vault_binding_id,
                                    holder_id,
                                    mode,
                                    descriptor,
                                    os.getpid(),
                                )
                                break
                if deadline is not None and time.monotonic() >= deadline:
                    raise BindingEffectLeaseTimeout(
                        f"timed out waiting for {mode} binding effect lease"
                    )
                time.sleep(self.poll_interval)
            if held is None:
                raise BindingEffectLeaseError("binding effect acquisition ended without a holder")
            yield held
        finally:
            try:
                if held is not None:
                    self._release(held)
                elif pending is not None:
                    self._discard_pending(
                        vault_binding_id,
                        holder_id,
                        pending_descriptor,
                    )
            finally:
                try:
                    if pending_descriptor is not None:
                        self._close_pending_activity(
                            pending_descriptor,
                        )
                finally:
                    if descriptor is not None and held is None:
                        try:
                            fcntl.flock(descriptor, fcntl.LOCK_UN)
                        finally:
                            _close_lease_descriptor(descriptor)

    def _release(self, held: _HeldLease) -> None:
        if held.owner_pid != os.getpid():
            raise BindingEffectLeaseError(
                "a fork child cannot release its parent's binding effect lease"
            )
        try:
            with self._state_locked(held.vault_binding_id):
                current = self._load_reconciled_locked(held.vault_binding_id)
                updated = copy.deepcopy(current)
                if held.mode == "shared":
                    before = len(updated["sharedHolders"])
                    updated["sharedHolders"] = [
                        item
                        for item in updated["sharedHolders"]
                        if item["holderId"] != held.holder_id
                    ]
                    found = len(updated["sharedHolders"]) != before
                else:
                    found = bool(
                        updated["exclusiveHolder"]
                        and updated["exclusiveHolder"]["holderId"] == held.holder_id
                    )
                    if found:
                        updated["exclusiveHolder"] = None
                if not found:
                    raise BindingEffectLeaseError("held binding effect lease state is missing")
                self._commit_locked(held.vault_binding_id, current, updated)
        finally:
            try:
                fcntl.flock(held.descriptor, fcntl.LOCK_UN)
            finally:
                _close_lease_descriptor(held.descriptor)

    def _discard_pending(
        self,
        vault_binding_id: str,
        holder_id: str,
        pending_descriptor: int | None,
    ) -> None:
        with self._state_locked(vault_binding_id):
            current = self._load_reconciled_locked(vault_binding_id)
            updated = copy.deepcopy(current)
            updated["exclusivePending"] = [
                item for item in updated["exclusivePending"] if item["holderId"] != holder_id
            ]
            if updated != current:
                if pending_descriptor is None:
                    raise BindingEffectLeaseError("exclusive waiter activity identity is missing")
                self._unlink_pending_activity_locked(
                    vault_binding_id,
                    holder_id,
                    pending_descriptor,
                )
                self._commit_locked(vault_binding_id, current, updated)

    @contextmanager
    def _state_locked(self, vault_binding_id: str) -> Iterator[None]:
        self._ensure_state_root()
        descriptor: int | None = None
        try:
            descriptor = self._open_private_lease_lock(self._lock_path(vault_binding_id))
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                self._recover_journal_locked(vault_binding_id)
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            if descriptor is not None:
                _close_lease_descriptor(descriptor)

    def _load_reconciled_locked(self, vault_binding_id: str) -> _LeaseState:
        state = self._load_state_locked(vault_binding_id)
        updated = copy.deepcopy(state)
        referenced_activity = {
            self._pending_activity_path(vault_binding_id, item["holderId"])
            for item in state["exclusivePending"]
        }
        self._scavenge_pending_activity_locked(vault_binding_id, referenced_activity)
        pending: list[_HolderState] = []
        abandoned: list[tuple[_HolderState, int | None]] = []
        try:
            for item in state["exclusivePending"]:
                if self._pending_waiter_active(
                    vault_binding_id,
                    item,
                    abandoned,
                ):
                    pending.append(item)
            updated["exclusivePending"] = pending
            gate: int | None = None
            try:
                gate = self._open_private_lease_lock(self._gate_path(vault_binding_id))
                try:
                    fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    updated["sharedHolders"] = [
                        item for item in state["sharedHolders"] if self._holder_alive(item)
                    ]
                    holder = state["exclusiveHolder"]
                    if holder is not None and not self._holder_alive(holder):
                        updated["exclusiveHolder"] = None
                else:
                    updated["sharedHolders"] = []
                    updated["exclusiveHolder"] = None
                    fcntl.flock(gate, fcntl.LOCK_UN)
            finally:
                if gate is not None:
                    _close_lease_descriptor(gate)
            if updated != state:
                for item, descriptor in abandoned:
                    if descriptor is not None:
                        self._unlink_pending_activity_locked(
                            vault_binding_id,
                            item["holderId"],
                            descriptor,
                        )
                committed = self._commit_locked(vault_binding_id, state, updated)
                self._scavenge_pending_activity_locked(
                    vault_binding_id,
                    {
                        self._pending_activity_path(vault_binding_id, item["holderId"])
                        for item in committed["exclusivePending"]
                    },
                )
                return committed
            return state
        finally:
            for _, descriptor in abandoned:
                if descriptor is not None:
                    self._close_pending_activity(descriptor)

    def _load_state_locked(self, vault_binding_id: str) -> _LeaseState:
        path = self._state_path(vault_binding_id)
        if os.path.lexists(path):
            try:
                value = json.loads(self._read_private_text(path))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BindingEffectLeaseError("binding effect lease state is corrupt") from exc
            local_state = self._validate_state(vault_binding_id, value)
            registry_state = self._registry_state(vault_binding_id)
            if local_state != registry_state:
                raise BindingEffectLeaseError(
                    "binding effect lease state diverges from registry without a journal"
                )
            return local_state
        return self._registry_state(vault_binding_id)

    def _commit_locked(
        self,
        vault_binding_id: str,
        previous: Mapping[str, object],
        candidate: Mapping[str, object],
    ) -> _LeaseState:
        previous_state = self._validate_state(vault_binding_id, previous)
        next_state = self._validate_state(
            vault_binding_id,
            {**copy.deepcopy(candidate), "generation": int(previous_state["generation"]) + 1},
        )
        journal = {
            "schema": JOURNAL_SCHEMA,
            "vaultBindingId": vault_binding_id,
            "previous": previous_state,
            "next": next_state,
        }
        self._atomic_private_json(self._journal_path(vault_binding_id), journal)
        self._atomic_private_json(self._state_path(vault_binding_id), next_state)
        try:
            self.registry_store.set_binding_effect_lease_state(
                vault_binding_id,
                next_state,
                _capability=self.capability,
            )
        except Exception:
            try:
                registry_state = self._registry_state(vault_binding_id)
            except Exception:
                raise
            if registry_state == next_state:
                self._atomic_private_json(self._state_path(vault_binding_id), next_state)
                self._journal_path(vault_binding_id).unlink(missing_ok=True)
                self._fsync_directory(self.state_root)
                return next_state
            if registry_state == previous_state:
                self._atomic_private_json(self._state_path(vault_binding_id), previous_state)
                self._journal_path(vault_binding_id).unlink(missing_ok=True)
                self._fsync_directory(self.state_root)
                raise
            raise BindingEffectLeaseError(
                "binding effect lease commit diverges from both journal endpoints"
            )
        self._journal_path(vault_binding_id).unlink(missing_ok=True)
        self._fsync_directory(self.state_root)
        return next_state

    def _recover_journal_locked(self, vault_binding_id: str) -> None:
        path = self._journal_path(vault_binding_id)
        if not os.path.lexists(path):
            return
        try:
            value = json.loads(self._read_private_text(path))
            if (
                not isinstance(value, dict)
                or value.get("schema") != JOURNAL_SCHEMA
                or value.get("vaultBindingId") != vault_binding_id
            ):
                raise ValueError
            previous = self._validate_state(vault_binding_id, value["previous"])
            next_state = self._validate_state(vault_binding_id, value["next"])
        except (
            OSError,
            UnicodeError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise BindingEffectLeaseError("binding effect lease journal is invalid") from exc
        registry_state = self._registry_state(vault_binding_id)
        if registry_state == next_state:
            recovered = next_state
        elif registry_state == previous:
            recovered = previous
        else:
            raise BindingEffectLeaseError(
                "binding effect lease journal diverges from registry state"
            )
        self._atomic_private_json(self._state_path(vault_binding_id), recovered)
        path.unlink()
        self._fsync_directory(self.state_root)

    def _registry_state(self, vault_binding_id: str) -> _LeaseState:
        snapshot = self.registry_store.load()
        states = snapshot.extensions.get("bindingEffectLeases") or {}
        if not isinstance(states, Mapping):
            raise BindingEffectLeaseError("registry binding effect lease state is invalid")
        value = states.get(vault_binding_id)
        return (
            self._empty_state(vault_binding_id)
            if value is None
            else self._validate_state(vault_binding_id, value)
        )

    def _holder(self, holder_id: str, *, ticket: int, mode: str) -> _HolderState:
        return {
            "holderId": holder_id,
            "pid": os.getpid(),
            "processStart": self._process_start(os.getpid()),
            "ticket": ticket,
            "mode": mode,
        }

    def _holder_alive(self, holder: Mapping[str, object]) -> bool:
        try:
            raw_pid = holder["pid"]
            if not isinstance(raw_pid, int) or isinstance(raw_pid, bool):
                return False
            pid = raw_pid
            os.kill(pid, 0)
        except (KeyError, ProcessLookupError, ValueError, TypeError):
            return False
        except PermissionError:
            pass
        start, state = self._process_identity(pid)
        return state != "Z" and str(holder.get("processStart") or "") == start

    def _pending_waiter_active(
        self,
        vault_binding_id: str,
        holder: _HolderState,
        abandoned: list[tuple[_HolderState, int | None]],
    ) -> bool:
        """Require both a live process incarnation and an active waiter lock."""

        holder_id = str(holder.get("holderId") or "")
        if not self._holder_alive(holder):
            abandoned.append((holder, None))
            return False
        descriptor: int | None = None
        try:
            try:
                descriptor = self._open_pending_activity(vault_binding_id, holder_id, create=False)
            except FileNotFoundError:
                abandoned.append((holder, None))
                return False
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            abandoned.append((holder, descriptor))
            return False
        finally:
            if descriptor is not None and not any(
                owned_descriptor == descriptor for _, owned_descriptor in abandoned
            ):
                self._close_pending_activity(descriptor)

    def _open_pending_activity(
        self,
        vault_binding_id: str,
        holder_id: str,
        *,
        create: bool,
    ) -> int:
        return self._open_pending_activity_path(
            self._pending_activity_path(vault_binding_id, holder_id),
            create=create,
        )

    def _open_pending_activity_path(self, path: Path, *, create: bool = False) -> int:
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor: int | None = None
        try:
            descriptor = _open_lease_descriptor(path, flags)
            if create:
                os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o777 != 0o600
            ):
                raise BindingEffectLeaseError("exclusive waiter activity file is unsafe")
            return descriptor
        except BaseException:
            if descriptor is not None:
                _close_lease_descriptor(descriptor)
            raise

    @staticmethod
    def _close_pending_activity(descriptor: int) -> None:
        _close_lease_descriptor(descriptor)

    def _unlink_pending_activity_locked(
        self,
        vault_binding_id: str,
        holder_id: str,
        descriptor: int,
    ) -> None:
        self._unlink_pending_activity_path_locked(
            self._pending_activity_path(vault_binding_id, holder_id),
            descriptor,
        )

    def _scavenge_pending_activity_locked(
        self,
        vault_binding_id: str,
        referenced: set[Path],
    ) -> None:
        stem = self._binding_stem(vault_binding_id)
        for path in self.state_root.glob(f"{stem}.*.pending.lock"):
            if path in referenced:
                continue
            suffix = path.name.removeprefix(f"{stem}.").removesuffix(".pending.lock")
            if len(suffix) != 64 or any(
                character not in "0123456789abcdef" for character in suffix
            ):
                raise BindingEffectLeaseError("exclusive waiter activity filename is invalid")
            descriptor: int | None = None
            try:
                try:
                    descriptor = self._open_pending_activity_path(path)
                except FileNotFoundError:
                    continue
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                self._unlink_pending_activity_path_locked(path, descriptor)
            finally:
                if descriptor is not None:
                    self._close_pending_activity(descriptor)

    def _unlink_pending_activity_path_locked(self, path: Path, descriptor: int) -> None:
        try:
            path_metadata = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return
        descriptor_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(path_metadata.st_mode) or (
            path_metadata.st_dev,
            path_metadata.st_ino,
        ) != (descriptor_metadata.st_dev, descriptor_metadata.st_ino):
            raise BindingEffectLeaseError("exclusive waiter activity path identity changed")
        path.unlink()
        self._fsync_directory(self.state_root)

    @staticmethod
    def _process_start(pid: int) -> str:
        return BindingEffectLeaseManager._process_identity(pid)[0]

    @staticmethod
    def _process_identity(pid: int) -> tuple[str, str]:
        stat_path = Path(f"/proc/{pid}/stat")
        try:
            raw = stat_path.read_text(encoding="utf-8")
            remainder = raw[raw.rindex(")") + 2 :].split()
            return f"proc:{remainder[19]}", remainder[0]
        except (OSError, IndexError, ValueError):
            if sys.platform == "darwin":
                return BindingEffectLeaseManager._darwin_process_identity(pid)
            raise BindingEffectLeaseError("a trustworthy process-incarnation token is unavailable")

    @staticmethod
    def _darwin_process_identity(pid: int) -> tuple[str, str]:
        """Return a microsecond-resolution native process incarnation on Darwin."""

        try:
            library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            proc_pidinfo = library.proc_pidinfo
        except (AttributeError, OSError) as exc:
            raise BindingEffectLeaseError(
                "a trustworthy process-incarnation token is unavailable"
            ) from exc
        proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        proc_pidinfo.restype = ctypes.c_int
        info = _DarwinProcBsdInfo()
        result = proc_pidinfo(
            pid,
            3,  # PROC_PIDTBSDINFO
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if (
            result == ctypes.sizeof(info)
            and info.pbi_pid == pid
            and info.pbi_status in {1, 2, 3, 4, 5}
            and info.pbi_start_tvsec > 0
            and info.pbi_start_tvusec < 1_000_000
        ):
            state = "Z" if info.pbi_status == 5 else "?"
            return (
                f"darwin:{info.pbi_start_tvsec}:{info.pbi_start_tvusec}",
                state,
            )

        # Full BSD info may disappear after process exit while an unreaped PID
        # still answers `kill(0)`. The native short flavor retains `p_stat`, so
        # it can prove a zombie is dead without supplying a weak live token.
        short = _DarwinProcBsdShortInfo()
        short_result = proc_pidinfo(
            pid,
            13,  # PROC_PIDT_SHORTBSDINFO
            0,
            ctypes.byref(short),
            ctypes.sizeof(short),
        )
        if (
            short_result == ctypes.sizeof(short)
            and short.pbsi_pid == pid
            and short.pbsi_status == 5
        ):
            return f"darwin:zombie:{pid}", "Z"
        if BindingEffectLeaseManager._darwin_process_is_zombie(pid):
            return f"darwin:zombie:{pid}", "Z"
        raise BindingEffectLeaseError("a trustworthy process-incarnation token is unavailable")

    @staticmethod
    def _darwin_process_is_zombie(pid: int) -> bool:
        """Use ``ps`` only as terminal-state proof, never as an identity token."""

        try:
            result = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(pid)],
                check=True,
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.stdout.strip().startswith("Z")

    @staticmethod
    def _empty_state(vault_binding_id: str) -> _LeaseState:
        return {
            "schema": LEASE_SCHEMA,
            "vaultBindingId": vault_binding_id,
            "generation": 0,
            "nextTicket": 1,
            "sharedHolders": [],
            "exclusivePending": [],
            "exclusiveHolder": None,
        }

    def _validate_state(self, vault_binding_id: str, value: object) -> _LeaseState:
        if not isinstance(value, dict):
            raise BindingEffectLeaseError("binding effect lease state is not a mapping")
        expected = set(self._empty_state(vault_binding_id))
        if set(value) != expected or value.get("schema") != LEASE_SCHEMA:
            raise BindingEffectLeaseError("binding effect lease state has an invalid shape")
        if value.get("vaultBindingId") != vault_binding_id:
            raise BindingEffectLeaseError("binding effect lease state binding mismatch")
        generation = value.get("generation")
        next_ticket = value.get("nextTicket")
        shared = value.get("sharedHolders")
        pending = value.get("exclusivePending")
        exclusive = value.get("exclusiveHolder")
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 0
            or not isinstance(next_ticket, int)
            or isinstance(next_ticket, bool)
            or next_ticket <= 0
            or not isinstance(shared, list)
            or not isinstance(pending, list)
            or (exclusive is not None and not isinstance(exclusive, dict))
        ):
            raise BindingEffectLeaseError("binding effect lease state values are invalid")
        holders = shared + pending + ([] if exclusive is None else [exclusive])
        seen_ids: set[str] = set()
        seen_tickets: set[int] = set()
        for holder in holders:
            if not isinstance(holder, dict) or set(holder) != {
                "holderId",
                "pid",
                "processStart",
                "ticket",
                "mode",
            }:
                raise BindingEffectLeaseError("binding effect lease holder is invalid")
            holder_id = holder.get("holderId")
            pid = holder.get("pid")
            process_start = holder.get("processStart")
            ticket = holder.get("ticket")
            if (
                not isinstance(holder_id, str)
                or not holder_id
                or not isinstance(pid, int)
                or isinstance(pid, bool)
                or pid <= 0
                or not isinstance(process_start, str)
                or not process_start
                or not isinstance(ticket, int)
                or isinstance(ticket, bool)
                or ticket <= 0
                or ticket >= next_ticket
                or holder_id in seen_ids
                or ticket in seen_tickets
            ):
                raise BindingEffectLeaseError("binding effect lease holder is invalid")
            seen_ids.add(holder_id)
            seen_tickets.add(ticket)
        if any(item.get("mode") != "shared" for item in shared):
            raise BindingEffectLeaseError("binding effect shared holder mode is invalid")
        if any(item.get("mode") != "pending" for item in pending):
            raise BindingEffectLeaseError("binding effect pending holder mode is invalid")
        if exclusive is not None and exclusive.get("mode") != "exclusive":
            raise BindingEffectLeaseError("binding effect exclusive holder mode is invalid")
        if exclusive is not None and shared:
            raise BindingEffectLeaseError("binding effect lease state overlaps holders")
        return cast(_LeaseState, copy.deepcopy(value))

    def _ensure_state_root(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_root, 0o700)
        metadata = self.state_root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o700
        ):
            raise BindingEffectLeaseError("binding effect lease directory is unsafe")

    @staticmethod
    def _open_private_lease_lock(path: Path) -> int:
        descriptor: int | None = None
        try:
            descriptor = _open_lease_descriptor(
                path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            )
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise BindingEffectLeaseError(f"binding effect lease lock is unsafe: {path.name}")
            return descriptor
        except BaseException:
            if descriptor is not None:
                _close_lease_descriptor(descriptor)
            raise

    @staticmethod
    def _read_private_text(path: Path) -> str:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise BindingEffectLeaseError(
                f"binding effect lease file cannot be opened safely: {path.name}"
            )
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    path,
                    os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0),
                )
            except OSError as exc:
                raise BindingEffectLeaseError(
                    f"binding effect lease file is unsafe: {path.name}"
                ) from exc
            os.set_inheritable(descriptor, False)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o777 != 0o600
            ):
                raise BindingEffectLeaseError(f"binding effect lease file is unsafe: {path.name}")
            with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
                return handle.read()
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _binding_stem(self, vault_binding_id: str) -> str:
        return hashlib.sha256(vault_binding_id.encode("utf-8")).hexdigest()

    def _state_path(self, vault_binding_id: str) -> Path:
        return self.state_root / f"{self._binding_stem(vault_binding_id)}.json"

    def _journal_path(self, vault_binding_id: str) -> Path:
        return self.state_root / f"{self._binding_stem(vault_binding_id)}.journal.json"

    def _lock_path(self, vault_binding_id: str) -> Path:
        return self.state_root / f"{self._binding_stem(vault_binding_id)}.state.lock"

    def _gate_path(self, vault_binding_id: str) -> Path:
        return self.state_root / f"{self._binding_stem(vault_binding_id)}.effect.lock"

    def _pending_activity_path(self, vault_binding_id: str, holder_id: str) -> Path:
        binding_stem = self._binding_stem(vault_binding_id)
        holder_stem = hashlib.sha256(holder_id.encode("utf-8")).hexdigest()
        return self.state_root / f"{binding_stem}.{holder_stem}.pending.lock"

    def _atomic_private_json(self, path: Path, value: Mapping[str, object]) -> None:
        payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            Path(temporary).unlink(missing_ok=True)
            raise

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = [
    "BindingEffectLeaseError",
    "BindingEffectLeaseManager",
    "BindingEffectLeaseObservation",
    "BindingEffectLeaseTimeout",
    "LEASE_SCHEMA",
]
