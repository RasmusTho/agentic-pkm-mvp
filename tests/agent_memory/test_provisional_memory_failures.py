from __future__ import annotations

from pathlib import Path
from uuid import UUID

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
