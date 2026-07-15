from __future__ import annotations

from datetime import datetime, timedelta, timezone
import multiprocessing
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.agent_memory import provisional_write as provisional_write_module
from app.agent_memory.candidate import MemoryType
from app.agent_memory.provisional_memory import (
    ProvisionalLifecycleReceipt,
    ProvisionalLifecycleTransition,
    ProvisionalReconciliationState,
    ProvisionalSensitivity,
)
from app.agent_memory.provisional_write import (
    ProvisionalMemoryWriteError,
    ProvisionalReceiptStore,
    ProvisionalReceiptStoreError,
    ProvisionalWriteRequest,
    write_provisional_memory,
)
from app.write_guard import WriteGuard, WritesBlockedError


class _FailCreatedReceiptStore:
    def __init__(self) -> None:
        self.receipts: list[ProvisionalLifecycleReceipt] = []

    def append(self, receipt: ProvisionalLifecycleReceipt) -> None:
        if receipt.transition is ProvisionalLifecycleTransition.CREATED:
            raise OSError("receipt disk unavailable")
        self.receipts.append(receipt)

    def list_for(self, memory_id: UUID) -> tuple[ProvisionalLifecycleReceipt, ...]:
        return tuple(item for item in self.receipts if item.memory_id == memory_id)


class _FailFirstReceiptStore(_FailCreatedReceiptStore):
    def append(self, receipt: ProvisionalLifecycleReceipt) -> None:
        raise OSError("receipt ledger unavailable")


class _MemoryReceiptStore(_FailCreatedReceiptStore):
    def append(self, receipt: ProvisionalLifecycleReceipt) -> None:
        self.receipts.append(receipt)


def _append_receipt_process(path: str, payload: str) -> None:
    store = ProvisionalReceiptStore(Path(path))
    store.append(ProvisionalLifecycleReceipt.model_validate_json(payload))


def _staged_receipt(
    *,
    memory_id: UUID,
    offset: int,
) -> ProvisionalLifecycleReceipt:
    return ProvisionalLifecycleReceipt(
        receipt_id=uuid4(),
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        transition=ProvisionalLifecycleTransition.WRITE_STAGED,
        actor_ref="agent",
        occurred_at=datetime(2026, 7, 15, tzinfo=timezone.utc)
        + timedelta(microseconds=offset),
    )


def _request() -> ProvisionalWriteRequest:
    return ProvisionalWriteRequest(
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="Never admit an orphan.",
        provenance_event_ids=("event-1",),
    )


def test_partial_write_fails_closed_and_reconciles(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _FailCreatedReceiptStore()

    with pytest.raises(ProvisionalMemoryWriteError) as caught:
        write_provisional_memory(
            _request(),
            vault_root=vault,
            receipt_store=store,
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
        )

    error = caught.value
    assert error.reconciliation.state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
    assert error.reconciliation.record is None
    assert [item.transition for item in store.receipts] == [
        ProvisionalLifecycleTransition.WRITE_STAGED
    ]
    artifacts = list((vault / "Memory" / "Provisional").glob("*.md"))
    assert len(artifacts) == 1
    assert "Never admit an orphan." in artifacts[0].read_text(encoding="utf-8")


def test_writeguard_block_creates_neither_artifact_nor_receipt(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _FailCreatedReceiptStore()
    guard = WriteGuard(
        snapshot_fn=lambda: {"state": "safe_mode", "reason": "operator block"},
        bootstrap_actions=(),
    )

    with pytest.raises(WritesBlockedError):
        write_provisional_memory(
            _request(),
            vault_root=vault,
            receipt_store=store,
            write_guard=guard,
        )

    assert store.receipts == []
    assert not (vault / "Memory" / "Provisional").exists()


def test_staged_receipt_failure_happens_before_artifact_write(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ProvisionalMemoryWriteError) as caught:
        write_provisional_memory(
            _request(),
            vault_root=vault,
            receipt_store=_FailFirstReceiptStore(),
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
        )

    assert caught.value.reconciliation.state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
    assert caught.value.reconciliation.record is None
    assert not (vault / "Memory" / "Provisional").exists()


def test_artifact_failure_records_retryable_content_free_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _MemoryReceiptStore()

    def _fail_write(*args: object, **kwargs: object) -> None:
        raise PermissionError("claim text must not enter the receipt")

    monkeypatch.setattr(provisional_write_module, "write_note_relative", _fail_write)

    with pytest.raises(ProvisionalMemoryWriteError) as caught:
        write_provisional_memory(
            _request(),
            vault_root=vault,
            receipt_store=store,
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
        )

    assert caught.value.reconciliation.state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
    assert caught.value.reconciliation.record is None
    assert [item.transition for item in store.receipts] == [
        ProvisionalLifecycleTransition.WRITE_STAGED,
        ProvisionalLifecycleTransition.WRITE_FAILED,
    ]
    failed_payload = store.receipts[-1].content_free_payload()
    assert failed_payload["error_code"] == "permission_denied"
    assert "claim text" not in str(failed_payload)
    assert not (vault / "Memory" / "Provisional").exists()


def test_receipt_store_serializes_cross_process_appends(tmp_path: Path) -> None:
    path = tmp_path / "receipts.jsonl"
    memory_id = uuid4()
    receipts = [_staged_receipt(memory_id=memory_id, offset=index) for index in range(8)]
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_append_receipt_process,
            args=(str(path), receipt.model_dump_json()),
        )
        for receipt in receipts
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    restarted = ProvisionalReceiptStore(path)
    persisted = restarted.list_for(memory_id)
    assert {item.receipt_id for item in persisted} == {
        item.receipt_id for item in receipts
    }
    assert len(path.read_text(encoding="utf-8").splitlines()) == len(receipts)


def test_failed_atomic_replace_preserves_restart_readability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "receipts.jsonl"
    memory_id = uuid4()
    first = _staged_receipt(memory_id=memory_id, offset=1)
    second = _staged_receipt(memory_id=memory_id, offset=2)
    store = ProvisionalReceiptStore(path)
    store.append(first)

    def _fail_replace(source: object, target: object) -> None:
        raise OSError("simulated replace failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(provisional_write_module.os, "replace", _fail_replace)
        with pytest.raises(OSError, match="simulated replace failure"):
            store.append(second)

    restarted = ProvisionalReceiptStore(path)
    assert restarted.list_for(memory_id) == (first,)
    assert list(tmp_path.glob("*.tmp")) == []


def test_visible_receipt_after_directory_fsync_failure_is_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    path = tmp_path / "receipts.jsonl"
    fsync_calls = 0

    def _fail_created_directory_fsync(directory: Path) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 2:
            raise OSError("simulated post-replace directory fsync failure")

    monkeypatch.setattr(
        provisional_write_module,
        "_fsync_directory",
        _fail_created_directory_fsync,
    )
    result = write_provisional_memory(
        _request(),
        vault_root=vault,
        receipt_store=ProvisionalReceiptStore(path),
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )

    assert result.reconciliation.state is ProvisionalReconciliationState.READY
    restarted = ProvisionalReceiptStore(path)
    assert [item.transition for item in restarted.list_for(result.lifecycle_receipt.memory_id)] == [
        ProvisionalLifecycleTransition.WRITE_STAGED,
        ProvisionalLifecycleTransition.CREATED,
    ]


def test_corrupt_ledger_restart_fails_closed_before_artifact(tmp_path: Path) -> None:
    path = tmp_path / "receipts.jsonl"
    memory_id = uuid4()
    store = ProvisionalReceiptStore(path)
    store.append(_staged_receipt(memory_id=memory_id, offset=1))
    path.write_bytes(path.read_bytes() + b'{"partial"')

    restarted = ProvisionalReceiptStore(path)
    with pytest.raises(ProvisionalReceiptStoreError):
        restarted.list_for(memory_id)

    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(ProvisionalMemoryWriteError) as caught:
        write_provisional_memory(
            _request(),
            vault_root=vault,
            receipt_store=restarted,
            write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
        )
    assert caught.value.reconciliation.record is None
    assert not (vault / "Memory" / "Provisional").exists()
