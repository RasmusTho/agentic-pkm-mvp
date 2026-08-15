from __future__ import annotations

import multiprocessing
import errno
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.instance.binding_effect_lease as lease_module
from app.instance.binding_effect_lease import BindingEffectLeaseError
from app.instance.vault_registry import RegistryError
from tests.instance.test_binding_effect_lease import _build_manager, _manager_for_existing


def _crash_inside_shared(root: str, acquired) -> None:
    manager = _manager_for_existing(root)
    vault = Path(root) / "vaults" / "binding-a"
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=5):
        acquired.set()
        os._exit(17)


def _crash_inside_exclusive(root: str, acquired) -> None:
    manager = _manager_for_existing(root)
    vault = Path(root) / "vaults" / "binding-a"
    with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=5):
        acquired.set()
        os._exit(19)


def _fork_child_then_crash_effect_holder(root: str, mode: str, acquired, release_child) -> None:
    manager = _manager_for_existing(root)
    vault = Path(root) / "vaults" / "binding-a"
    effect = manager.shared_effect if mode == "shared" else manager.exclusive_change
    with effect("binding-a", channel_id="dev", root=vault, timeout=5):
        pid = os.fork()
        if pid == 0:
            release_child.wait(5)
            os._exit(0)
        acquired.set()
        os._exit(23)


def _persist_abandoned_pending(manager, *holder_ids: str) -> list[Path]:
    descriptors: list[int] = []
    paths: list[Path] = []
    try:
        with manager._state_locked("binding-a"):
            current = manager._load_reconciled_locked("binding-a")
            updated = dict(current)
            updated["exclusivePending"] = list(current["exclusivePending"])
            next_ticket = int(current["nextTicket"])
            for holder_id in holder_ids:
                descriptor = manager._open_pending_activity("binding-a", holder_id, create=True)
                descriptors.append(descriptor)
                lease_module.fcntl.flock(descriptor, lease_module.fcntl.LOCK_EX)
                updated["exclusivePending"].append(
                    manager._holder(holder_id, ticket=next_ticket, mode="pending")
                )
                paths.append(manager._pending_activity_path("binding-a", holder_id))
                next_ticket += 1
            updated["nextTicket"] = next_ticket
            manager._commit_locked("binding-a", current, updated)
    finally:
        for descriptor in descriptors:
            manager._close_pending_activity(descriptor)
    return paths


def test_crashed_holder_recovers_without_deadlock_or_false_completion(tmp_path) -> None:
    _build_manager(tmp_path, "binding-a")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    process = context.Process(target=_crash_inside_shared, args=(str(tmp_path), acquired))
    process.start()
    assert acquired.wait(3)
    process.join(5)
    assert process.exitcode == 17

    manager = _manager_for_existing(str(tmp_path))
    vault = tmp_path / "vaults" / "binding-a"
    with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=2):
        observation = manager.observe("binding-a")
        assert observation.shared_count == 0
        assert observation.exclusive_held

    persisted = manager.persisted_state("binding-a")
    assert "completed" not in persisted
    assert "completion" not in persisted


def test_crashed_exclusive_holder_recovers_for_a_later_shared_effect(tmp_path) -> None:
    _build_manager(tmp_path, "binding-a")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    process = context.Process(target=_crash_inside_exclusive, args=(str(tmp_path), acquired))
    process.start()
    assert acquired.wait(3)
    process.join(5)
    assert process.exitcode == 19

    manager = _manager_for_existing(str(tmp_path))
    vault = tmp_path / "vaults" / "binding-a"
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=2):
        assert manager.observe("binding-a").shared_count == 1


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork inheritance proof")
@pytest.mark.parametrize(
    ("holder_mode", "later_mode"),
    [("shared", "exclusive"), ("exclusive", "shared")],
)
def test_fork_child_cannot_extend_a_crashed_effect_holder(
    tmp_path, holder_mode, later_mode
) -> None:
    _build_manager(tmp_path, "binding-a")
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release_child = context.Event()
    process = context.Process(
        target=_fork_child_then_crash_effect_holder,
        args=(str(tmp_path), holder_mode, acquired, release_child),
    )
    process.start()
    assert acquired.wait(3)
    process.join(5)
    assert process.exitcode == 23

    manager = _manager_for_existing(str(tmp_path))
    vault = tmp_path / "vaults" / "binding-a"
    effect = manager.shared_effect if later_mode == "shared" else manager.exclusive_change
    try:
        with effect("binding-a", channel_id="dev", root=vault, timeout=1):
            observation = manager.observe("binding-a")
            assert observation.shared_count == (1 if later_mode == "shared" else 0)
            assert observation.exclusive_held is (later_mode == "exclusive")
    finally:
        release_child.set()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork ownership proof")
def test_fork_child_cannot_release_the_parent_effect(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    held = manager._acquire(
        "binding-a",
        mode="shared",
        channel_id="dev",
        root=vault,
        timeout=1,
    )
    pid = os.fork()
    if pid == 0:
        try:
            manager._release(held)
        except BindingEffectLeaseError:
            os._exit(0)
        os._exit(2)

    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert manager.observe("binding-a").shared_count == 1
    manager._release(held)


def test_state_lock_cancellation_closes_the_acquired_descriptor(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    baseline = set(lease_module._LEASE_LOCK_FDS)
    real_flock = lease_module.fcntl.flock
    interrupted = False

    def acquire_then_interrupt(descriptor, operation):
        nonlocal interrupted
        result = real_flock(descriptor, operation)
        if not interrupted and operation == lease_module.fcntl.LOCK_EX:
            interrupted = True
            raise KeyboardInterrupt("cancel after state lock acquisition")
        return result

    monkeypatch.setattr(lease_module.fcntl, "flock", acquire_then_interrupt)
    with pytest.raises(KeyboardInterrupt, match="state lock acquisition"):
        manager.observe("binding-a")
    monkeypatch.setattr(lease_module.fcntl, "flock", real_flock)

    assert set(lease_module._LEASE_LOCK_FDS) == baseline
    probe = os.open(manager._lock_path("binding-a"), os.O_RDWR)
    try:
        real_flock(
            probe,
            lease_module.fcntl.LOCK_EX | lease_module.fcntl.LOCK_NB,
        )
    finally:
        os.close(probe)


def test_holder_identity_failure_closes_the_effect_descriptor(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    baseline = set(lease_module._LEASE_LOCK_FDS)

    def fail_holder_identity():
        raise KeyboardInterrupt("holder identity unavailable")

    monkeypatch.setattr(lease_module, "uuid4", fail_holder_identity)
    with pytest.raises(KeyboardInterrupt, match="holder identity unavailable"):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
            pytest.fail("holder identity failure cannot expose an effect")

    assert set(lease_module._LEASE_LOCK_FDS) == baseline
    probe = os.open(manager._gate_path("binding-a"), os.O_RDWR)
    try:
        lease_module.fcntl.flock(
            probe,
            lease_module.fcntl.LOCK_EX | lease_module.fcntl.LOCK_NB,
        )
    finally:
        os.close(probe)


def test_reconciliation_cancellation_closes_transferred_pending_descriptor(
    tmp_path, monkeypatch
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    [sentinel] = _persist_abandoned_pending(manager, "holder-abandoned")
    baseline = set(lease_module._LEASE_LOCK_FDS)
    real_flock = lease_module.fcntl.flock
    nonblocking_exclusive_calls = 0

    def cancel_at_gate_probe(descriptor, operation):
        nonlocal nonblocking_exclusive_calls
        result = real_flock(descriptor, operation)
        if operation == lease_module.fcntl.LOCK_EX | lease_module.fcntl.LOCK_NB:
            nonblocking_exclusive_calls += 1
            if nonblocking_exclusive_calls == 2:
                raise KeyboardInterrupt("cancel after pending descriptor transfer")
        return result

    monkeypatch.setattr(lease_module.fcntl, "flock", cancel_at_gate_probe)
    with pytest.raises(KeyboardInterrupt, match="pending descriptor transfer"):
        manager.observe("binding-a")
    monkeypatch.setattr(lease_module.fcntl, "flock", real_flock)

    assert set(lease_module._LEASE_LOCK_FDS) == baseline
    probe = os.open(sentinel, os.O_RDWR)
    try:
        real_flock(
            probe,
            lease_module.fcntl.LOCK_EX | lease_module.fcntl.LOCK_NB,
        )
    finally:
        os.close(probe)
    assert manager.observe("binding-a").exclusive_pending_count == 0


def test_later_pending_probe_failure_closes_an_earlier_transfer(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    first, _ = _persist_abandoned_pending(
        manager,
        "holder-abandoned-first",
        "holder-abandoned-second",
    )
    baseline = set(lease_module._LEASE_LOCK_FDS)
    real_status = manager._pending_waiter_status
    calls = 0

    def fail_second_probe(vault_binding_id, holder):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("later pending probe failed")
        return real_status(vault_binding_id, holder)

    monkeypatch.setattr(manager, "_pending_waiter_status", fail_second_probe)
    with pytest.raises(KeyboardInterrupt, match="later pending probe"):
        manager.observe("binding-a")
    monkeypatch.setattr(manager, "_pending_waiter_status", real_status)

    assert set(lease_module._LEASE_LOCK_FDS) == baseline
    probe = os.open(first, os.O_RDWR)
    try:
        lease_module.fcntl.flock(
            probe,
            lease_module.fcntl.LOCK_EX | lease_module.fcntl.LOCK_NB,
        )
    finally:
        os.close(probe)
    assert manager.observe("binding-a").exclusive_pending_count == 0


@pytest.mark.parametrize("crash_point", ["journal", "state"])
def test_pre_registry_commit_crash_rolls_back_from_the_separate_journal(
    tmp_path, monkeypatch, crash_point
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    state_path = manager._state_path("binding-a")
    journal_path = manager._journal_path("binding-a")
    real_write = manager._atomic_private_json

    def interrupt_during_outer_commit(path, value) -> None:
        real_write(path, value)
        if path == journal_path and crash_point == "journal":
            raise KeyboardInterrupt("crash after lease journal prepare")
        if path == state_path and crash_point == "state" and value.get("generation") == 1:
            raise KeyboardInterrupt("crash after lease state write")

    monkeypatch.setattr(manager, "_atomic_private_json", interrupt_during_outer_commit)
    with pytest.raises(KeyboardInterrupt, match="crash after lease"):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
            pytest.fail("the interrupted acquisition cannot expose an effect window")
    assert journal_path.exists()

    recovered = _manager_for_existing(str(tmp_path))
    observation = recovered.observe("binding-a")
    assert observation.shared_count == 0
    assert not observation.exclusive_held
    assert not journal_path.exists()


def test_registry_post_commit_error_converges_to_committed_journal_endpoint(
    tmp_path, monkeypatch
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_verify = manager.registry_store._verify_generation
    calls = 0

    def fail_first_post_commit_verification(generation) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RegistryError("post-commit verification failed")
        real_verify(generation)

    monkeypatch.setattr(
        manager.registry_store,
        "_verify_generation",
        fail_first_post_commit_verification,
    )
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        assert manager.observe("binding-a").shared_count == 1

    assert not manager._journal_path("binding-a").exists()
    assert (
        manager.persisted_state("binding-a")
        == manager.registry_store.load().extensions["bindingEffectLeases"]["binding-a"]
    )


def test_journal_less_registry_state_divergence_fails_closed(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        pass
    state = manager.persisted_state("binding-a")
    manager._atomic_private_json(
        manager._state_path("binding-a"),
        {**state, "generation": int(state["generation"]) + 1},
    )

    with pytest.raises(BindingEffectLeaseError, match="diverges from registry"):
        manager.observe("binding-a")


def test_unreadable_registry_retains_outer_journal_until_recovery(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_registry_state = manager._registry_state
    producer_failed = False

    def fail_before_registry_commit(*args, **kwargs) -> None:
        nonlocal producer_failed
        producer_failed = True
        raise RegistryError("registry unavailable")

    def unreadable_after_failure(binding_id):
        if producer_failed:
            raise RegistryError("registry still unavailable")
        return real_registry_state(binding_id)

    monkeypatch.setattr(
        manager.registry_store,
        "set_binding_effect_lease_state",
        fail_before_registry_commit,
    )
    monkeypatch.setattr(manager, "_registry_state", unreadable_after_failure)
    with pytest.raises(RegistryError, match="still unavailable"):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
            pytest.fail("an indeterminate commit cannot expose an effect window")
    assert manager._journal_path("binding-a").exists()

    recovered = _manager_for_existing(str(tmp_path))
    assert recovered.observe("binding-a").shared_count == 0
    assert not recovered._journal_path("binding-a").exists()


def test_third_registry_endpoint_retains_journal_and_fails_closed(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_producer = manager.registry_store.set_binding_effect_lease_state

    def commit_third_endpoint(binding_id, state, **kwargs) -> None:
        third = {**state, "generation": int(state["generation"]) + 1}
        real_producer(binding_id, third, **kwargs)
        raise RegistryError("ambiguous registry outcome")

    monkeypatch.setattr(
        manager.registry_store,
        "set_binding_effect_lease_state",
        commit_third_endpoint,
    )
    with pytest.raises(BindingEffectLeaseError, match="both journal endpoints"):
        with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
            pytest.fail("a third endpoint cannot expose an effect window")
    assert manager._journal_path("binding-a").exists()

    recovered = _manager_for_existing(str(tmp_path))
    with pytest.raises(BindingEffectLeaseError, match="diverges from registry"):
        recovered.observe("binding-a")
    assert recovered._journal_path("binding-a").exists()


def test_failed_pending_discard_does_not_leave_a_live_process_at_fifo_head(
    tmp_path, monkeypatch
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_producer = manager.registry_store.set_binding_effect_lease_state
    discard_failed = False

    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):

        def fail_pending_discard(binding_id, state, **kwargs) -> None:
            nonlocal discard_failed
            current = manager.registry_store.load().extensions["bindingEffectLeases"][binding_id]
            if not discard_failed and current["exclusivePending"] and not state["exclusivePending"]:
                discard_failed = True
                raise RegistryError("pending discard unavailable")
            real_producer(binding_id, state, **kwargs)

        monkeypatch.setattr(
            manager.registry_store,
            "set_binding_effect_lease_state",
            fail_pending_discard,
        )
        with pytest.raises(RegistryError, match="pending discard unavailable"):
            with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=0.02):
                pytest.fail("exclusive acquisition cannot overlap a shared holder")

    monkeypatch.setattr(
        manager.registry_store,
        "set_binding_effect_lease_state",
        real_producer,
    )
    with manager.shared_effect("binding-a", channel_id="dev", root=vault, timeout=1):
        assert manager.observe("binding-a").exclusive_pending_count == 0


def test_pending_activity_requires_a_held_lock_from_the_live_waiter(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    manager._ensure_state_root()
    holder = manager._holder("holder-active", ticket=1, mode="pending")
    descriptor = manager._open_pending_activity("binding-a", holder["holderId"], create=True)
    lease_module.fcntl.flock(descriptor, lease_module.fcntl.LOCK_EX)
    try:
        assert manager._pending_waiter_status("binding-a", holder) == (True, None)
    finally:
        manager._close_pending_activity(descriptor)

    active, stale_descriptor = manager._pending_waiter_status("binding-a", holder)
    assert not active
    assert stale_descriptor is not None
    manager._close_pending_activity(stale_descriptor)
    manager._pending_activity_path("binding-a", holder["holderId"]).unlink()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork inheritance proof")
def test_forked_child_neither_unlocks_nor_extends_pending_activity(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    manager._ensure_state_root()
    path = manager._pending_activity_path("binding-a", "holder-fork")
    descriptor = manager._open_pending_activity("binding-a", "holder-fork", create=True)
    lease_module.fcntl.flock(descriptor, lease_module.fcntl.LOCK_EX)
    child_read, parent_write = os.pipe()
    parent_read, child_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(parent_write)
        os.close(parent_read)
        probe = os.open(path, os.O_RDWR)
        try:
            try:
                lease_module.fcntl.flock(
                    probe,
                    lease_module.fcntl.LOCK_EX | lease_module.fcntl.LOCK_NB,
                )
            except BlockingIOError:
                os.write(child_write, b"B")
            else:
                os._exit(2)
            os.read(child_read, 1)
            lease_module.fcntl.flock(
                probe,
                lease_module.fcntl.LOCK_EX | lease_module.fcntl.LOCK_NB,
            )
            os.write(child_write, b"A")
            os._exit(0)
        except BaseException:
            os._exit(3)

    os.close(child_read)
    os.close(child_write)
    try:
        assert os.read(parent_read, 1) == b"B"
        manager._close_pending_activity(descriptor)
        os.write(parent_write, b"R")
        assert os.read(parent_read, 1) == b"A"
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0
    finally:
        os.close(parent_write)
        os.close(parent_read)
        path.unlink(missing_ok=True)


@pytest.mark.parametrize("crash_point", ["before-pending", "after-exclusive"])
def test_pending_activity_crash_windows_converge_without_file_leaks(
    tmp_path, monkeypatch, crash_point
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    vault = tmp_path / "vaults" / "binding-a"
    real_commit = manager._commit_locked

    def crash(vault_binding_id, previous, candidate):
        pending = candidate["exclusivePending"]
        exclusive = candidate["exclusiveHolder"]
        if crash_point == "before-pending" and pending and not previous["exclusivePending"]:
            raise KeyboardInterrupt("crash before pending commit")
        committed = real_commit(vault_binding_id, previous, candidate)
        if crash_point == "after-exclusive" and exclusive is not None:
            raise KeyboardInterrupt("crash after exclusive commit")
        return committed

    monkeypatch.setattr(manager, "_commit_locked", crash)
    with pytest.raises(KeyboardInterrupt, match="crash"):
        with manager.exclusive_change("binding-a", channel_id="dev", root=vault, timeout=1):
            if crash_point == "before-pending":
                pytest.fail("pending commit was expected to crash")

    monkeypatch.setattr(manager, "_commit_locked", real_commit)
    observation = manager.observe("binding-a")
    assert observation.exclusive_pending_count == 0
    assert not observation.exclusive_held
    assert list(manager.state_root.glob("*.pending.lock")) == []


def test_pending_activity_probe_error_fails_closed(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    manager._ensure_state_root()
    holder = manager._holder("holder-probe", ticket=1, mode="pending")
    descriptor = manager._open_pending_activity("binding-a", holder["holderId"], create=True)
    lease_module.fcntl.flock(descriptor, lease_module.fcntl.LOCK_EX)
    real_flock = lease_module.fcntl.flock

    def unsupported(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "flock unsupported")

    monkeypatch.setattr(lease_module.fcntl, "flock", unsupported)
    with pytest.raises(OSError, match="flock unsupported"):
        manager._pending_waiter_status("binding-a", holder)
    monkeypatch.setattr(lease_module.fcntl, "flock", real_flock)
    manager._close_pending_activity(descriptor)


def test_pending_activity_unlink_rejects_path_replacement(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    manager._ensure_state_root()
    holder_id = "holder-replaced"
    path = manager._pending_activity_path("binding-a", holder_id)
    descriptor = manager._open_pending_activity("binding-a", holder_id, create=True)
    lease_module.fcntl.flock(descriptor, lease_module.fcntl.LOCK_EX)
    displaced = path.with_suffix(".displaced")
    path.rename(displaced)
    path.touch(mode=0o600)
    try:
        with pytest.raises(BindingEffectLeaseError, match="path identity changed"):
            manager._unlink_pending_activity_locked("binding-a", holder_id, descriptor)
        assert path.exists()
    finally:
        manager._close_pending_activity(descriptor)
        path.unlink(missing_ok=True)
        displaced.unlink(missing_ok=True)


class _FakeProcPidInfo:
    def __init__(self, *, status: int, second: int, microsecond: int, result: int | None = None):
        self.status = status
        self.second = second
        self.microsecond = microsecond
        self.result = result
        self.argtypes = None
        self.restype = None

    def __call__(self, pid, flavor, arg, buffer, size):
        assert arg == 0
        if flavor == 3:
            info = lease_module.ctypes.cast(
                buffer,
                lease_module.ctypes.POINTER(lease_module._DarwinProcBsdInfo),
            ).contents
            info.pbi_pid = pid
            info.pbi_status = self.status
            info.pbi_start_tvsec = self.second
            info.pbi_start_tvusec = self.microsecond
            return size if self.result is None else self.result
        assert flavor == 13
        short = lease_module.ctypes.cast(
            buffer,
            lease_module.ctypes.POINTER(lease_module._DarwinProcBsdShortInfo),
        ).contents
        short.pbsi_pid = pid
        short.pbsi_status = self.status
        return size


class _FakeLibproc:
    def __init__(self, proc_pidinfo) -> None:
        self.proc_pidinfo = proc_pidinfo


def test_process_identity_refuses_pid_reuse(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    start, _ = manager._process_identity(os.getpid())
    stale = {
        "holderId": "stale",
        "pid": os.getpid(),
        "processStart": f"{start}-previous-incarnation",
        "ticket": 1,
        "mode": "pending",
    }
    assert not manager._holder_alive(stale)

    native = _FakeProcPidInfo(status=2, second=100, microsecond=222)
    monkeypatch.setattr(
        lease_module.ctypes,
        "CDLL",
        lambda *args, **kwargs: _FakeLibproc(native),
    )
    token, state = manager._darwin_process_identity(os.getpid())
    assert token == "darwin:100:222"
    assert state == "?"

    same_second_stale = {**stale, "processStart": "darwin:100:221"}
    monkeypatch.setattr(manager, "_process_identity", lambda pid: (token, state))
    assert not manager._holder_alive(same_second_stale)


def test_darwin_zombie_is_stale_even_with_matching_native_identity(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    native = _FakeProcPidInfo(status=5, second=100, microsecond=222)
    monkeypatch.setattr(
        lease_module.ctypes,
        "CDLL",
        lambda *args, **kwargs: _FakeLibproc(native),
    )
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(lease_module.sys, "platform", "darwin")

    holder = {
        "holderId": "zombie",
        "pid": os.getpid(),
        "processStart": "darwin:100:222",
        "ticket": 1,
        "mode": "pending",
    }
    assert not manager._holder_alive(holder)


def test_darwin_ps_is_terminal_zombie_proof_not_a_live_identity(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    unavailable_full_info = _FakeProcPidInfo(
        status=2,
        second=100,
        microsecond=222,
        result=0,
    )
    monkeypatch.setattr(
        lease_module.ctypes,
        "CDLL",
        lambda *args, **kwargs: _FakeLibproc(unavailable_full_info),
    )
    monkeypatch.setattr(
        lease_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Z+\n"),
    )
    assert manager._darwin_process_identity(os.getpid()) == (
        f"darwin:zombie:{os.getpid()}",
        "Z",
    )

    monkeypatch.setattr(
        lease_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="S+\n"),
    )
    with pytest.raises(BindingEffectLeaseError, match="trustworthy process-incarnation"):
        manager._darwin_process_identity(os.getpid())


@pytest.mark.parametrize(
    ("status", "second", "microsecond", "result"),
    [
        (2, 100, 222, 0),
        (6, 100, 222, None),
        (2, 0, 222, None),
        (2, 100, 1_000_000, None),
    ],
)
def test_darwin_identity_rejects_short_or_malformed_native_results(
    tmp_path, monkeypatch, status, second, microsecond, result
) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    native = _FakeProcPidInfo(
        status=status,
        second=second,
        microsecond=microsecond,
        result=result,
    )
    monkeypatch.setattr(
        lease_module.ctypes,
        "CDLL",
        lambda *args, **kwargs: _FakeLibproc(native),
    )
    with pytest.raises(BindingEffectLeaseError, match="trustworthy process-incarnation"):
        manager._darwin_process_identity(os.getpid())


def test_process_identity_refuses_unavailable_native_fallback(tmp_path, monkeypatch) -> None:
    manager = _build_manager(tmp_path, "binding-a")

    def no_procfs(*args, **kwargs):
        raise OSError("procfs unavailable")

    def no_libproc(*args, **kwargs):
        raise OSError("libproc unavailable")

    monkeypatch.setattr(Path, "read_text", no_procfs)
    monkeypatch.setattr(lease_module.sys, "platform", "darwin")
    monkeypatch.setattr(lease_module.ctypes, "CDLL", no_libproc)
    with pytest.raises(BindingEffectLeaseError, match="trustworthy process-incarnation"):
        manager._process_identity(os.getpid())


@pytest.mark.skipif(lease_module.sys.platform != "darwin", reason="Darwin-only libproc proof")
def test_live_darwin_process_identity_uses_native_microseconds(tmp_path) -> None:
    manager = _build_manager(tmp_path, "binding-a")
    token, state = manager._darwin_process_identity(os.getpid())

    assert lease_module.ctypes.sizeof(lease_module._DarwinProcBsdInfo) == 136
    prefix, second, microsecond = token.split(":")
    assert prefix == "darwin"
    assert int(second) > 0
    assert 0 <= int(microsecond) < 1_000_000
    assert state != "Z"
