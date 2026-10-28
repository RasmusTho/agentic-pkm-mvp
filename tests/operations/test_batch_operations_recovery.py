"""Real-owner regressions for final publication and recovery-attempt truth."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import os
from threading import Event
import time

import pytest

from app.knowledge import adapters
from app.operations import JsonReceiptStore, PolicyDecision, execution_kernel
from app.operations.batch_operations import BatchOperationCoordinator
from app.operations.contracts import SourceEffectStatus
from app.operations.placement_operations import reconcile_placement_operation
from tests.operations import test_placement_operations, test_semantic_operations, test_write_operations
from tests.operations._batch_harness import (
    Interrupted, coordinator, delegation_for, execute, native_receipt, preview, requests_for, source_tags,
)

write_bound = test_write_operations.bound
semantic_bound = test_semantic_operations.bound
placement_bound = test_placement_operations.bound


@pytest.mark.parametrize("wait_site", ["candidate_fsync", "collision", "after_publication"])
@pytest.mark.parametrize("expired", [False, True])
def test_conflict_publication_checks_the_actual_link_and_retains_public_evidence(
    write_bound, tmp_path, monkeypatch, wait_site, expired,
):
    request = test_write_operations._request(write_bound, "artifact.update", arguments={"body": "Bounded proposal.\n"})
    kernel = test_write_operations._kernel(write_bound)
    kernel.receipt_store = JsonReceiptStore(tmp_path / "kernel.json")
    batch = BatchOperationCoordinator(kernel)
    expiry = time.time() + 2
    delegation = {**delegation_for([request]), "expires_at": expiry}
    assert kernel._precondition_refusal(request, delegation) is None
    frozen = batch.preview(batch_id="final-conflict", requests=[request], selector={}, delegation=delegation)
    human = write_bound.note_path.read_bytes() + b"Concurrent human bytes.\n"
    initial_files = set(write_bound.vault_root.rglob("*.md"))
    read, opened, fsync, link = adapters._read_handle, os.open, os.fsync, os.link
    state = {"read": False, "candidate": None, "waited": False, "collision": False}
    publications, winners = [], []

    def wait(site):
        if site == wait_site and not state["waited"]:
            assert time.time() < expiry
            state["waited"] = True
            time.sleep(max(0, expiry - time.time()) + 0.04 if expired else 0.01)

    def human_race(handle):
        if not state["read"]:
            state["read"] = True
            write_bound.note_path.write_bytes(human)
        return read(handle)

    def observe_open(path, *args, **kwargs):
        fd = opened(path, *args, **kwargs)
        if str(path).endswith(".conflict-stage"):
            state["candidate"] = fd
        return fd

    def observe_fsync(fd):
        result = fsync(fd)
        if fd == state["candidate"]:
            wait("candidate_fsync")
        return result

    def observe_link(source, destination, *args, **kwargs):
        if not str(source).endswith(".conflict-stage"):
            return link(source, destination, *args, **kwargs)
        if wait_site == "collision" and not state["collision"]:
            state["collision"] = True
            fd = opened(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
                        dir_fd=kwargs["dst_dir_fd"])
            try:
                os.write(fd, b"Human destination winner.\n")
                fsync(fd)
            finally:
                os.close(fd)
            winners.append(write_bound.note_path.parent / destination)
            try:
                return link(source, destination, *args, **kwargs)
            except FileExistsError:
                wait("collision")
                raise
        result = link(source, destination, *args, **kwargs)
        publications.append((write_bound.note_path.parent / destination, time.time()))
        wait("after_publication")
        return result

    monkeypatch.setattr(adapters, "_read_handle", human_race)
    monkeypatch.setattr(adapters.os, "open", observe_open)
    monkeypatch.setattr(adapters.os, "fsync", observe_fsync)
    monkeypatch.setattr(adapters.os, "link", observe_link)
    result = execute(batch, frozen)
    assert state["read"] and state["waited"]
    assert write_bound.note_path.read_bytes() == human
    assert all(path.read_bytes() == b"Human destination winner.\n" for path in winners)
    added = set(write_bound.vault_root.rglob("*.md")) - initial_files - set(winners)
    if expired and wait_site != "after_publication":
        assert publications == [] and added == set()
        assert result.counts["completed"] == result.counts["conflicted"] == 0
    else:
        assert len(publications) == 1 and publications[0][1] < expiry
        assert added == {publications[0][0]}
        assert result.counts["conflicted"] == 1
        receipt = native_receipt(result.items[0])
        assert receipt["source_receipt"]["outcome"] == "conflict_staged"
        assert receipt["authority_receipt"]["outcome"] == "failed"
        assert publications[0][0].exists()


@pytest.mark.parametrize("revoke", [False, True])
def test_conflict_helper_rechecks_the_semantic_owned_guard_after_candidate_io(
    semantic_bound, monkeypatch, revoke,
):
    requests, paths = requests_for(semantic_bound, 1)
    request = requests[0]
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    human = paths[0].read_bytes() + b"Concurrent human body.\n"
    original_files = set(semantic_bound.owner.root.rglob("*.md"))
    read, opened, fsync = adapters._read_handle, os.open, os.fsync
    state = {"read": False, "candidate": None, "observed": False}

    def human_race(handle):
        if not state["read"]:
            state["read"] = True
            paths[0].write_bytes(human)
        return read(handle)

    def observe_open(path, *args, **kwargs):
        fd = opened(path, *args, **kwargs)
        if str(path).endswith(".conflict-stage"):
            state["candidate"] = fd
        return fd

    def candidate_io(fd):
        result = fsync(fd)
        if fd == state["candidate"] and not state["observed"]:
            state["observed"] = True
            if revoke:
                semantic_bound.revoke_approval(request.request_id)
        return result

    monkeypatch.setattr(adapters, "_read_handle", human_race)
    monkeypatch.setattr(adapters.os, "open", observe_open)
    monkeypatch.setattr(adapters.os, "fsync", candidate_io)
    result = execute(batch, frozen)
    assert state["observed"] and paths[0].read_bytes() == human
    added = set(semantic_bound.owner.root.rglob("*.md")) - original_files
    if revoke:
        assert added == set() and result.counts["refused"] == 1
        assert not semantic_bound.owner.receipt_path.exists()
    else:
        assert added and result.counts["conflicted"] == 1
        assert native_receipt(result.items[0])["authority_receipt"]["outcome"] == "failed"


@pytest.mark.parametrize("refusal", ["none", "expiry", "policy"])
def test_lost_kernel_finalize_cannot_erase_committed_batch_evidence(semantic_bound, monkeypatch, refusal):
    requests, paths = requests_for(semantic_bound, 1)
    request = requests[0]
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    finalize = batch.store.finalize

    def lose_result(request_id, *args):
        if request_id == request.request_id:
            raise OSError("kernel finalization lost after native source/GOV durability")
        return finalize(request_id, *args)

    with monkeypatch.context() as patch:
        patch.setattr(batch.store, "finalize", lose_result)
        first = execute(batch, frozen)
    assert first.items[0].outcome.convergence.source_effect is SourceEffectStatus.COMMITTED
    native = native_receipt(first.items[0])
    assert native["authority_receipt"]["receipt_id"] == semantic_bound.records()[0]["receipt_id"]
    restarted = coordinator(semantic_bound, restart=True)
    assert native_receipt(restarted.inspect(frozen.batch_id, expected_digest=frozen.digest).items[0]) == native
    assert restarted.store.lookup(request.request_id).outcome.convergence is None
    if refusal == "expiry":
        monkeypatch.setattr(execution_kernel, "time", lambda: 4102444801)
    elif refusal == "policy":
        restarted.kernel.policy_evaluator = lambda *_: PolicyDecision.denied("policy-1", "current recovery refused")
    result = execute(restarted, frozen)
    assert result.items[0].outcome.convergence.source_effect is SourceEffectStatus.COMMITTED
    assert native_receipt(result.items[0]) == native
    assert result.counts["ambiguous"] == 0
    assert result.counts["completed"] == int(refusal == "none")
    assert source_tags(paths[0]) == ["reviewed"] and len(semantic_bound.records()) == 1


def _prepared(placement_bound, monkeypatch, *, batch_id="prepared"):
    request = test_placement_operations._request(placement_bound)
    batch = BatchOperationCoordinator(test_placement_operations._kernel(placement_bound))
    frozen = preview(batch, [request], batch_id=batch_id)
    store = placement_bound.owner._store

    def fail(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "prepared":
            raise OSError("initial prepared operation interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(placement_bound.owner, "_store", fail)
        result = execute(batch, frozen)
    assert result.items[0].outcome.convergence.source_effect is SourceEffectStatus.NOT_APPLIED
    restarted = test_placement_operations._restart(placement_bound)
    resumed = BatchOperationCoordinator(test_placement_operations._kernel(restarted),
        reconcile_owner=lambda r: reconcile_placement_operation(r, restarted))
    return request, frozen, restarted, resumed


@pytest.mark.parametrize("refusal", ["expiry", "policy"])
def test_new_native_recovery_attempt_supersedes_old_not_applied_before_callback(
    placement_bound, monkeypatch, refusal,
):
    request, frozen, restarted, resumed = _prepared(placement_bound, monkeypatch)
    store = restarted.owner._store

    def crash(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "activated":
            raise Interrupted()

    with monkeypatch.context() as patch:
        patch.setattr(restarted.owner, "_store", crash)
        with pytest.raises(Interrupted):
            execute(resumed, frozen)
    assert (restarted.owner.root / "Projects/moved.md").exists()
    assert resumed.store.lookup(request.request_id).outcome.convergence.source_effect is SourceEffectStatus.UNKNOWN
    if refusal == "expiry":
        monkeypatch.setattr(execution_kernel, "time", lambda: 4102444801)
    else:
        resumed.kernel.policy_evaluator = lambda *_: PolicyDecision.denied("policy-1", "recovery revoked")
    result = execute(resumed, frozen)
    assert result.items[0].outcome.convergence.source_effect is SourceEffectStatus.UNKNOWN
    assert result.counts["ambiguous"] == 1 and result.counts["completed"] == 0
    assert test_placement_operations._record(restarted)["phase"] == "activated"


def test_failed_recovery_attempt_reservation_never_calls_the_native_owner(placement_bound, monkeypatch):
    request, frozen, restarted, resumed = _prepared(placement_bound, monkeypatch)
    calls = []
    native = resumed.reconcile_owner

    def observed(r):
        calls.append(r.request_id)
        return native(r)

    resumed.reconcile_owner = observed
    finalize = resumed.store.finalize

    def fail(request_id, *args):
        if request_id == request.request_id:
            raise OSError("attempt marker cannot become durable")
        return finalize(request_id, *args)

    with monkeypatch.context() as patch:
        patch.setattr(resumed.store, "finalize", fail)
        result = execute(resumed, frozen)
    assert calls == [] and result.counts["completed"] == 0
    assert test_placement_operations._record(restarted)["phase"] == "prepared"
    assert (restarted.owner.root / restarted.source).exists()
    assert execute(resumed, frozen).counts["completed"] == 1 and calls == [request.request_id]


def test_initial_effect_and_recovery_share_one_original_request_window(placement_bound, monkeypatch):
    request = test_placement_operations._request(placement_bound)
    initial = BatchOperationCoordinator(test_placement_operations._kernel(placement_bound))
    frozen = preview(initial, [request])
    waiting_kernel = test_placement_operations._kernel(test_placement_operations._restart(placement_bound))
    entered, release, waiting = Event(), Event(), Event()
    store = placement_bound.owner._store
    calls = []

    def blocked(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "prepared":
            entered.set()
            assert release.wait(10)

    monkeypatch.setattr(placement_bound.owner, "_store", blocked)
    window = waiting_kernel.receipt_store.effect_window

    @contextmanager
    def observed_window(request_id):
        waiting.set()
        with window(request_id):
            yield

    monkeypatch.setattr(waiting_kernel.receipt_store, "effect_window", observed_window)

    def recover(r):
        calls.append(r.request_id)
        return reconcile_placement_operation(r, placement_bound)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(execute, initial, frozen)
        assert entered.wait(5)
        path = initial.store.path.parent / f".{initial.store.path.name}.effect-{sha256(request.request_id.encode()).hexdigest()}.lock"
        with path.open("a+") as probe:
            with pytest.raises(BlockingIOError):
                fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        second = pool.submit(waiting_kernel.execute, request, delegation_for([request]),
                             reconcile=recover, bind_owner_delegation=True)
        try:
            assert waiting.wait(5) and calls == []
        finally:
            release.set()
        result = first.result(timeout=10)
        replay = second.result(timeout=10)
    assert calls == [] and replay == result.items[0].outcome
    assert result.counts["completed"] == 1


def test_two_recoveries_refresh_after_the_same_original_request_window(placement_bound, monkeypatch):
    request, frozen, restarted, first = _prepared(placement_bound, monkeypatch, batch_id="first")
    second = BatchOperationCoordinator(test_placement_operations._kernel(restarted),
        reconcile_owner=lambda r: reconcile_placement_operation(r, restarted))
    second_frozen = preview(second, [request], batch_id="second")
    assert execute(second, second_frozen).counts["recoverable"] == 1
    entered, release, waiting = Event(), Event(), Event()
    calls = []

    def blocked(r):
        calls.append(r.request_id)
        entered.set()
        assert release.wait(10)
        return reconcile_placement_operation(r, restarted)

    first.reconcile_owner = blocked
    window = second.store.effect_window

    @contextmanager
    def observed(request_id):
        waiting.set()
        with window(request_id):
            yield

    monkeypatch.setattr(second.store, "effect_window", observed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(execute, first, frozen)
        assert entered.wait(5)
        two = pool.submit(execute, second, second_frozen)
        try:
            assert waiting.wait(5)
        finally:
            release.set()
        result = one.result(timeout=10)
        repeated = two.result(timeout=10)
    assert calls == [request.request_id]
    assert result.counts["completed"] == repeated.counts["completed"] == 1
    assert result.items[0].outcome == repeated.items[0].outcome
