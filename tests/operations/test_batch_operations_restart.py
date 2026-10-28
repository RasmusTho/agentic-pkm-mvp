from concurrent.futures import ThreadPoolExecutor
import fcntl
import os
from threading import Event
import time

import pytest

from app.knowledge import adapters, semantic
from app.knowledge.contracts import NoteLocator
from app.knowledge.errors import KnowledgeCapabilityError
from app.operations import execution_kernel, JsonReceiptStore, PolicyDecision
from app.operations.batch_operations import BatchOperationCoordinator
from app.operations import placement_operations
from app.operations.contracts import SourceEffectStatus
from tests.operations import test_semantic_operations
from tests.operations import test_placement_operations, test_write_operations
from tests.operations._batch_harness import (
    Interrupted, coordinator, delegation_for, execute, native_receipt, preview, requests_for, source_tags,
)

semantic_bound = test_semantic_operations.bound
placement_bound = test_placement_operations.bound
write_bound = test_write_operations.bound


@pytest.mark.parametrize("cancel", [False, True])
def test_batch_cancel_and_restart_resume_are_idempotent(semantic_bound, monkeypatch, cancel):
    requests, paths = requests_for(semantic_bound)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    save = batch._save
    writes = []
    source_write = semantic.write_note_from_absolute

    def observe(*args, **kwargs):
        writes.append(str(args[0]))
        return source_write(*args, **kwargs)

    def crash(state):
        if state["items"][0]["state"] == "terminal":
            raise Interrupted()
        return save(state)

    monkeypatch.setattr(semantic, "write_note_from_absolute", observe)
    with monkeypatch.context() as patch:
        patch.setattr(batch, "_save", crash)
        with pytest.raises(Interrupted):
            execute(batch, frozen)
    restarted = coordinator(semantic_bound, restart=True)
    if cancel:
        cancelled = restarted.cancel(frozen.batch_id, expected_digest=frozen.digest)
        assert cancelled.cancel_requested and cancelled.counts["cancelled"] == 2
    result = execute(restarted, frozen)
    assert result.counts["completed"] == (1 if cancel else 3)
    assert result.counts["cancelled"] == (2 if cancel else 0)
    assert [source_tags(path) for path in paths] == [["reviewed"], *([[], []] if cancel else [["reviewed"], ["reviewed"]])]
    assert len(writes) == len(set(writes)) == result.counts["completed"]
    assert execute(coordinator(semantic_bound, restart=True), frozen) == result


def test_durable_cancel_during_an_owner_effect_prevents_later_starts(semantic_bound, monkeypatch):
    requests, paths = requests_for(semantic_bound)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    entered, release = Event(), Event()
    write = semantic.write_note_from_absolute

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return write(*args, **kwargs)

    monkeypatch.setattr(semantic, "write_note_from_absolute", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(execute, batch, frozen)
        assert entered.wait(10)
        waiting = pool.submit(execute, coordinator(semantic_bound), frozen)
        try:
            cancelled = coordinator(semantic_bound).cancel(frozen.batch_id, expected_digest=frozen.digest)
            assert cancelled.cancel_requested and cancelled.counts["cancelled"] == 2
        finally:
            release.set()
        result = running.result(timeout=15)
        assert waiting.result(timeout=15) == result
    assert result.counts["completed"] == 1 and result.counts["cancelled"] == 2
    assert [source_tags(path) for path in paths] == [["reviewed"], [], []]
    assert len(semantic_bound.records()) == 1


@pytest.mark.parametrize("known", [True, False])
def test_expired_recovery_preserves_known_or_unknown_effect_and_original_version(semantic_bound, monkeypatch, known):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    frozen = preview(batch, requests)
    calls = []
    write = semantic.write_note_from_absolute

    def failed(*args, **kwargs):
        calls.append(kwargs["expected_version"])
        receipt = write(*args, **kwargs)
        if not known:
            raise OSError("effect happened before owner receipt returned")
        return receipt

    monkeypatch.setattr(semantic, "write_note_from_absolute", failed)
    with monkeypatch.context() as patch:
        if known:
            patch.setattr(semantic, "append_jsonl_outbox_event", lambda *_a, **_k: False)
        first = execute(batch, frozen)
    assert first.status == "recovery_required"
    source_effect = SourceEffectStatus.COMMITTED if known else SourceEffectStatus.UNKNOWN
    assert first.items[0].outcome.convergence.source_effect is source_effect
    monkeypatch.setattr(execution_kernel, "time", lambda: 4102444801)
    recovered = execute(coordinator(semantic_bound, restart=True), frozen)
    assert recovered.status == "recovery_required" and recovered.counts["completed"] == 0
    assert recovered.items[0].outcome.convergence.source_effect is source_effect
    assert recovered.items[0].outcome.extensions["recovery_admission"] == "refused"
    if known:
        assert native_receipt(recovered.items[0]) == native_receipt(first.items[0])
    assert calls == [requests[0].expected_version] and source_tags(paths[0]) == ["reviewed"]


def _short_preview(batch, request):
    expiry = time.time() + 3
    delegation = {**delegation_for([request]), "expires_at": expiry}
    frozen = batch.preview(batch_id="deadline", requests=[request], selector={}, delegation=delegation)
    return frozen, expiry


@pytest.mark.parametrize("expired", [True, False])
@pytest.mark.parametrize("wait_site", ["approval", "cas"])
def test_original_batch_deadline_after_semantic_approval_wait_prevents_source(semantic_bound, monkeypatch, expired, wait_site):
    requests, paths = requests_for(semantic_bound, 1)
    batch = coordinator(semantic_bound)
    frozen, expiry = _short_preview(batch, requests[0])
    entered = []

    def wait_for_expiry(*_):
        assert time.time() < expiry
        entered.append(True)
        time.sleep(max(0, expiry - time.time()) + 0.04 if expired else 0.01)

    if wait_site == "approval":
        semantic_bound.hooks["lookup"] = wait_for_expiry
    else:
        snapshot = adapters._snapshot_descriptor_recovery

        def wait_in_cas(*args, **kwargs):
            snapshot(*args, **kwargs)
            wait_for_expiry()

        monkeypatch.setattr(adapters, "_snapshot_descriptor_recovery", wait_in_cas)
    exchanges = []
    exchange = adapters._atomic_exchange_at

    def observed_exchange(*args, **kwargs):
        exchanges.append(True)
        return exchange(*args, **kwargs)

    monkeypatch.setattr(adapters, "_atomic_exchange_at", observed_exchange)
    raw = paths[0].read_bytes()
    result = execute(batch, frozen)
    assert entered == [True]
    assert result.counts["completed"] == int(not expired)
    assert (paths[0].read_bytes() == raw) is expired
    assert len(exchanges) == int(not expired)


@pytest.mark.parametrize("expired", [True, False])
def test_original_batch_deadline_after_body_owner_wait_prevents_source(write_bound, tmp_path, monkeypatch, expired):
    request = test_write_operations._request(write_bound, "artifact.update", arguments={"body": "Should not be applied.\n"})
    kernel = test_write_operations._kernel(write_bound)
    kernel.receipt_store = JsonReceiptStore(tmp_path / "deadline.json")
    batch = BatchOperationCoordinator(kernel)
    frozen, expiry = _short_preview(batch, request)
    raw = write_bound.note_path.read_bytes()
    snapshot = adapters._snapshot_descriptor_recovery
    entered = []

    def wait_then_write(*args, **kwargs):
        result = snapshot(*args, **kwargs)
        assert time.time() < expiry
        entered.append(True)
        time.sleep(max(0, expiry - time.time()) + 0.04 if expired else 0.01)
        return result

    monkeypatch.setattr(adapters, "_snapshot_descriptor_recovery", wait_then_write)
    exchanges = []
    exchange = adapters._atomic_exchange_at

    def observed_exchange(*args, **kwargs):
        exchanges.append(True)
        return exchange(*args, **kwargs)

    monkeypatch.setattr(adapters, "_atomic_exchange_at", observed_exchange)
    result = execute(batch, frozen)
    assert entered == [True]
    assert result.counts["completed"] == int(not expired)
    assert (write_bound.note_path.read_bytes() == raw) is expired
    assert len(exchanges) == int(not expired)


@pytest.mark.parametrize("expired", [True, False])
def test_original_batch_deadline_at_body_conflict_publication_keeps_human_source(write_bound, tmp_path, monkeypatch, expired):
    request = test_write_operations._request(write_bound, "artifact.update", arguments={"body": "A proposed body.\n"})
    kernel = test_write_operations._kernel(write_bound)
    kernel.receipt_store = JsonReceiptStore(tmp_path / "conflict-deadline.json")
    batch = BatchOperationCoordinator(kernel)
    frozen, expiry = _short_preview(batch, request)
    human = write_bound.note_path.read_bytes() + b"A concurrent human save.\n"
    original_files = set(write_bound.vault_root.rglob("*.md"))
    read_handle = adapters._read_handle
    observed = []

    def concurrent_save(handle):
        if not observed:
            observed.append(True)
            write_bound.note_path.write_bytes(human)
            assert time.time() < expiry
            time.sleep(max(0, expiry - time.time()) + 0.04 if expired else 0.01)
        return read_handle(handle)

    monkeypatch.setattr(adapters, "_read_handle", concurrent_save)
    result = execute(batch, frozen)
    assert observed == [True] and result.counts["completed"] == 0
    assert write_bound.note_path.read_bytes() == human
    if expired:
        assert set(write_bound.vault_root.rglob("*.md")) == original_files
        assert result.counts["refused"] == 1
    else:
        assert result.counts["conflicted"] == 1
        native = native_receipt(result.items[0])
        assert native["source_receipt"]["outcome"] == "conflict_staged"
        assert native["authority_receipt"]["outcome"] == "failed"


def test_deadline_consumers_refuse_unsupported_routes_without_dropping_the_ceiling(write_bound):
    calls = []
    cli = adapters.ObsidianCliAdapter(runner=lambda *args, **kwargs: calls.append(args))
    locator = NoteLocator("selected", "Notes/note.md")
    with pytest.raises(KnowledgeCapabilityError, match="deadline"):
        cli.write_note(locator, "Unadmitted CLI write", expected_version="original", admission_deadline=time.time() + 60)
    with pytest.raises(KnowledgeCapabilityError, match="deadline"):
        adapters.FsVaultAdapter(write_bound.vault_root).write_note(locator, "Unversioned write", admission_deadline=time.time() + 60)
    assert calls == []


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("expired", [True, False])
def test_original_batch_deadline_after_real_placement_lock_wait_prevents_effect(placement_bound, monkeypatch, recover, expired):
    request = test_placement_operations._request(placement_bound)
    batch = BatchOperationCoordinator(test_placement_operations._kernel(placement_bound))
    frozen, expiry = _short_preview(batch, request)
    if recover:
        save = placement_bound.owner._store

        def interrupt(root, state, name, value):
            save(root, state, name, value)
            if value["phase"] == "prepared":
                raise Interrupted()

        with monkeypatch.context() as patch:
            patch.setattr(placement_bound.owner, "_store", interrupt)
            with pytest.raises(Interrupted):
                execute(batch, frozen)
        placement_bound = test_placement_operations._restart(placement_bound)
        batch = BatchOperationCoordinator(test_placement_operations._kernel(placement_bound),
            reconcile_owner=lambda r: placement_operations.reconcile_placement_operation(r, placement_bound))
    source = placement_bound.owner.root / placement_bound.source
    raw = source.read_bytes()
    state = placement_bound.owner.root / ".pkm-placement"
    state.mkdir(mode=0o700, exist_ok=True)
    holder = os.open(state / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    flock = fcntl.flock
    flock(holder, fcntl.LOCK_EX)
    lock_inode = os.fstat(holder).st_ino
    queued = Event()

    def wait_observed(fd, operation):
        if fd != holder and os.fstat(fd).st_ino == lock_inode:
            queued.set()
        return flock(fd, operation)

    monkeypatch.setattr(test_placement_operations.placement.fcntl, "flock", wait_observed)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(execute, batch, frozen)
            try:
                assert queued.wait(2), "owner did not reach the real held placement lock"
                assert time.time() < expiry
                time.sleep(max(0, expiry - time.time()) + 0.04 if expired else 0.01)
            finally:
                flock(holder, fcntl.LOCK_UN)
            result = pending.result(timeout=5)
    finally:
        os.close(holder)
    assert result.counts["completed"] == int(not expired)
    if expired:
        assert source.read_bytes() == raw and not (placement_bound.owner.root / "Projects/moved.md").exists()
    else:
        assert not source.exists() and (placement_bound.owner.root / "Projects/moved.md").read_bytes() == raw


def test_recovery_cannot_replace_the_original_decision_with_a_same_version_token(placement_bound, monkeypatch):
    request = test_placement_operations._request(placement_bound)
    batch = BatchOperationCoordinator(test_placement_operations._kernel(placement_bound))
    frozen = preview(batch, [request])
    store = placement_bound.owner._store

    def interrupt(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == "prepared":
            raise Interrupted()

    with monkeypatch.context() as patch:
        patch.setattr(placement_bound.owner, "_store", interrupt)
        with pytest.raises(Interrupted):
            execute(batch, frozen)
    restarted = test_placement_operations._restart(placement_bound)
    resumed = BatchOperationCoordinator(test_placement_operations._kernel(restarted),
        reconcile_owner=lambda r: placement_operations.reconcile_placement_operation(r, restarted))
    original = test_placement_operations._record(restarted)
    original_decision = resumed.kernel.policy_evaluator
    resumed.kernel.policy_evaluator = lambda *_: PolicyDecision.allowed("policy-1", "replacement-token")
    refused = execute(resumed, frozen)
    assert refused.counts["completed"] == 0 and refused.status == "recovery_required"
    assert refused.items[0].outcome.extensions["recovery_admission"] == "decision_rebinding_refused"
    assert test_placement_operations._record(restarted) == original
    assert (restarted.owner.root / restarted.source).exists()
    resumed.kernel.policy_evaluator = original_decision
    recovered = execute(resumed, frozen)
    assert recovered.counts["completed"] == 1
    assert recovered.items[0].outcome.receipt.extensions["placement"]["source_generation"] == request.expected_version


@pytest.mark.parametrize("phase,known", [("publishing", False), ("activated", True), ("committed", True)])
def test_batch_deadline_after_a_durable_placement_transition_retains_effect_truth(placement_bound, monkeypatch, phase, known):
    request = test_placement_operations._request(placement_bound)
    batch = BatchOperationCoordinator(test_placement_operations._kernel(placement_bound))
    frozen, expiry = _short_preview(batch, request)
    store = placement_bound.owner._store
    observed = []

    def wait_at_transition(root, state, name, value):
        store(root, state, name, value)
        if value["phase"] == phase and not observed:
            observed.append(True)
            assert time.time() < expiry
            time.sleep(max(0, expiry - time.time()) + 0.04)

    monkeypatch.setattr(placement_bound.owner, "_store", wait_at_transition)
    result = execute(batch, frozen)
    expected = SourceEffectStatus.COMMITTED if known else SourceEffectStatus.UNKNOWN
    assert observed == [True] and result.counts["completed"] == 0
    assert result.items[0].outcome.convergence.source_effect is expected
    destination = placement_bound.owner.root / "Projects/moved.md"
    assert destination.exists() is known
    original = test_placement_operations._record(placement_bound)
    assert original["phase"] == ("retiring" if phase == "activated" else phase)
    if phase == "activated":
        # The existing owner may durably mark its next phase before that
        # phase's effect guard. Expiry still prevents source retirement.
        assert (placement_bound.owner.root / placement_bound.source).exists()
    repeated = execute(batch, frozen)
    assert repeated.counts["completed"] == 0
    assert repeated.items[0].outcome.convergence.source_effect is expected
    assert test_placement_operations._record(placement_bound) == original
    if phase == "committed":
        assert repeated.items[0].outcome.receipt.extensions["placement"]["governed_write"]["authority_receipt"]["effect_id"] == request.request_id
