from __future__ import annotations

import hashlib
import inspect
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.agent_memory.materialization as materialization_module
import app.receipts.outbox_sources as outbox_sources_module
import app.services.outbox as outbox_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.materialization import (
    MemoryMaterializationError,
    materialize_promoted_memory,
)
from app.agent_memory.review_decision_store import (
    ReviewDecisionStore,
    ReviewDecisionStoreError,
)
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewDecision
from app.receipts.promotion_receipts import (
    PromotionReceiptQueryResult,
    query_promotion_receipts,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError


def _vault(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-a",
        active_vault_name="Vault A",
        active_vault_path=str(root),
    )


def _candidate(
    *,
    candidate_id: str = "candidate-semantic",
    memory_type: MemoryType = MemoryType.SEMANTIC_MEMORY,
    title: str = "Explicit semantic memory",
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title=title,
        memory_type=memory_type,
        inferred=False,
        content="The user explicitly prefers design docs before code.",
        source_refs=["note:source.md", "session:2026-06-13T09:00:00Z"],
        derived_from="vault:source.md",
        generated_by="companion_agent",
        scope_id="scope:test/materialization",
    )


def _promoted(
    candidate: MemoryCandidate,
    *,
    store: ReviewDecisionStore,
    vault: VaultContext,
    channel: str = "test",
):
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(candidate)
    entry = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Confirmed.",
    )
    store.record_decision(entry, vault_context=vault, channel=channel)
    return entry


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocked_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "operator hold"})


def _outbox_events(path: Path) -> list[str]:
    return [
        json.loads(line)["event"]
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _outbox_records(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rewrite_outbox_preserving_source_binding(path: Path, content: str) -> None:
    """Forge a self-consistent test source so deeper validators remain observable."""

    source_binding = materialization_module._validate_materialization_source_marker(
        path
    )
    path.write_text(content, encoding="utf-8")
    materialization_module._materialization_source_marker_path(path).unlink()
    materialization_module._write_materialization_source_marker(
        path,
        source_binding=source_binding,
    )


def test_promotion_materializes_via_writeguard_with_receipt(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(_candidate(), store=store, vault=vault)

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.status == "materialized"
    assert result.artifact_path is not None
    note_path = Path(vault.active_vault_path) / result.artifact_path
    assert note_path.exists()

    receipts = query_promotion_receipts(vault_root=Path(vault.active_vault_path), outbox_path=outbox)
    assert [row.receipt_id for row in receipts.rows] == [result.receipt_id]
    assert receipts.rows[0].artifact_path == result.artifact_path
    assert receipts.rows[0].outcome_status == "applied"
    assert store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    ).terminal is True


def test_blocked_writes_prevent_materialization(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    entry = _promoted(_candidate(), store=store, vault=vault)

    with pytest.raises(MemoryMaterializationError) as excinfo:
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_blocked_guard(),
            outbox_path=tmp_path / "outbox.jsonl",
        )

    assert isinstance(excinfo.value.__cause__, WritesBlockedError)
    assert not list(Path(vault.active_vault_path).rglob("*.md"))


def test_semantic_materialization_requires_scope_before_write(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate().model_copy(update={"scope_id": None})
    entry = _promoted(candidate, store=store, vault=vault)

    with pytest.raises(MemoryMaterializationError, match="candidate.scope_id"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert not outbox.exists()
    record = store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    )
    assert record is not None
    assert record.terminal is False


def test_materialization_requires_entry_scope_to_match_persisted_decision(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(candidate_id="candidate-scope-cas")
    _promoted(candidate, store=store, vault=vault)

    stale_candidate = candidate.model_copy(update={"scope_id": "scope:test/other"})
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(stale_candidate)
    stale_entry = queue.decide(
        stale_candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Stale in-memory review entry.",
    )

    with pytest.raises(MemoryMaterializationError, match="persisted review decision"):
        materialize_promoted_memory(
            stale_entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert not outbox.exists()
    record = store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    )
    assert record is not None
    assert record.scope_id == "scope:test/materialization"
    assert record.terminal is False


def test_materialization_refuses_intervening_same_scope_rejection(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(candidate_id="candidate-revoked")
    stale_promote = _promoted(candidate, store=store, vault=vault)

    replacement_queue = MemoryCandidateReviewQueue()
    replacement_queue.enqueue(candidate)
    rejection = replacement_queue.decide(
        candidate.candidate_id,
        ReviewDecision.REJECT,
        decided_by="companion-ui:reviewer",
        notes="Promotion authority revoked before materialization.",
    )
    store.record_decision(rejection, vault_context=vault, channel="test")

    with pytest.raises(MemoryMaterializationError, match="persisted promote decision"):
        materialize_promoted_memory(
            stale_promote,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert not outbox.exists()
    record = store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    )
    assert record is not None
    assert record.outcome is ReviewDecision.REJECT
    assert record.terminal is True


def test_duplicate_materializer_refuses_after_terminal_success(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-single-writer"),
        store=store,
        vault=vault,
    )

    first = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )
    with pytest.raises(MemoryMaterializationError, match="already terminal"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert first.artifact_path is not None
    assert len(list(Path(vault.active_vault_path).rglob("*.md"))) == 1
    receipts = query_promotion_receipts(
        vault_root=Path(vault.active_vault_path),
        outbox_path=outbox,
    )
    assert [row.outcome_status for row in receipts.rows] == ["applied"]


def test_memory_promotion_refuses_legacy_ungoverned_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-legacy-ungoverned"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_promotion_receipt

    def append_legacy_receipt(*args: object, **kwargs: object) -> str:
        kwargs.pop("governed_facts", None)
        return original_append(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        append_legacy_receipt,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="predates the governed write chain",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        original_append,
    )
    with pytest.raises(
        MemoryMaterializationError,
        match="predates the governed write chain",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    assert _outbox_events(outbox) == ["promotion.transition.applied"]
    interrupted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert interrupted is not None
    assert interrupted.terminal is False
    assert interrupted.materializing is True


def test_memory_promotion_fails_closed_when_receipt_source_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-unavailable-receipt-source"),
        store=store,
        vault=vault,
    )
    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        lambda *args, **kwargs: PromotionReceiptQueryResult(source_available=False),
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="promotion receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not list(vault_root.rglob("*.md"))
    assert outbox.read_text(encoding="utf-8") == ""
    interrupted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert interrupted is not None
    assert interrupted.terminal is False
    assert interrupted.materializing is True


def test_retry_reconciles_applied_receipt_after_late_query_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-query"),
        store=store,
        vault=vault,
    )
    original_query = materialization_module.query_promotion_receipts
    query_calls = 0

    def fail_post_append_query(*args, **kwargs):
        nonlocal query_calls
        query_calls += 1
        if query_calls == 2:
            raise RuntimeError("injected post-append query failure")
        return original_query(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        fail_post_append_query,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    assert len(outbox.read_text(encoding="utf-8").splitlines()) == 1
    interrupted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert interrupted.terminal is False
    assert interrupted.materializing is True

    changed_candidate = entry.candidate.model_copy(
        update={"content": "Changed candidate content after restart."}
    )
    changed_queue = MemoryCandidateReviewQueue()
    changed_queue.enqueue(changed_candidate)
    changed_retry = changed_queue.decide(
        changed_candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
    )
    with pytest.raises(ReviewDecisionStoreError, match="content cannot change"):
        store.record_decision(
            changed_retry,
            vault_context=vault,
            channel="test",
        )

    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        original_query,
    )
    retry_queue = MemoryCandidateReviewQueue()
    retry_queue.enqueue(entry.candidate)
    retry_entry = retry_queue.decide(
        entry.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
        notes="Retry after restart.",
    )
    persisted_retry = store.record_decision(
        retry_entry,
        vault_context=vault,
        channel="test",
    )
    assert persisted_retry.decided_by == "companion-ui:reviewer"
    result = materialize_promoted_memory(
        retry_entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.status == "materialized"
    assert len(list(vault_root.rglob("*.md"))) == 1
    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        "governance.authority_receipt.recorded",
    ]
    completed = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert completed.terminal is True
    assert completed.materializing is False


def test_retry_refuses_candidate_note_without_governed_receipt_after_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-append"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_promotion_receipt

    def fail_receipt_append(*args, **kwargs):
        raise RuntimeError("injected receipt append failure")

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        fail_receipt_append,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
            memory_dir="Memory A",
        )

    first_note = next(vault_root.rglob("*.md"))
    receipt_id = materialization_module._stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault,
        channel="test",
    )
    marker = materialization_module._validated_materialization_source_marker(outbox)
    assert marker.target_reservations == {
        receipt_id: first_note.relative_to(vault_root).as_posix()
    }
    first_body = first_note.read_text(encoding="utf-8")
    assert outbox.read_text(encoding="utf-8") == ""
    interrupted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert interrupted.terminal is False
    assert interrupted.materializing is True

    rejection_queue = MemoryCandidateReviewQueue()
    rejection_queue.enqueue(entry.candidate)
    rejection = rejection_queue.decide(
        entry.candidate_id,
        ReviewDecision.REJECT,
        decided_by="companion-ui:restart-reviewer",
    )
    with pytest.raises(ReviewDecisionStoreError, match="in progress"):
        store.record_decision(rejection, vault_context=vault, channel="test")

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        original_append,
    )
    retry_queue = MemoryCandidateReviewQueue()
    retry_queue.enqueue(entry.candidate)
    retry_entry = retry_queue.decide(
        entry.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
        notes="Retry after restart.",
    )
    store.record_decision(retry_entry, vault_context=vault, channel="test")
    with pytest.raises(
        MemoryMaterializationError,
        match="reserved memory materialization target requires explicit remediation",
    ):
        materialize_promoted_memory(
            retry_entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
            memory_dir="Memory B",
        )

    assert first_note.read_text(encoding="utf-8") == first_body
    assert len(list(vault_root.rglob("*.md"))) == 1
    assert outbox.read_text(encoding="utf-8") == ""
    unresolved = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert unresolved.terminal is False
    assert unresolved.materializing is True


@pytest.mark.parametrize(
    "alteration",
    ("agent_promoted", "candidate_id", "scope_id", "unreadable_frontmatter"),
)
def test_retry_refuses_altered_candidate_note_after_receipt_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alteration: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-altered-after-append-failure"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_promotion_receipt
    original_write = materialization_module.write_note_relative
    hka_calls = 0

    def fail_receipt_append(*args, **kwargs):
        raise RuntimeError("injected receipt append failure")

    def count_hka(*args, **kwargs):
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        fail_receipt_append,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    first_note = next(vault_root.rglob("*.md"))
    first_body = first_note.read_text(encoding="utf-8")
    if alteration == "agent_promoted":
        altered_body = first_body.replace(
            "agent_promoted: true",
            "agent_promoted: false",
            1,
        )
    elif alteration == "candidate_id":
        altered_body = "\n".join(
            line
            for line in first_body.splitlines()
            if not line.startswith("promoted_from_candidate_id:")
        ) + "\n"
    elif alteration == "scope_id":
        altered_body = "\n".join(
            line for line in first_body.splitlines() if not line.startswith("scope_id:")
        ) + "\n"
    else:
        altered_body = "human replacement without frontmatter\n"
    first_note.write_text(altered_body, encoding="utf-8")
    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        original_append,
    )
    retry_queue = MemoryCandidateReviewQueue()
    retry_queue.enqueue(entry.candidate)
    retry_entry = retry_queue.decide(
        entry.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
        notes="Retry after restart.",
    )
    store.record_decision(retry_entry, vault_context=vault, channel="test")

    with pytest.raises(
        MemoryMaterializationError,
        match="reserved memory materialization target requires explicit remediation",
    ):
        materialize_promoted_memory(
            retry_entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 1
    assert list(vault_root.rglob("*.md")) == [first_note]
    assert not list(first_note.parent.glob(f"{first_note.stem}-2.md"))
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_conflicting_structured_jsonl_event_alias_refuses_before_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-conflicting-jsonl-alias"),
        store=store,
        vault=vault,
    )
    outbox.write_text(
        json.dumps(
            {
                "event": "unrelated.event",
                "event_type": "governance.authority_receipt.recorded",
                "event_id": "masked-authority-history",
                "payload": "{",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    materialization_module._write_materialization_source_marker(outbox)
    hka_calls = 0

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with ambiguous authority history")

    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source is unavailable|receipt source.*reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 0
    assert not list(vault_root.rglob("*.md"))


def test_db_topic_shadowing_refuses_before_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-shadowed-db-topic"),
        store=store,
        vault=vault,
    )
    hka_calls = 0

    class ShadowedTopicCursor:
        returned = False

        def fetchmany(self, _size: int) -> list[tuple[object, ...]]:
            if self.returned:
                return []
            self.returned = True
            return [
                (
                    "shadowed-db-row",
                    "governance.authority_receipt.recorded",
                    {
                        "event": "unrelated.event",
                        "event_type": "unrelated.event",
                        "payload": "{",
                    },
                    None,
                )
            ]

    def db_records() -> list[dict[str, object]]:
        return list(
            outbox_sources_module._iter_db_outbox_records(ShadowedTopicCursor())
        )

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with a shadowed DB authority topic")

    monkeypatch.setattr(outbox_sources_module, "_db_outbox_configured", lambda: True)
    monkeypatch.setattr(outbox_sources_module, "_read_db_outbox_records", db_records)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source is unavailable|receipt source.*reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 0
    assert not list(vault_root.rglob("*.md"))


def test_retry_refuses_visible_authority_receipt_until_source_fsync_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-visible-unsynced-authority"),
        store=store,
        vault=vault,
    )
    original_append = outbox_module._append_jsonl_outbox_event_unlocked
    original_source_fsync = materialization_module._fsync_materialization_file
    original_write = materialization_module.write_note_relative
    fail_authority_append = True
    fail_source_fsync = False
    source_fsync_calls = 0
    hka_calls = 0

    def append_complete_record_then_fail_fsync(
        path: Path,
        record: dict[str, object],
    ) -> None:
        nonlocal fail_authority_append
        if (
            record.get("event")
            == materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT
            and fail_authority_append
        ):
            fail_authority_append = False
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
            raise OSError("injected AuthorityReceipt fsync failure after complete write")
        original_append(path, record)

    def controlled_source_fsync(path: Path) -> None:
        nonlocal source_fsync_calls
        if path == outbox:
            source_fsync_calls += 1
            if fail_source_fsync:
                raise OSError("injected recovery source fsync failure")
        original_source_fsync(path)

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        outbox_module,
        "_append_jsonl_outbox_event_unlocked",
        append_complete_record_then_fail_fsync,
    )
    monkeypatch.setattr(
        materialization_module,
        "_fsync_materialization_file",
        controlled_source_fsync,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        "governance.authority_receipt.recorded",
    ]
    assert hka_calls == 1
    first = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert first is not None
    assert first.terminal is False

    calls_before_retry = source_fsync_calls
    fail_source_fsync = True
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert source_fsync_calls == calls_before_retry + 1
    after_failed_barrier = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert after_failed_barrier is not None
    assert after_failed_barrier.terminal is False
    assert hka_calls == 1

    fail_source_fsync = False
    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.terminal is True
    assert source_fsync_calls == calls_before_retry + 2
    assert hka_calls == 1


def test_gov_issuance_timestamp_is_not_backdated_to_human_review(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate(candidate_id="candidate-current-gov-issuance")
    queue.enqueue(candidate)
    entry = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Confirmed long ago.",
    ).model_copy(update={"decided_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
    store.record_decision(entry, vault_context=vault, channel="test")

    assert materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True

    promotion = next(
        record
        for record in _outbox_records(outbox)
        if record["event"] == "promotion.transition.applied"
    )
    payload = promotion["payload"]
    assert isinstance(payload, dict)
    policy = payload["policy_decision"]
    token = payload["decision_token"]
    mutation = payload["state_owner_receipt"]
    assert isinstance(policy, dict)
    assert isinstance(token, dict)
    assert isinstance(mutation, dict)
    issued_at = datetime.fromisoformat(str(policy["issued_at"]).replace("Z", "+00:00"))
    written_at = datetime.fromisoformat(
        str(mutation["written_at"]).replace("Z", "+00:00")
    )
    assert policy["issued_at"] != entry.decided_at.isoformat().replace("+00:00", "Z")
    assert issued_at >= entry.decided_at.replace(microsecond=0)
    assert token["issued_at"] == policy["issued_at"]
    authority_record = next(
        record
        for record in _outbox_records(outbox)
        if record["event"] == "governance.authority_receipt.recorded"
    )
    authority_payload = authority_record["payload"]
    assert isinstance(authority_payload, dict)
    authority = authority_payload["authority_receipt"]
    assert isinstance(authority, dict)
    recorded_at = datetime.fromisoformat(
        str(authority["recorded_at"]).replace("Z", "+00:00")
    )
    assert issued_at <= written_at <= recorded_at
    assert authority["recorded_at"] != mutation["written_at"]


def test_retry_refuses_changed_policy_decision_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-policy-reason-integrity"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_materialization_authority_receipt

    def interrupt_before_authority(*args: object, **kwargs: object) -> object:
        raise OSError("injected interruption before AuthorityReceipt")

    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        interrupt_before_authority,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )
    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        original_append,
    )
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    source_binding = persisted.materialization_source_binding
    assert source_binding is not None

    records = _outbox_records(outbox)
    payload = records[0]["payload"]
    assert isinstance(payload, dict)
    policy = payload["policy_decision"]
    assert isinstance(policy, dict)
    policy["reason"] = "A different policy reason was persisted."
    _rewrite_outbox_preserving_source_binding(
        outbox,
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="persisted GOV authorization",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize(
    "malformation",
    (
        "string_valid",
        "missing_valid",
        "empty_token_id",
        "empty_decision_ids",
        "foreign_governed_ids",
        "missing_issued_at",
        "missing_hka_fields",
        "malformed_hka_timestamp",
        "padded_hka_path",
        "padded_token_resource",
        "backslash_token_resource",
        "already_exists_hka_outcome",
        "hka_before_gov_issuance",
    ),
)
def test_retry_refuses_malformed_persisted_governed_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-malformed-{malformation}"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_materialization_authority_receipt

    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected authority receipt failure")
        ),
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    records = _outbox_records(outbox)
    payload = records[0]["payload"]
    assert isinstance(payload, dict)
    policy = payload["policy_decision"]
    token = payload["decision_token"]
    mutation = payload["state_owner_receipt"]
    assert isinstance(policy, dict)
    assert isinstance(token, dict)
    assert isinstance(mutation, dict)
    if malformation == "string_valid":
        token["valid"] = "false"
    elif malformation == "missing_valid":
        token.pop("valid")
    elif malformation == "empty_token_id":
        token["token_id"] = ""
    elif malformation == "empty_decision_ids":
        policy["decision_id"] = ""
        token["decision_id"] = ""
    elif malformation == "foreign_governed_ids":
        policy["decision_id"] = "foreign-decision"
        token["decision_id"] = "foreign-decision"
        token["token_id"] = "foreign-token"
    elif malformation == "missing_issued_at":
        policy["issued_at"] = None
        token["issued_at"] = None
    elif malformation == "missing_hka_fields":
        for field in (
            "outcome",
            "written_at",
            "fallback_used",
            "trace_id",
            "conflict_artifact",
        ):
            mutation.pop(field)
    elif malformation == "padded_hka_path":
        locator = mutation["locator"]
        assert isinstance(locator, dict)
        locator["path"] = f" {payload['artifact_path']} "
    elif malformation == "padded_token_resource":
        token["resource"] = f" {payload['artifact_path']} "
    elif malformation == "backslash_token_resource":
        token["resource"] = str(payload["artifact_path"]).replace("/", "\\")
    elif malformation == "already_exists_hka_outcome":
        mutation["outcome"] = "already_exists"
    elif malformation == "hka_before_gov_issuance":
        mutation["written_at"] = "2000-01-01T00:00:00Z"
    else:
        mutation["written_at"] = {"invalid": "timestamp"}
    _rewrite_outbox_preserving_source_binding(
        outbox,
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
    )
    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        original_append,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="persisted (?:GOV authorization|HKA mutation receipt)",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert _outbox_events(outbox) == ["promotion.transition.applied"]
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize(
    "malformation",
    (
        "foreign_requested_by",
        "missing_authority",
        "rejected_review_state",
        "wrong_channel",
        "wrong_trace",
        "wrong_linkage",
        "integer_inferred",
        "float_inferred",
        "promotion_before_hka",
    ),
)
def test_retry_refuses_conflicting_promotion_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-promotion-{malformation}"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_materialization_authority_receipt

    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected authority receipt failure")
        ),
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    records = _outbox_records(outbox)
    assert len(records) == 1
    record = records[0]
    payload = record["payload"]
    assert isinstance(payload, dict)
    authority = payload["authority"]
    outcome = payload["outcome"]
    linkage = payload["artifact_linkage"]
    basis = payload["basis"]
    assert isinstance(authority, dict)
    assert isinstance(outcome, dict)
    assert isinstance(linkage, dict)
    assert isinstance(basis, dict)
    if malformation == "foreign_requested_by":
        authority["requested_by"] = "human:different-reviewer"
    elif malformation == "missing_authority":
        payload["authority"] = {}
    elif malformation == "rejected_review_state":
        outcome["review_state"] = "rejected"
    elif malformation == "wrong_channel":
        payload["channel"] = "prod"
    elif malformation == "wrong_trace":
        record["trace_id"] = "foreign-trace"
        payload["trace_id"] = "foreign-trace"
    elif malformation == "integer_inferred":
        basis["inferred"] = 0
    elif malformation == "float_inferred":
        basis["inferred"] = 0.0
    elif malformation == "promotion_before_hka":
        record["timestamp"] = "2000-01-01T00:00:00Z"
    else:
        linkage["candidate_id"] = "foreign-candidate"
    _rewrite_outbox_preserving_source_binding(
        outbox,
        json.dumps(record, sort_keys=True) + "\n",
    )
    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        original_append,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="promotion evidence conflicts",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    assert _outbox_events(outbox) == ["promotion.transition.applied"]
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_retry_refuses_missing_target_reservation_after_hka_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-missing-target-reservation"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_promotion_receipt
    original_write = materialization_module.write_note_relative
    hka_calls = 0

    def fail_receipt_append(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected receipt append failure")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        fail_receipt_append,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    first_note = next(vault_root.rglob("*.md"))
    first_note.write_text("human replacement without frontmatter\n", encoding="utf-8")
    marker_path = materialization_module._materialization_source_marker_path(outbox)
    marker_payload = json.loads(marker_path.read_text(encoding="utf-8"))
    marker_payload.pop("target_reservations")
    marker_path.write_text(json.dumps(marker_payload, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        original_append,
    )

    retry_queue = MemoryCandidateReviewQueue()
    retry_queue.enqueue(entry.candidate)
    retry_entry = retry_queue.decide(
        entry.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
        notes="Retry after restart.",
    )
    store.record_decision(retry_entry, vault_context=vault, channel="test")

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source continuity marker is invalid",
    ):
        materialize_promoted_memory(
            retry_entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 1
    assert list(vault_root.rglob("*.md")) == [first_note]
    assert not list(first_note.parent.glob(f"{first_note.stem}-2.md"))
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_fresh_attempt_upgrades_legacy_marker_without_reservation_state(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-legacy-marker-upgrade"),
        store=store,
        vault=vault,
    )
    outbox.write_text("", encoding="utf-8")
    materialization_module._write_materialization_source_marker(outbox)
    marker_path = materialization_module._materialization_source_marker_path(outbox)
    marker_payload = json.loads(marker_path.read_text(encoding="utf-8"))
    marker_payload["contract"] = (
        materialization_module._LEGACY_MATERIALIZATION_SOURCE_MARKER_CONTRACT
    )
    marker_payload.pop("target_reservations")
    marker_path.write_text(json.dumps(marker_payload, sort_keys=True), encoding="utf-8")

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.terminal is True
    assert len(list(vault_root.rglob("*.md"))) == 1
    upgraded = materialization_module._validated_materialization_source_marker(outbox)
    assert upgraded.target_reservations_authoritative is True
    upgraded_payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert (
        upgraded_payload["contract"]
        == materialization_module._MATERIALIZATION_SOURCE_MARKER_CONTRACT
    )


def test_stale_first_attempt_cannot_recreate_missing_owned_receipt_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-stale-source-initialization"),
        store=store,
        vault=vault,
    )
    original_transaction = store.promotion_materialization_transaction
    original_initialize = materialization_module._initialize_materialization_receipt_source
    initialized = 0
    hka_calls = 0

    @contextmanager
    def reserve_then_enter(*args: object, **kwargs: object):
        competing_kwargs = dict(kwargs)
        competing_kwargs.pop("initialize_first_attempt", None)
        with pytest.raises(RuntimeError, match="injected competing interruption"):
            with original_transaction(*args, **competing_kwargs):
                raise RuntimeError("injected competing interruption")
        assert not outbox.exists()
        with original_transaction(*args, **kwargs) as persisted:
            assert persisted.materializing is True
            yield persisted

    def count_initialize(
        path: Path | None,
        *,
        source_history_required: bool = False,
        expected_source_binding: str | None = None,
    ) -> str:
        nonlocal initialized
        initialized += 1
        return original_initialize(
            path,
            source_history_required=source_history_required,
            expected_source_binding=expected_source_binding,
        )

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after a competing reservation")

    monkeypatch.setattr(
        store,
        "promotion_materialization_transaction",
        reserve_then_enter,
    )
    monkeypatch.setattr(
        materialization_module,
        "_initialize_materialization_receipt_source",
        count_initialize,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="owned materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert initialized == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


@pytest.mark.parametrize("failed_barrier", ("source_file", "marker_file", "directory"))
def test_receipt_source_durability_failure_refuses_before_hka_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_barrier: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "receipts" / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-{failed_barrier}-durability"),
        store=store,
        vault=vault,
    )
    marker_name = f".{outbox.name}.materialization-source"
    hka_calls = 0

    def fail_file_sync(path: Path) -> None:
        if failed_barrier == "source_file" and path.name == outbox.name:
            raise OSError("injected receipt source file fsync failure")
        if failed_barrier == "marker_file" and path.name == marker_name:
            raise OSError("injected receipt marker file fsync failure")

    def fail_directory_sync(path: Path) -> None:
        if failed_barrier == "directory":
            raise OSError("injected receipt source directory fsync failure")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after receipt source durability failure")

    monkeypatch.setattr(
        materialization_module,
        "_fsync_materialization_file",
        fail_file_sync,
        raising=False,
    )
    monkeypatch.setattr(
        materialization_module,
        "_fsync_materialization_directory",
        fail_directory_sync,
        raising=False,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source could not be initialized",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 0
    assert not list(vault_root.rglob("*.md"))
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is False


def test_receipt_source_alias_requires_canonical_parent_directory_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    alias_root = tmp_path / "aliases"
    alias_root.mkdir()
    canonical_anchor = tmp_path / "canonical-receipts"
    canonical_outbox = canonical_anchor / "nested" / "outbox.jsonl"
    outbox_alias = alias_root / "outbox.jsonl"
    outbox_alias.symlink_to(canonical_outbox)
    entry = _promoted(
        _candidate(candidate_id="candidate-canonical-directory-barrier"),
        store=store,
        vault=vault,
    )
    original_directory_sync = materialization_module._fsync_materialization_directory
    original_write = materialization_module.write_note_relative
    canonical_barrier_attempts = 0
    hka_calls = 0

    def fail_canonical_anchor_sync(path: Path) -> None:
        nonlocal canonical_barrier_attempts
        if path == canonical_anchor:
            canonical_barrier_attempts += 1
            raise OSError("injected canonical receipt directory fsync failure")
        original_directory_sync(path)

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_fsync_materialization_directory",
        fail_canonical_anchor_sync,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source could not be initialized",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox_alias,
        )

    assert canonical_barrier_attempts == 1
    assert hka_calls == 0
    assert not list(vault_root.rglob("*.md"))
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is False


def test_receipt_source_retry_reestablishes_parent_directory_durability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "receipts" / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-directory-durability-retry"),
        store=store,
        vault=vault,
    )
    original_directory_sync = materialization_module._fsync_materialization_directory
    original_write = materialization_module.write_note_relative
    parent_sync_attempts = 0

    def fail_first_parent_sync(path: Path) -> None:
        nonlocal parent_sync_attempts
        if path == tmp_path:
            parent_sync_attempts += 1
            if parent_sync_attempts == 1:
                raise OSError("injected parent directory fsync failure")
        original_directory_sync(path)

    def require_reestablished_parent_sync(*args: object, **kwargs: object) -> object:
        assert parent_sync_attempts >= 2
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_fsync_materialization_directory",
        fail_first_parent_sync,
    )
    monkeypatch.setattr(
        materialization_module,
        "write_note_relative",
        require_reestablished_parent_sync,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source could not be initialized",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert parent_sync_attempts >= 2
    assert result.status == "materialized"
    assert result.terminal is True


def test_first_attempt_refuses_if_source_disappears_during_reservation_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-reservation-gap"),
        store=store,
        vault=vault,
    )
    hka_calls = 0

    class CommitHookConnection(sqlite3.Connection):
        after_commit: object = None

        def commit(self) -> None:
            super().commit()
            callback = self.after_commit
            if callback is not None:
                self.after_commit = None
                assert callable(callback)
                callback()

    connection = sqlite3.connect(
        store.db_path,
        factory=CommitHookConnection,
    )
    connection.row_factory = sqlite3.Row

    def compete_then_lose_source() -> None:
        competing_store = ReviewDecisionStore(store.db_path)
        with pytest.raises(MemoryMaterializationError):
            materialize_promoted_memory(
                entry,
                vault_context=vault,
                channel="test",
                decision_store=competing_store,
                write_guard=_blocked_guard(),
                outbox_path=outbox,
            )
        outbox.unlink(missing_ok=True)

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after receipt history disappears")

    connection.after_commit = compete_then_lose_source
    monkeypatch.setattr(store, "_connect", lambda: connection)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="owned materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 0
    assert not outbox.exists()
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize("raw_reviewer", (None, 0))
def test_persisted_reviewer_must_remain_a_nonempty_string_before_governance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw_reviewer: object,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-malformed-persisted-reviewer"),
        store=store,
        vault=vault,
    )
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions"
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["decided_by"] = raw_reviewer
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ?",
            (json.dumps(payload),),
        )

    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not receive a malformed persisted reviewer")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with malformed reviewer authority")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="persisted review decision reviewer is invalid",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


@pytest.mark.parametrize("tamper", ("mirror_conflict", "duplicate_payload_key"))
def test_persisted_reviewer_authority_must_have_one_consistent_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-persisted-reviewer-{tamper}"),
        store=store,
        vault=vault,
    )
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions"
        ).fetchone()
        assert row is not None
        raw_payload = str(row[0])
        if tamper == "mirror_conflict":
            payload = json.loads(raw_payload)
            payload["decided_by"] = "other:reviewer"
            raw_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        else:
            authority = '\"decided_by\":\"companion-ui:reviewer\"'
            assert authority in raw_payload
            raw_payload = raw_payload.replace(
                authority,
                f'{authority},\"decided_by\":\"other:reviewer\"',
            )
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ?",
            (raw_payload,),
        )

    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not receive ambiguous reviewer authority")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with ambiguous reviewer authority")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="persisted review decision",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


def test_source_loss_after_preflight_refuses_before_governance_or_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-source-loss-after-preflight"),
        store=store,
        vault=vault,
    )
    original_find = materialization_module._find_materialized_note
    original_grant = materialization_module._materialization_grant
    gov_calls = 0
    hka_calls = 0

    def lose_source_after_discovery(*args: object, **kwargs: object) -> object:
        recovered = original_find(*args, **kwargs)
        outbox.unlink()
        return recovered

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        return original_grant(*args, **kwargs)

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after receipt history disappears")

    monkeypatch.setattr(
        materialization_module,
        "_find_materialized_note",
        lose_source_after_discovery,
    )
    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="owned materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


def test_new_candidate_cannot_recreate_lost_shared_receipt_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    first = _promoted(
        _candidate(candidate_id="aaaaaaaa-shared-source", title="First memory"),
        store=store,
        vault=vault,
    )
    first_result = materialize_promoted_memory(
        first,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )
    assert first_result.terminal is True
    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT,
    ]
    outbox.unlink()

    second = _promoted(
        _candidate(candidate_id="bbbbbbbb-shared-source", title="Second memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run after shared receipt history disappears")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after shared receipt history disappears")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="shared materialization receipt history is unavailable",
    ):
        materialize_promoted_memory(
            second,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert len(list(vault_root.rglob("*.md"))) == 1


def test_pre_marker_historical_promotion_refuses_empty_source_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(candidate_id="aaaaaaaa-pre-marker-history", title="Historical memory"),
        store=store,
        vault=vault,
    )
    store.mark_terminal(
        historical.candidate_id,
        vault_context=vault,
        channel="test",
        expected_outcome=ReviewDecision.PROMOTE,
    )
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    entry = _promoted(
        _candidate(candidate_id="bbbbbbbb-after-upgrade", title="New memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run without historical receipt evidence")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run without historical receipt evidence")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


def test_pre_marker_historical_promotion_refuses_foreign_nonempty_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(candidate_id="aaaaaaaa-pre-marker-foreign", title="Historical memory"),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        historical,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True

    foreign_vault = VaultContext(
        status="selected",
        active_vault_id="vault-foreign",
        active_vault_name="Foreign Vault",
        active_vault_path=str(tmp_path / "foreign-vault"),
    )
    Path(foreign_vault.active_vault_path).mkdir()
    foreign_store = ReviewDecisionStore(tmp_path / "foreign-review-decisions.sqlite3")
    foreign_outbox = tmp_path / "foreign-outbox.jsonl"
    foreign = _promoted(
        _candidate(candidate_id="foreign-materialization", title="Foreign memory"),
        store=foreign_store,
        vault=foreign_vault,
    )
    assert materialize_promoted_memory(
        foreign,
        vault_context=foreign_vault,
        channel="test",
        decision_store=foreign_store,
        write_guard=_allowing_guard(),
        outbox_path=foreign_outbox,
    ).terminal is True

    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        legacy_payload.pop("materialization_source_binding")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    materialization_module._materialization_source_marker_path(outbox).unlink()
    outbox.write_bytes(foreign_outbox.read_bytes())

    entry = _promoted(
        _candidate(candidate_id="bbbbbbbb-after-foreign-source", title="New memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run with foreign historical receipt evidence")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with foreign historical receipt evidence")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source continuity is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert len(list(vault_root.rglob("*.md"))) == 1


def test_pre_marker_history_refuses_db_receipts_masking_lost_owned_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(candidate_id="aaaaaaaa-db-mask", title="Historical memory"),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        historical,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True
    historical_records = _outbox_records(outbox)

    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        legacy_payload.pop("materialization_source_binding")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    materialization_module._materialization_source_marker_path(outbox).unlink()
    outbox.write_text(
        json.dumps(
            {
                "event": "unrelated.event",
                "event_id": "unrelated-owned-jsonl-record",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(outbox_sources_module, "_db_outbox_configured", lambda: True)
    monkeypatch.setattr(
        outbox_sources_module,
        "_read_db_outbox_records",
        lambda: historical_records,
    )

    @contextmanager
    def open_db_records():
        yield iter(historical_records)

    monkeypatch.setattr(
        outbox_sources_module,
        "_open_db_outbox_records",
        open_db_records,
    )

    entry = _promoted(
        _candidate(candidate_id="bbbbbbbb-after-db-mask", title="New memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run when DB masks lost owned JSONL history")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run when DB masks lost owned JSONL history")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source continuity is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert len(list(vault_root.rglob("*.md"))) == 1


def test_pre_marker_history_refuses_skeletal_owned_jsonl_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(candidate_id="aaaaaaaa-skeletal", title="Historical memory"),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        historical,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True
    promotion = _outbox_records(outbox)[0]
    promotion_payload = promotion["payload"]
    assert isinstance(promotion_payload, dict)

    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        legacy_payload.pop("materialization_source_binding")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    materialization_module._materialization_source_marker_path(outbox).unlink()
    skeletal = {
        "event": promotion["event"],
        "event_id": promotion["event_id"],
        "payload": {
            "receipt_id": promotion_payload["receipt_id"],
            "vault_id": promotion_payload["vault_id"],
            "channel": promotion_payload["channel"],
            "transition_family": promotion_payload["transition_family"],
            "basis": {"candidate_id": historical.candidate_id},
            "artifact_linkage": {"candidate_id": historical.candidate_id},
            "outcome": {"status": "applied"},
        },
    }
    outbox.write_text(json.dumps(skeletal) + "\n", encoding="utf-8")

    entry = _promoted(
        _candidate(candidate_id="bbbbbbbb-after-skeletal", title="New memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run with skeletal historical evidence")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with skeletal historical evidence")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source continuity is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert len(list(vault_root.rglob("*.md"))) == 1


def _assert_pre_marker_history_refuses_hidden_promotion_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    conflict_shape: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(
            candidate_id=f"aaaaaaaa-hidden-{conflict_shape}",
            title="Historical memory",
        ),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        historical,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True
    records = _outbox_records(outbox)
    promotion = records[0]
    duplicate = json.loads(json.dumps(promotion))
    duplicate_payload = duplicate["payload"]
    assert isinstance(duplicate_payload, dict)
    duplicate["event_id"] = "foreign-promotion-event-id"
    duplicate_payload["receipt_id"] = "foreign-promotion-receipt-id"
    if conflict_shape == "governed_identity":
        duplicate["event"] = "foreign.promotion.event"
        duplicate_payload["outcome"] = {"status": "failed"}
    else:
        assert conflict_shape == "candidate_source"
        duplicate_payload.pop("policy_decision")
        duplicate_payload.pop("decision_token")
    records.append(duplicate)

    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        legacy_payload.pop("materialization_source_binding")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    materialization_module._materialization_source_marker_path(outbox).unlink()
    outbox.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )

    entry = _promoted(
        _candidate(
            candidate_id=f"bbbbbbbb-after-hidden-{conflict_shape}",
            title="New memory",
        ),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run with conflicting historical evidence")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with conflicting historical evidence")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source continuity is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert len(list(vault_root.rglob("*.md"))) == 1


def test_pre_marker_history_refuses_hidden_governed_promotion_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_pre_marker_history_refuses_hidden_promotion_conflict(
        tmp_path,
        monkeypatch,
        conflict_shape="governed_identity",
    )


def test_pre_marker_history_refuses_hidden_candidate_source_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_pre_marker_history_refuses_hidden_promotion_conflict(
        tmp_path,
        monkeypatch,
        conflict_shape="candidate_source",
    )


def test_pre_marker_historical_promotion_backfills_exact_owned_source(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(candidate_id="aaaaaaaa-pre-marker-owned", title="Historical memory"),
        store=store,
        vault=vault,
    )
    historical_result = materialize_promoted_memory(
        historical,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )
    assert historical_result.terminal is True

    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        legacy_payload.pop("materialization_source_binding")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    materialization_module._materialization_source_marker_path(outbox).unlink()

    entry = _promoted(
        _candidate(candidate_id="bbbbbbbb-after-owned-source", title="New memory"),
        store=store,
        vault=vault,
    )
    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.terminal is True
    assert len(list(vault_root.rglob("*.md"))) == 2
    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT,
        "promotion.transition.applied",
        materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT,
    ]
    assert materialization_module._materialization_source_marker_path(outbox).is_file()


def test_missing_marker_with_persisted_source_binding_refuses_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(candidate_id="aaaaaaaa-bound-source", title="Bound history"),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        historical,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True
    persisted = store.get_decision(
        historical.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.materialization_source_binding is not None
    marker = materialization_module._materialization_source_marker_path(outbox)
    marker.unlink()

    entry = _promoted(
        _candidate(candidate_id="bbbbbbbb-after-marker-loss", title="New memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run after a persisted marker disappears")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after a persisted marker disappears")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="persisted materialization receipt source continuity marker is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not marker.exists()
    assert len(list(vault_root.rglob("*.md"))) == 1


@pytest.mark.parametrize("locator_vault_shape", ("foreign", "padded"))
def test_pre_marker_migration_refuses_mismatched_hka_locator_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locator_vault_shape: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(
            candidate_id=f"aaaaaaaa-pre-marker-locator-{locator_vault_shape}",
            title="Historical memory",
        ),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        historical,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True

    records = _outbox_records(outbox)
    promotion_payload = records[0]["payload"]
    assert isinstance(promotion_payload, dict)
    mutation_receipt = promotion_payload["state_owner_receipt"]
    assert isinstance(mutation_receipt, dict)
    locator = mutation_receipt["locator"]
    assert isinstance(locator, dict)
    produced_vault = locator["vault"]
    assert isinstance(produced_vault, str)
    locator["vault"] = (
        "foreign-vault"
        if locator_vault_shape == "foreign"
        else f" {produced_vault} "
    )
    outbox.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )

    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        legacy_payload.pop("materialization_source_binding")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    materialization_module._materialization_source_marker_path(outbox).unlink()

    entry = _promoted(
        _candidate(
            candidate_id=f"bbbbbbbb-after-locator-{locator_vault_shape}",
            title="New memory",
        ),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run with malformed historical HKA identity")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with malformed historical HKA identity")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source continuity is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert len(list(vault_root.rglob("*.md"))) == 1


@pytest.mark.parametrize("attack", ("truncate", "retarget_alias"))
def test_receipt_source_continuity_refuses_truncation_or_retargeting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    canonical_outbox = tmp_path / "canonical-outbox.jsonl"
    outbox = tmp_path / "outbox-alias.jsonl"
    outbox.symlink_to(canonical_outbox)
    first = _promoted(
        _candidate(candidate_id="aaaaaaaa-continuity", title="First continuity memory"),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        first,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True

    if attack == "truncate":
        canonical_outbox.write_text("", encoding="utf-8")
    else:
        replacement = tmp_path / "replacement-outbox.jsonl"
        replacement.write_text("", encoding="utf-8")
        outbox.unlink()
        outbox.symlink_to(replacement)

    second = _promoted(
        _candidate(candidate_id=f"bbbbbbbb-{attack}", title="Second continuity memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run after receipt history loses continuity")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after receipt history loses continuity")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(MemoryMaterializationError, match="receipt source.*continuity"):
        materialize_promoted_memory(
            second,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        second.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is False


def test_receipt_source_binding_refuses_another_valid_marked_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_a = _vault(tmp_path / "vault-a")
    Path(vault_a.active_vault_path).mkdir()
    store_a = ReviewDecisionStore(tmp_path / "review-decisions-a.sqlite3")
    sink_a = tmp_path / "sink-a.jsonl"
    alias = tmp_path / "active-source.jsonl"
    alias.symlink_to(sink_a)
    first_a = _promoted(
        _candidate(candidate_id="aaaaaaaa-source-a", title="Source A history"),
        store=store_a,
        vault=vault_a,
    )
    first_result = materialize_promoted_memory(
        first_a,
        vault_context=vault_a,
        channel="test",
        decision_store=store_a,
        write_guard=_allowing_guard(),
        outbox_path=alias,
    )

    vault_b = VaultContext(
        status="selected",
        active_vault_id="vault-b",
        active_vault_name="Vault B",
        active_vault_path=str(tmp_path / "vault-b"),
    )
    Path(vault_b.active_vault_path).mkdir()
    store_b = ReviewDecisionStore(tmp_path / "review-decisions-b.sqlite3")
    sink_b = tmp_path / "sink-b.jsonl"
    first_b = _promoted(
        _candidate(candidate_id="bbbbbbbb-source-b", title="Source B history"),
        store=store_b,
        vault=vault_b,
    )
    assert materialize_promoted_memory(
        first_b,
        vault_context=vault_b,
        channel="test",
        decision_store=store_b,
        write_guard=_allowing_guard(),
        outbox_path=sink_b,
    ).terminal is True

    alias.unlink()
    alias.symlink_to(sink_b)
    second_a = _promoted(
        _candidate(candidate_id="cccccccc-source-a", title="Second source A memory"),
        store=store_a,
        vault=vault_a,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run after valid-source retargeting")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after valid-source retargeting")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(MemoryMaterializationError, match="receipt source.*binding"):
        materialize_promoted_memory(
            second_a,
            vault_context=vault_a,
            channel="test",
            decision_store=store_a,
            write_guard=_allowing_guard(),
            outbox_path=alias,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    active_ids = {record["event_id"] for record in _outbox_records(alias)}
    assert first_result.receipt_id not in active_ids


def test_terminal_guard_refuses_changed_committed_receipt_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    first = _promoted(
        _candidate(candidate_id="aaaaaaaa-committed-prefix", title="Committed history"),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        first,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True
    second = _promoted(
        _candidate(candidate_id="bbbbbbbb-committed-prefix", title="New history"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def corrupt_committed_prefix(*args: object, **kwargs: object) -> object:
        authority_receipt = original_ensure(*args, **kwargs)
        records = _outbox_records(outbox)
        records[0]["timestamp"] = "2000-01-01T00:00:00Z"
        outbox.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        return authority_receipt

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        corrupt_committed_prefix,
    )

    with pytest.raises(MemoryMaterializationError, match="receipt source continuity"):
        materialize_promoted_memory(
            second,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    persisted = store.get_decision(
        second.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize("record_index", (0, 1), ids=("promotion", "authority"))
def test_terminal_guard_refuses_singleton_receipt_with_conflicting_event_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_index: int,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(
            candidate_id=f"candidate-conflicting-envelope-{record_index}",
            title="Conflicting envelope",
        ),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt
    original_write = materialization_module.write_note_relative
    hka_calls = 0

    def inject_conflicting_alias(*args: object, **kwargs: object) -> object:
        authority_receipt = original_ensure(*args, **kwargs)
        records = _outbox_records(outbox)
        assert len(records) == 2
        records[record_index]["event_type"] = "foreign.event"
        _rewrite_outbox_preserving_source_binding(
            outbox,
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        )
        return authority_receipt

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        inject_conflicting_alias,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source is unavailable during reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 1
    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_terminal_guard_refuses_changed_uncommitted_authority_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-uncommitted-authority-tail"),
        store=store,
        vault=vault,
    )
    original_marker_write = materialization_module._write_materialization_source_marker

    def fail_authority_marker(path: Path, *args: object, **kwargs: object) -> object:
        if path.exists() and len(path.read_text(encoding="utf-8").splitlines()) == 2:
            raise OSError("injected AuthorityReceipt marker failure")
        return original_marker_write(path, *args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_write_materialization_source_marker",
        fail_authority_marker,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        "governance.authority_receipt.recorded",
    ]
    corrupted = False

    def corrupt_authority_tail(path: Path, *args: object, **kwargs: object) -> object:
        nonlocal corrupted
        if not corrupted:
            raw = path.read_bytes()
            changed = raw.replace(b'"state_owner": "HKA"', b'"state_owner": "BAD"', 1)
            assert changed != raw
            with path.open("r+b") as handle:
                handle.write(changed)
                handle.flush()
                os.fsync(handle.fileno())
            corrupted = True
        return original_marker_write(path, *args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_write_materialization_source_marker",
        corrupt_authority_tail,
    )
    with pytest.raises(MemoryMaterializationError):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert corrupted is True
    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_terminal_guard_refuses_receipt_source_replacement_during_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    first = _promoted(
        _candidate(candidate_id="aaaaaaaa-terminal-snapshot", title="First history"),
        store=store,
        vault=vault,
    )
    assert materialize_promoted_memory(
        first,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    ).terminal is True
    second = _promoted(
        _candidate(candidate_id="bbbbbbbb-terminal-snapshot", title="Second history"),
        store=store,
        vault=vault,
    )
    original_read = materialization_module.read_receipt_source_snapshot
    replaced = False

    def replace_during_terminal_snapshot(*args: object, **kwargs: object):
        nonlocal replaced
        caller = inspect.currentframe()
        caller_name = caller.f_back.f_code.co_name if caller and caller.f_back else ""
        if not replaced and caller_name == "_materialization_terminal_guard":
            records = _outbox_records(outbox)
            replacement = tmp_path / "replacement.jsonl"
            replacement.write_text(
                "".join(
                    json.dumps(record, sort_keys=True) + "\n"
                    for record in records[-2:]
                ),
                encoding="utf-8",
            )
            os.replace(replacement, outbox)
            replaced = True
        return original_read(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "read_receipt_source_snapshot",
        replace_during_terminal_snapshot,
    )

    with pytest.raises(MemoryMaterializationError, match="receipt source continuity"):
        materialize_promoted_memory(
            second,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert replaced is True
    persisted = store.get_decision(
        second.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_retry_refuses_nonboolean_materializing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-nonboolean-materializing"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_materialization_authority_receipt
    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected interruption before AuthorityReceipt")
        ),
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )
    monkeypatch.setattr(
        materialization_module,
        "_append_materialization_authority_receipt",
        original_append,
    )
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions"
        ).fetchone()
        assert row is not None
        payload = json.loads(str(row[0]))
        payload["materializing"] = 1
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ?",
            (json.dumps(payload, sort_keys=True),),
        )

    monkeypatch.setattr(
        materialization_module,
        "write_note_relative",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("HKA must not run from malformed reservation state")
        ),
    )
    with pytest.raises(MemoryMaterializationError, match="materializing.*invalid"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    with sqlite3.connect(store.db_path) as connection:
        terminal = connection.execute(
            "SELECT terminal FROM agent_memory_review_decisions"
        ).fetchone()
    assert terminal == (0,)


@pytest.mark.parametrize("reservation_state", ("missing", "false"))
def test_bound_reservation_requires_active_materializing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reservation_state: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review-decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-bound-{reservation_state}"),
        store=store,
        vault=vault,
    )
    original_grant = materialization_module._materialization_grant
    monkeypatch.setattr(
        materialization_module,
        "_materialization_grant",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected interruption after source reservation")
        ),
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.materializing is True
    assert persisted.materialization_source_binding is not None

    outbox.unlink()
    materialization_module._materialization_source_marker_path(outbox).unlink()
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions"
        ).fetchone()
        assert row is not None
        payload = json.loads(str(row[0]))
        if reservation_state == "missing":
            payload.pop("materializing")
        else:
            payload["materializing"] = False
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ?",
            (json.dumps(payload, sort_keys=True),),
        )

    original_initialize = (
        materialization_module._initialize_materialization_receipt_source
    )
    initialize_calls = 0
    gov_calls = 0
    hka_calls = 0

    def count_initialize(*args: object, **kwargs: object) -> str:
        nonlocal initialize_calls
        initialize_calls += 1
        return original_initialize(*args, **kwargs)

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        return original_grant(*args, **kwargs)

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run from an inconsistent reservation")

    monkeypatch.setattr(
        materialization_module,
        "_initialize_materialization_receipt_source",
        count_initialize,
    )
    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="materialization reservation state is inconsistent",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert initialize_calls == 0
    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


def test_pre_marker_in_progress_promotion_refuses_empty_source_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    interrupted = _promoted(
        _candidate(candidate_id="aaaaaaaa-in-progress-history", title="Interrupted memory"),
        store=store,
        vault=vault,
    )
    with pytest.raises(RuntimeError, match="pre-marker interruption"):
        with store.promotion_materialization_transaction(
            interrupted.candidate_id,
            vault_context=vault,
            channel="test",
            expected_scope_id="scope:test/materialization",
            expected_candidate_digest=materialization_module.review_candidate_digest(
                interrupted
            ),
        ):
            raise RuntimeError("pre-marker interruption")
    persisted_interruption = store.get_decision(
        interrupted.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted_interruption is not None
    assert persisted_interruption.materializing is True
    assert persisted_interruption.terminal is False
    assert not outbox.exists()

    entry = _promoted(
        _candidate(candidate_id="bbbbbbbb-after-interruption", title="New memory"),
        store=store,
        vault=vault,
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run without in-progress receipt history")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run without in-progress receipt history")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


def test_pre_marker_legacy_promotion_in_another_channel_refuses_empty_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    historical = _promoted(
        _candidate(
            candidate_id="aaaaaaaa-cross-channel-legacy",
            title="Historical dev memory",
        ),
        store=store,
        vault=vault,
        channel="dev",
    )
    store.mark_terminal(
        historical.candidate_id,
        vault_context=vault,
        channel="dev",
        expected_outcome=ReviewDecision.PROMOTE,
    )
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT payload FROM agent_memory_review_decisions WHERE candidate_id = ?",
            (historical.candidate_id,),
        ).fetchone()
        assert row is not None
        legacy_payload = json.loads(row[0])
        legacy_payload.pop("memory_type")
        connection.execute(
            "UPDATE agent_memory_review_decisions SET payload = ? WHERE candidate_id = ?",
            (json.dumps(legacy_payload), historical.candidate_id),
        )
    entry = _promoted(
        _candidate(
            candidate_id="bbbbbbbb-cross-channel-new",
            title="New test memory",
        ),
        store=store,
        vault=vault,
        channel="test",
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run without cross-channel history")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run without cross-channel history")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


def test_pre_marker_in_progress_promotion_in_another_channel_refuses_empty_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    interrupted = _promoted(
        _candidate(
            candidate_id="aaaaaaaa-cross-channel-in-progress",
            title="Interrupted dev memory",
        ),
        store=store,
        vault=vault,
        channel="dev",
    )
    with pytest.raises(RuntimeError, match="pre-marker interruption"):
        with store.promotion_materialization_transaction(
            interrupted.candidate_id,
            vault_context=vault,
            channel="dev",
            expected_scope_id="scope:test/materialization",
            expected_candidate_digest=materialization_module.review_candidate_digest(
                interrupted
            ),
        ):
            raise RuntimeError("pre-marker interruption")

    entry = _promoted(
        _candidate(
            candidate_id="bbbbbbbb-cross-channel-after-interruption",
            title="New test memory",
        ),
        store=store,
        vault=vault,
        channel="test",
    )
    gov_calls = 0
    hka_calls = 0

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        raise AssertionError("GOV must not run without cross-channel history")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run without cross-channel history")

    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="historical materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not outbox.exists()
    assert not list(vault_root.rglob("*.md"))


def test_shared_source_distinguishes_same_candidate_across_vaults(
    tmp_path: Path,
) -> None:
    vault_a = _vault(tmp_path / "vault-a")
    vault_b = VaultContext(
        status="selected",
        active_vault_id="vault-b",
        active_vault_name="Vault B",
        active_vault_path=str(tmp_path / "vault-b"),
    )
    Path(vault_a.active_vault_path).mkdir()
    Path(vault_b.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(candidate_id="candidate-shared-source-two-vaults")

    entry_a = _promoted(candidate, store=store, vault=vault_a, channel="test")
    result_a = materialize_promoted_memory(
        entry_a,
        vault_context=vault_a,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )
    entry_b = _promoted(candidate, store=store, vault=vault_b, channel="test")
    result_b = materialize_promoted_memory(
        entry_b,
        vault_context=vault_b,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result_a.terminal is True
    assert result_b.terminal is True
    assert result_a.receipt_id != result_b.receipt_id
    assert len(list(Path(vault_a.active_vault_path).rglob("*.md"))) == 1
    assert len(list(Path(vault_b.active_vault_path).rglob("*.md"))) == 1
    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT,
        "promotion.transition.applied",
        materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT,
    ]


def test_non_semantic_promotion_does_not_block_first_semantic_source(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    preference = _promoted(
        _candidate(
            candidate_id="aaaaaaaa-preference-before-semantic",
            memory_type=MemoryType.PREFERENCE_MEMORY,
            title="Preference memory",
        ),
        store=store,
        vault=vault,
    )
    preference_result = materialize_promoted_memory(
        preference,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )
    assert preference_result.status == "not_semantic"
    assert not outbox.exists()

    semantic = _promoted(
        _candidate(
            candidate_id="bbbbbbbb-first-semantic",
            title="First semantic memory",
        ),
        store=store,
        vault=vault,
    )
    semantic_result = materialize_promoted_memory(
        semantic,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert semantic_result.status == "materialized"
    assert semantic_result.terminal is True
    assert semantic_result.artifact_path is not None
    assert (vault_root / semantic_result.artifact_path).is_file()
    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT,
    ]


def test_late_promotion_identity_occupancy_refuses_before_governance_or_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-promotion-occupancy"),
        store=store,
        vault=vault,
    )
    receipt_id = materialization_module._stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault,
        channel="test",
    )
    original_find = materialization_module._find_materialized_note
    original_grant = materialization_module._materialization_grant
    gov_calls = 0
    hka_calls = 0

    def occupy_identity_after_recovery(*args: object, **kwargs: object) -> object:
        recovered = original_find(*args, **kwargs)
        with outbox.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event": "promotion.transition.applied",
                        "event_id": receipt_id,
                        "payload": {
                            "receipt_id": receipt_id,
                            "outcome": "malformed",
                        },
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        return recovered

    def count_gov(*args: object, **kwargs: object) -> object:
        nonlocal gov_calls
        gov_calls += 1
        return original_grant(*args, **kwargs)

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after its receipt identity is occupied")

    monkeypatch.setattr(
        materialization_module,
        "_find_materialized_note",
        occupy_identity_after_recovery,
    )
    monkeypatch.setattr(materialization_module, "_materialization_grant", count_gov)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt identity changed during pre-mutation reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert gov_calls == 0
    assert hka_calls == 0
    assert not list(vault_root.rglob("*.md"))
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize(
    "malformation",
    (
        "missing_contract_version",
        "integer_fallback_used",
        "foreign_outer_trace",
        "foreign_outer_source",
        "malformed_outer_timestamp",
        "missing_outer_event_id",
        "foreign_outer_event_id",
        "integer_outer_event_id",
    ),
)
def test_retry_refuses_malformed_persisted_authority_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-authority-{malformation}"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def interrupt_after_authority_receipt(*args: object, **kwargs: object) -> None:
        original_ensure(*args, **kwargs)
        raise OSError("injected interruption after AuthorityReceipt persistence")

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        interrupt_after_authority_receipt,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    records = _outbox_records(outbox)
    assert len(records) == 2
    authority_payload = records[1]["payload"]
    assert isinstance(authority_payload, dict)
    authority = authority_payload["authority_receipt"]
    assert isinstance(authority, dict)
    authority_record = records[1]
    if malformation == "missing_contract_version":
        authority.pop("contract_version")
    elif malformation == "integer_fallback_used":
        authority["fallback_used"] = 0
    elif malformation == "foreign_outer_trace":
        authority_record["trace_id"] = "foreign-trace"
    elif malformation == "foreign_outer_source":
        authority_record["source"] = "foreign-writer"
    elif malformation == "missing_outer_event_id":
        authority_record.pop("event_id")
    elif malformation == "foreign_outer_event_id":
        authority_record["event_id"] = "foreign-event-id"
    elif malformation == "integer_outer_event_id":
        authority_record["event_id"] = 0
    else:
        authority_record["timestamp"] = {"invalid": "timestamp"}
    _rewrite_outbox_preserving_source_binding(
        outbox,
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
    )
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        original_ensure,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="memory AuthorityReceipt event is invalid",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    assert _outbox_events(outbox) == [
        "promotion.transition.applied",
        "governance.authority_receipt.recorded",
    ]
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize(
    "duplicate_key_case",
    (
        "decision_token",
        "authority_receipt",
        "stringified_decision_token",
        "db_decision_token",
        "db_authority_receipt",
    ),
)
def test_retry_refuses_duplicate_authority_keys_without_repeating_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duplicate_key_case: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-duplicate-key-{duplicate_key_case}"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt
    original_write = materialization_module.write_note_relative
    original_decoder = outbox_module.loads_json_without_duplicate_keys
    decoder_calls = 0
    hka_calls = 0

    def count_decoder(raw: str | bytes | bytearray) -> object:
        nonlocal decoder_calls
        decoder_calls += 1
        return original_decoder(raw)

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    def interrupt_after_authority_receipt(*args: object, **kwargs: object) -> None:
        original_ensure(*args, **kwargs)
        raise OSError("injected interruption after AuthorityReceipt persistence")

    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)
    monkeypatch.setattr(
        outbox_module,
        "loads_json_without_duplicate_keys",
        count_decoder,
    )
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        interrupt_after_authority_receipt,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    records = _outbox_records(outbox)
    assert len(records) == 2
    raw_records = [json.dumps(record, sort_keys=True) for record in records]
    db_raw_record: str | None = None
    if duplicate_key_case == "decision_token":
        raw_records[0] = raw_records[0].replace(
            '"valid": true',
            '"valid": false, "valid": true',
            1,
        )
    elif duplicate_key_case == "authority_receipt":
        raw_records[1] = raw_records[1].replace(
            '"fallback_used": false',
            '"fallback_used": true, "fallback_used": false',
            1,
        )
    else:
        payload = records[0]["payload"]
        assert isinstance(payload, dict)
        raw_payload = json.dumps(payload, sort_keys=True).replace(
            '"valid": true',
            '"valid": false, "valid": true',
            1,
        )
        stringified = dict(records[0])
        stringified["payload"] = raw_payload
        raw_records[0] = json.dumps(stringified, sort_keys=True)
    if duplicate_key_case.startswith("db_"):
        db_record_index = 0 if duplicate_key_case == "db_decision_token" else 1
        needle = (
            '"valid": true'
            if duplicate_key_case == "db_decision_token"
            else '"fallback_used": false'
        )
        replacement = (
            '"valid": false, "valid": true'
            if duplicate_key_case == "db_decision_token"
            else '"fallback_used": true, "fallback_used": false'
        )
        encoded = json.dumps(records[db_record_index], sort_keys=True)
        db_raw_record = encoded.replace(needle, replacement, 1)
        assert db_raw_record != encoded

        class RawDbCursor:
            def __init__(self) -> None:
                self._returned = False

            def fetchmany(self, _size: int) -> list[tuple[object, ...]]:
                if self._returned:
                    return []
                self._returned = True
                return [
                    (
                        "db-duplicate-authority-row",
                        records[db_record_index]["event"],
                        db_raw_record,
                        None,
                    )
                ]

        @contextmanager
        def open_db_records():
            yield outbox_sources_module._iter_db_outbox_records(RawDbCursor())

        complementary_record = records[1 - db_record_index]

        def iter_complementary_jsonl(_path: Path):
            yield complementary_record

        monkeypatch.setattr(outbox_sources_module, "_db_outbox_configured", lambda: True)
        monkeypatch.setattr(
            outbox_sources_module,
            "_open_db_outbox_records",
            open_db_records,
        )
        monkeypatch.setattr(
            outbox_sources_module,
            "_read_jsonl_outbox_records",
            lambda **_kwargs: [complementary_record],
        )
        monkeypatch.setattr(
            outbox_module,
            "iter_jsonl_outbox_records",
            iter_complementary_jsonl,
        )
        corrupt_history = outbox.read_text(encoding="utf-8")
    else:
        corrupt_history = "\n".join(raw_records) + "\n"
        _rewrite_outbox_preserving_source_binding(outbox, corrupt_history)
    note = next(vault_root.rglob("*.md"))
    note_body = note.read_text(encoding="utf-8")
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        original_ensure,
    )

    with pytest.raises(MemoryMaterializationError):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 1
    assert decoder_calls > 0
    assert outbox.read_text(encoding="utf-8") == corrupt_history
    assert note.read_text(encoding="utf-8") == note_body
    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize("outer_event_id", (None, "foreign-event-id", 0))
def test_linked_authority_identity_conflict_refuses_before_hka_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outer_event_id: object,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-linked-authority-{outer_event_id}"),
        store=store,
        vault=vault,
    )
    receipt_id = materialization_module._stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault,
        channel="test",
    )
    authority_record: dict[str, object] = {
        "event": "governance.authority_receipt.recorded",
        "payload": {
            "materialization_id": receipt_id,
            "promotion_receipt_id": receipt_id,
            "candidate_id": entry.candidate_id,
            "authority_receipt": {},
        },
    }
    if outer_event_id is not None:
        authority_record["event_id"] = outer_event_id
    outbox.write_text(json.dumps(authority_record) + "\n", encoding="utf-8")
    original_write = materialization_module.write_note_relative
    writes = 0

    def count_write(*args: object, **kwargs: object) -> object:
        nonlocal writes
        writes += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(materialization_module, "write_note_relative", count_write)
    with pytest.raises(MemoryMaterializationError, match="AuthorityReceipt"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert writes == 0
    assert not list(vault_root.rglob("*.md"))
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False


@pytest.mark.parametrize(
    "receipt_class",
    ("promotion_source", "promotion_governed", "authority_effect", "authority_governed"),
)
def test_stable_secondary_receipt_identity_conflict_refuses_before_hka_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_class: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-stable-{receipt_class}-identity"),
        store=store,
        vault=vault,
    )
    receipt_id = materialization_module._stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault,
        channel="test",
    )
    source_event = f"memory-promote:{entry.candidate_id}"
    artifact_path = materialization_module._unique_memory_path(
        vault_root=vault_root,
        memory_dir=materialization_module.DEFAULT_MEMORY_DIR,
        title=entry.title,
        candidate_id=entry.candidate_id,
    )
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    decision_id, token_id = materialization_module._materialization_governed_ids(
        receipt_id=receipt_id,
        persisted=persisted,
        artifact_path=artifact_path,
    )
    if receipt_class.startswith("promotion"):
        record: dict[str, object] = {
            "event": "promotion.transition.applied",
            "event_id": "foreign-promotion-id",
            "payload": {
                "receipt_id": "foreign-promotion-id",
                "intent_event_id": (
                    source_event if receipt_class == "promotion_source" else "foreign-source"
                ),
                "source_event": (
                    source_event if receipt_class == "promotion_source" else "foreign-source"
                ),
                "vault_id": "vault-a",
                "channel": "test",
                "transition_family": "agent_memory_materialization",
                "outcome": {"status": "applied", "review_state": "rejected"},
                "basis": {
                    "source_event": (
                        source_event
                        if receipt_class == "promotion_source"
                        else "foreign-source"
                    ),
                    "candidate_id": entry.candidate_id,
                },
                "policy_decision": {
                    "decision_id": (
                        decision_id
                        if receipt_class == "promotion_governed"
                        else "foreign-decision-id"
                    )
                },
                "decision_token": {
                    "token_id": (
                        token_id
                        if receipt_class == "promotion_governed"
                        else "foreign-token-id"
                    ),
                    "decision_id": (
                        decision_id
                        if receipt_class == "promotion_governed"
                        else "foreign-decision-id"
                    ),
                },
            },
        }
    else:
        record = {
            "event": "governance.authority_receipt.recorded",
            "event_id": "foreign-authority-event-id",
            "payload": {
                "materialization_id": "foreign-materialization-id",
                "promotion_receipt_id": "foreign-promotion-id",
                "candidate_id": entry.candidate_id,
                "authority_receipt": {
                    "receipt_id": "foreign-authority-receipt-id",
                    "effect_id": (
                        receipt_id
                        if receipt_class == "authority_effect"
                        else "foreign-effect-id"
                    ),
                    "decision_id": (
                        decision_id
                        if receipt_class == "authority_governed"
                        else "foreign-decision-id"
                    ),
                    "decision_token_id": (
                        token_id
                        if receipt_class == "authority_governed"
                        else "foreign-token-id"
                    ),
                    "outcome": "failed",
                },
            },
        }
    outbox.write_text(json.dumps(record) + "\n", encoding="utf-8")
    hka_calls = 0

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run after stable receipt identity conflict")

    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(MemoryMaterializationError, match="receipt identity|AuthorityReceipt"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 0
    assert not list(vault_root.rglob("*.md"))
    persisted_after = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted_after is not None
    assert persisted_after.terminal is False


@pytest.mark.parametrize("outer_event_id", (None, "foreign-event-id", 0))
def test_embedded_authority_identity_conflict_refuses_before_hka_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outer_event_id: object,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-embedded-authority-{outer_event_id}"),
        store=store,
        vault=vault,
    )
    receipt_id = materialization_module._stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault,
        channel="test",
    )
    authority_receipt_id = "authority_receipt_" + hashlib.sha256(
        (
            materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT
            + "\x00"
            + receipt_id
        ).encode("utf-8")
    ).hexdigest()
    authority_record: dict[str, object] = {
        "event": "governance.authority_receipt.recorded",
        "payload": {
            "candidate_id": entry.candidate_id,
            "authority_receipt": {"receipt_id": authority_receipt_id},
        },
    }
    if outer_event_id is not None:
        authority_record["event_id"] = outer_event_id
    outbox.write_text(json.dumps(authority_record) + "\n", encoding="utf-8")
    original_write = materialization_module.write_note_relative
    writes = 0

    def count_write(*args: object, **kwargs: object) -> object:
        nonlocal writes
        writes += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(materialization_module, "write_note_relative", count_write)
    with pytest.raises(MemoryMaterializationError, match="AuthorityReceipt"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert writes == 0
    assert not list(vault_root.rglob("*.md"))
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False


@pytest.mark.parametrize("outer_event_id", (None, "foreign-event-id", 0))
def test_retry_refuses_hidden_linked_promotion_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outer_event_id: object,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-hidden-promotion-{outer_event_id}"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def interrupt_after_authority_receipt(*args: object, **kwargs: object) -> None:
        original_ensure(*args, **kwargs)
        raise OSError("injected interruption after AuthorityReceipt persistence")

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        interrupt_after_authority_receipt,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    records = _outbox_records(outbox)
    assert len(records) == 2
    duplicate = json.loads(json.dumps(records[0]))
    if outer_event_id is None:
        duplicate.pop("event_id")
    else:
        duplicate["event_id"] = outer_event_id
    duplicate["payload"]["outcome"] = "not-an-outcome-object"
    records.append(duplicate)
    _rewrite_outbox_preserving_source_binding(
        outbox,
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
    )
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        original_ensure,
    )

    with pytest.raises(MemoryMaterializationError, match="promotion"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize("injection_phase", ("pre_hka", "final_reconciliation"))
@pytest.mark.parametrize("conflict_shape", ("failed", "wrong_event"))
def test_governed_promotion_identity_conflict_always_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    injection_phase: str,
    conflict_shape: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(
            candidate_id=f"candidate-governed-conflict-{injection_phase}-{conflict_shape}"
        ),
        store=store,
        vault=vault,
    )
    receipt_id = materialization_module._stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault,
        channel="test",
    )
    artifact_path = materialization_module._unique_memory_path(
        vault_root=vault_root,
        memory_dir=materialization_module.DEFAULT_MEMORY_DIR,
        title=entry.title,
        candidate_id=entry.candidate_id,
    )
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    decision_id, token_id = materialization_module._materialization_governed_ids(
        receipt_id=receipt_id,
        persisted=persisted,
        artifact_path=artifact_path,
    )
    conflict = {
        "event": (
            "foreign.promotion.event"
            if conflict_shape == "wrong_event"
            else "promotion.transition.applied"
        ),
        "event_id": "foreign-promotion-event-id",
        "payload": {
            "receipt_id": "foreign-promotion-receipt-id",
            "intent_event_id": "foreign-source-event",
            "source_event": "foreign-source-event",
            "policy_decision": {"decision_id": decision_id},
            "decision_token": {
                "decision_id": decision_id,
                "token_id": token_id,
            },
            "outcome": {
                "status": "failed" if conflict_shape == "failed" else "applied"
            },
        },
    }
    hka_calls = 0
    original_write = materialization_module.write_note_relative

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)
    if injection_phase == "pre_hka":
        outbox.write_text(json.dumps(conflict) + "\n", encoding="utf-8")
    else:
        original_ensure = materialization_module._ensure_materialization_authority_receipt

        def inject_before_final_reconciliation(
            *args: object, **kwargs: object
        ) -> object:
            result = original_ensure(*args, **kwargs)
            with outbox.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(conflict, sort_keys=True) + "\n")
            return result

        monkeypatch.setattr(
            materialization_module,
            "_ensure_materialization_authority_receipt",
            inject_before_final_reconciliation,
        )

    with pytest.raises(MemoryMaterializationError, match="promotion"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == (0 if injection_phase == "pre_hka" else 1)
    persisted_after = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted_after is not None
    assert persisted_after.terminal is False


@pytest.mark.parametrize("receipt_class", ("promotion", "authority"))
def test_final_reconciliation_refuses_hidden_stable_receipt_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    receipt_class: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-late-stable-{receipt_class}"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def inject_hidden_conflict(*args: object, **kwargs: object) -> object:
        result = original_ensure(*args, **kwargs)
        records = _outbox_records(outbox)
        source = records[0] if receipt_class == "promotion" else records[1]
        duplicate = json.loads(json.dumps(source))
        duplicate["event_id"] = f"foreign-{receipt_class}-event-id"
        payload = duplicate["payload"]
        assert isinstance(payload, dict)
        if receipt_class == "promotion":
            payload["receipt_id"] = "foreign-promotion-receipt-id"
            outcome = payload["outcome"]
            assert isinstance(outcome, dict)
            outcome["review_state"] = "rejected"
        else:
            payload["materialization_id"] = "foreign-materialization-id"
            payload["promotion_receipt_id"] = "foreign-promotion-receipt-id"
            authority = payload["authority_receipt"]
            assert isinstance(authority, dict)
            authority["receipt_id"] = "foreign-authority-receipt-id"
            authority["outcome"] = "failed"
        with outbox.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(duplicate, sort_keys=True) + "\n")
        return result

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        inject_hidden_conflict,
    )

    with pytest.raises(MemoryMaterializationError):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_late_authority_duplicate_uses_exact_type_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-typed-authority-duplicate"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def interrupt_after_authority_receipt(*args: object, **kwargs: object) -> None:
        original_ensure(*args, **kwargs)
        raise OSError("injected interruption after AuthorityReceipt persistence")

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        interrupt_after_authority_receipt,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    original_preflight = materialization_module._preflight_materialization_receipt_identities
    injected = False

    def inject_duplicate_after_preflight(*args: object, **kwargs: object) -> None:
        nonlocal injected
        original_preflight(*args, **kwargs)
        if injected:
            return
        injected = True
        records = _outbox_records(outbox)
        duplicate = json.loads(json.dumps(records[1]))
        duplicate["payload"]["authority_receipt"]["fallback_used"] = 0
        records.append(duplicate)
        _rewrite_outbox_preserving_source_binding(
            outbox,
            "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        )

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        original_ensure,
    )
    monkeypatch.setattr(
        materialization_module,
        "_preflight_materialization_receipt_identities",
        inject_duplicate_after_preflight,
    )

    with pytest.raises(MemoryMaterializationError, match="AuthorityReceipt"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_normalization_changing_target_refuses_before_hka_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-normalized-target-alias"),
        store=store,
        vault=vault,
    )
    original_write = materialization_module.write_note_relative
    writes = 0

    def count_write(*args: object, **kwargs: object) -> object:
        nonlocal writes
        writes += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(materialization_module, "write_note_relative", count_write)
    with pytest.raises(MemoryMaterializationError, match="exact HKA target"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
            memory_dir=" Agent Memory",
        )

    assert writes == 0
    assert not list(vault_root.rglob("*.md"))
    assert outbox.read_text(encoding="utf-8") == ""
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_late_promotion_duplicate_compares_complete_event_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-promotion-envelope-duplicate"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def inject_conflicting_duplicate(*args: object, **kwargs: object) -> object:
        records = _outbox_records(outbox)
        assert len(records) == 1
        duplicate = json.loads(json.dumps(records[0]))
        duplicate["timestamp"] = "2000-01-01T00:00:00Z"
        records.append(duplicate)
        _rewrite_outbox_preserving_source_binding(
            outbox,
            "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        )
        return original_ensure(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        inject_conflicting_duplicate,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="conflicting memory promotion receipts",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    records = _outbox_records(outbox)
    assert [record["event"] for record in records] == [
        "promotion.transition.applied",
        "promotion.transition.applied",
    ]
    assert records[0]["timestamp"] != records[1]["timestamp"]
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_source_loss_before_authority_append_does_not_recreate_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-authority-source-loss"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def remove_history_before_authority(*args: object, **kwargs: object) -> object:
        assert _outbox_events(outbox) == ["promotion.transition.applied"]
        outbox.unlink()
        return original_ensure(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        remove_history_before_authority,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="owned materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not outbox.exists()
    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_final_receipt_chain_snapshot_fences_terminalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-final-receipt-chain-fence"),
        store=store,
        vault=vault,
    )
    original_read = materialization_module._read_materialization_authority_receipt
    authority_reads = 0

    def remove_promotion_before_final_authority_read(
        *args: object, **kwargs: object
    ) -> object:
        nonlocal authority_reads
        authority_reads += 1
        if authority_reads == 2:
            records = [
                record
                for record in _outbox_records(outbox)
                if record["event"]
                == materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT
            ]
            _rewrite_outbox_preserving_source_binding(
                outbox,
                "\n".join(json.dumps(record, sort_keys=True) for record in records)
                + "\n",
            )
        return original_read(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "_read_materialization_authority_receipt",
        remove_promotion_before_final_authority_read,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="complete governed materialization receipt chain",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert authority_reads == 2
    assert len(list(vault_root.rglob("*.md"))) == 1
    assert _outbox_events(outbox) == [
        materialization_module.MEMORY_MATERIALIZATION_AUTHORITY_EVENT
    ]
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize(
    "loss_window",
    ("during_db_read", "between_jsonl_stat_and_open"),
)
def test_final_snapshot_refuses_owned_jsonl_loss_during_db_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    loss_window: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-final-snapshot-source-loss"),
        store=store,
        vault=vault,
    )
    original_source_fsync = materialization_module._fsync_materialization_file
    original_is_file = Path.is_file
    original_write = materialization_module.write_note_relative
    source_loss_armed = False
    hka_calls = 0

    def arm_source_loss_after_terminal_fsync(path: Path) -> None:
        nonlocal source_loss_armed
        original_source_fsync(path)
        if path == outbox and len(_outbox_records(outbox)) == 2:
            source_loss_armed = True

    def read_db_copy() -> list[dict[str, object]]:
        if not source_loss_armed:
            return []
        records = _outbox_records(outbox)
        if loss_window == "during_db_read":
            outbox.unlink()
        return records

    def lose_source_after_jsonl_stat(path: Path) -> bool:
        is_file = original_is_file(path)
        if (
            path == outbox
            and source_loss_armed
            and loss_window == "between_jsonl_stat_and_open"
            and is_file
        ):
            outbox.unlink()
        return is_file

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    def query_owned_records(*args: object, **kwargs: object) -> object:
        records = _outbox_records(outbox) if outbox.exists() else []
        return query_promotion_receipts(
            args[0] if args else None,
            vault_root=kwargs["vault_root"],
            records=records,
        )

    monkeypatch.setattr(outbox_sources_module, "_db_outbox_configured", lambda: True)
    monkeypatch.setattr(
        outbox_sources_module,
        "_read_db_outbox_records",
        read_db_copy,
    )
    monkeypatch.setattr(
        materialization_module,
        "_fsync_materialization_file",
        arm_source_loss_after_terminal_fsync,
    )
    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        query_owned_records,
    )
    monkeypatch.setattr(Path, "is_file", lose_source_after_jsonl_stat)
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="owned materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert source_loss_armed is True
    assert hka_calls == 1
    assert not outbox.exists()
    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


@pytest.mark.parametrize(
    "failure_mode",
    (
        "outage",
        "duplicate_key_corruption",
        "malformed_json",
        "non_object_json_null",
        "non_object_json_array",
        "non_object_json_boolean",
        "non_object_json_number",
        "non_string_none",
        "non_string_array",
        "non_string_number",
        "nested_malformed_json_string",
        "nested_json_null_string",
        "nested_non_string_array",
        "nested_non_string_boolean",
        "event_topic_conflict",
    ),
)
def test_final_snapshot_refuses_late_db_failure_without_repeating_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-late-db-{failure_mode}"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt
    original_write = materialization_module.write_note_relative
    db_failure_armed = False
    db_failure_pending = True
    hka_calls = 0

    def arm_db_failure_after_authority_receipt(
        *args: object, **kwargs: object
    ) -> object:
        nonlocal db_failure_armed
        authority_receipt = original_ensure(*args, **kwargs)
        db_failure_armed = True
        return authority_receipt

    def read_db_records() -> list[dict[str, object]]:
        nonlocal db_failure_pending
        if not db_failure_armed or not db_failure_pending:
            return []
        db_failure_pending = False
        if failure_mode == "outage":
            raise OSError("injected late DB receipt outage")
        if failure_mode == "malformed_json" or failure_mode.startswith(
            ("non_object_json_", "non_string_", "nested_")
        ) or failure_mode == "event_topic_conflict":
            db_payloads: dict[str, object] = {
                "malformed_json": '{"event":"governance.authority_receipt.recorded",',
                "non_object_json_null": "null",
                "non_object_json_array": "[]",
                "non_object_json_boolean": "false",
                "non_object_json_number": "0",
                "non_string_none": None,
                "non_string_array": [],
                "non_string_number": 0,
                "nested_malformed_json_string": json.dumps(
                    {
                        "event": "governance.authority_receipt.recorded",
                        "payload": "{",
                    }
                ),
                "nested_json_null_string": json.dumps(
                    {
                        "event": "governance.authority_receipt.recorded",
                        "payload": "null",
                    }
                ),
                "nested_non_string_array": json.dumps(
                    {
                        "event": "governance.authority_receipt.recorded",
                        "payload": [],
                    }
                ),
                "nested_non_string_boolean": json.dumps(
                    {
                        "event": "governance.authority_receipt.recorded",
                        "payload": False,
                    }
                ),
                "event_topic_conflict": {
                    "event": "unrelated.event",
                    "event_type": "unrelated.event",
                    "payload": "{",
                },
            }

            class MalformedDbCursor:
                def __init__(self) -> None:
                    self._returned = False

                def fetchmany(self, _size: int) -> list[tuple[object, ...]]:
                    if self._returned:
                        return []
                    self._returned = True
                    return [
                        (
                            "db-malformed-json-row",
                            "governance.authority_receipt.recorded",
                            db_payloads[failure_mode],
                            None,
                        )
                    ]

            return list(
                outbox_sources_module._iter_db_outbox_records(
                    MalformedDbCursor()
                )
            )
        outbox_sources_module._coerce_record(
            '{"event":"governance.authority_receipt.recorded",'
            '"payload":{"authority_receipt":{'
            '"fallback_used":true,"fallback_used":false}}}'
        )
        raise AssertionError("duplicate-key DB evidence must fail closed")

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    @contextmanager
    def open_db_records():
        yield iter(())

    monkeypatch.setattr(outbox_sources_module, "_db_outbox_configured", lambda: True)
    monkeypatch.setattr(
        outbox_sources_module,
        "_read_db_outbox_records",
        read_db_records,
    )
    monkeypatch.setattr(
        outbox_sources_module,
        "_open_db_outbox_records",
        open_db_records,
    )
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        arm_db_failure_after_authority_receipt,
    )
    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="configured receipt source is unavailable during terminal reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert db_failure_armed is True
    assert db_failure_pending is False
    assert hka_calls == 1
    assert len(list(vault_root.rglob("*.md"))) == 1
    interrupted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert interrupted is not None
    assert interrupted.terminal is False
    assert interrupted.materializing is True

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.terminal is True
    assert hka_calls == 1
    assert len(list(vault_root.rglob("*.md"))) == 1
    completed = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert completed is not None
    assert completed.terminal is True


@pytest.mark.parametrize("structured_payload", ("{", None, []))
def test_structured_jsonl_payload_corruption_refuses_before_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    structured_payload: object,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-malformed-jsonl-{type(structured_payload).__name__}"),
        store=store,
        vault=vault,
    )
    outbox.write_text(
        json.dumps(
            {
                "event": "governance.authority_receipt.recorded",
                "event_id": "unreadable-authority-history",
                "payload": structured_payload,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    materialization_module._write_materialization_source_marker(outbox)
    hka_calls = 0

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        raise AssertionError("HKA must not run with unreadable authority history")

    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source is unavailable|receipt source.*reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 0
    assert not list(vault_root.rglob("*.md"))


@pytest.mark.parametrize(
    ("structured_payload", "conflicting_alias"),
    (("{", False), (None, False), ([], False), ("{", True)),
)
def test_structured_jsonl_payload_corruption_refuses_terminal_retry_without_repeating_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    structured_payload: object,
    conflicting_alias: bool,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-late-jsonl-{type(structured_payload).__name__}"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt
    original_write = materialization_module.write_note_relative
    hka_calls = 0

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    def inject_corruption_after_authority_receipt(
        *args: object, **kwargs: object
    ) -> object:
        authority_receipt = original_ensure(*args, **kwargs)
        records = _outbox_records(outbox)
        corrupt_record = {
            "event": (
                "unrelated.event"
                if conflicting_alias
                else "governance.authority_receipt.recorded"
            ),
            "event_id": "unreadable-authority-history",
            "payload": structured_payload,
        }
        if conflicting_alias:
            corrupt_record["event_type"] = "governance.authority_receipt.recorded"
        records.append(corrupt_record)
        _rewrite_outbox_preserving_source_binding(
            outbox,
            "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        )
        return authority_receipt

    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        inject_corruption_after_authority_receipt,
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source is unavailable|receipt source.*reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 1
    assert len(list(vault_root.rglob("*.md"))) == 1
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        original_ensure,
    )
    with pytest.raises(
        MemoryMaterializationError,
        match="receipt source is unavailable|receipt source.*reconciliation",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert hka_calls == 1
    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_retry_accepts_identical_receipts_from_db_and_owned_jsonl_without_repeating_hka(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-identical-dual-source-retry"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt
    original_write = materialization_module.write_note_relative
    hka_calls = 0

    def count_hka(*args: object, **kwargs: object) -> object:
        nonlocal hka_calls
        hka_calls += 1
        return original_write(*args, **kwargs)

    def interrupt_after_authority_receipt(*args: object, **kwargs: object) -> None:
        original_ensure(*args, **kwargs)
        raise OSError("injected interruption after AuthorityReceipt persistence")

    monkeypatch.setattr(materialization_module, "write_note_relative", count_hka)
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        interrupt_after_authority_receipt,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    durable_records = [
        json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event"] for record in durable_records] == [
        "promotion.transition.applied",
        "governance.authority_receipt.recorded",
    ]

    class PersistedDbCursor:
        def __init__(self) -> None:
            self._returned = False

        def fetchmany(self, _size: int) -> list[tuple[object, ...]]:
            if self._returned:
                return []
            self._returned = True
            return [
                (
                    f"db-row-{index}",
                    record["event"],
                    json.dumps(record),
                    datetime.fromisoformat(
                        str(record["timestamp"]).replace("Z", "+00:00")
                    ),
                )
                for index, record in enumerate(durable_records)
            ]

    def copied_db_records() -> list[dict[str, object]]:
        return list(
            outbox_sources_module._iter_db_outbox_records(PersistedDbCursor())
        )

    @contextmanager
    def open_copied_db_records():
        yield outbox_sources_module._iter_db_outbox_records(PersistedDbCursor())

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        original_ensure,
    )
    monkeypatch.setattr(outbox_sources_module, "_db_outbox_configured", lambda: True)
    monkeypatch.setattr(
        outbox_sources_module,
        "_read_db_outbox_records",
        copied_db_records,
    )
    monkeypatch.setattr(
        outbox_sources_module,
        "_open_db_outbox_records",
        open_copied_db_records,
    )

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.terminal is True
    assert hka_calls == 1
    assert len(list(vault_root.rglob("*.md"))) == 1
    assert [
        json.loads(line)["event"]
        for line in outbox.read_text(encoding="utf-8").splitlines()
    ] == [
        "promotion.transition.applied",
        "governance.authority_receipt.recorded",
    ]
    completed = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert completed is not None
    assert completed.terminal is True


@pytest.mark.parametrize("locator_vault_shape", ("foreign", "padded"))
def test_retry_refuses_mismatched_hka_locator_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locator_vault_shape: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-retry-locator-{locator_vault_shape}"),
        store=store,
        vault=vault,
    )
    original_ensure = materialization_module._ensure_materialization_authority_receipt

    def interrupt_after_authority_receipt(*args: object, **kwargs: object) -> None:
        original_ensure(*args, **kwargs)
        raise OSError("injected interruption after AuthorityReceipt persistence")

    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        interrupt_after_authority_receipt,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    records = _outbox_records(outbox)
    promotion_payload = records[0]["payload"]
    assert isinstance(promotion_payload, dict)
    mutation_receipt = promotion_payload["state_owner_receipt"]
    assert isinstance(mutation_receipt, dict)
    locator = mutation_receipt["locator"]
    assert isinstance(locator, dict)
    produced_vault = locator["vault"]
    assert isinstance(produced_vault, str)
    locator["vault"] = (
        "foreign-vault"
        if locator_vault_shape == "foreign"
        else f" {produced_vault} "
    )
    _rewrite_outbox_preserving_source_binding(
        outbox,
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
    )
    monkeypatch.setattr(
        materialization_module,
        "_ensure_materialization_authority_receipt",
        original_ensure,
    )
    monkeypatch.setattr(
        materialization_module,
        "write_note_relative",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("HKA must not repeat while validating retry evidence")
        ),
    )

    with pytest.raises(
        MemoryMaterializationError,
        match="HKA mutation receipt",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_retry_requires_owned_jsonl_source_even_when_another_source_is_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-missing-owned-source"),
        store=store,
        vault=vault,
    )

    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        lambda *args, **kwargs: PromotionReceiptQueryResult(source_available=False),
    )
    with pytest.raises(MemoryMaterializationError, match="source is unavailable"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )
    outbox.unlink()

    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        lambda *args, **kwargs: PromotionReceiptQueryResult(source_available=True),
    )
    writes = 0

    def count_write(*args: object, **kwargs: object) -> object:
        nonlocal writes
        writes += 1
        raise AssertionError("HKA must not run without the owned receipt source")

    monkeypatch.setattr(materialization_module, "write_note_relative", count_write)
    with pytest.raises(
        MemoryMaterializationError,
        match="owned materialization receipt source is unavailable",
    ):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert writes == 0
    assert not list(vault_root.rglob("*.md"))


@pytest.mark.parametrize(
    "identity",
    (
        "promotion",
        "authority",
        "authority_same_event_malformed",
        "authority_same_event_conflicting_duplicates",
        "authority_same_event_duplicate",
    ),
)
def test_receipt_identity_conflict_refuses_before_hka_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity: str,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id=f"candidate-{identity}-identity-conflict"),
        store=store,
        vault=vault,
    )
    receipt_id = materialization_module._stable_materialization_id(
        "receipt",
        entry=entry,
        vault_context=vault,
        channel="test",
    )
    event_id = receipt_id if identity == "promotion" else (
        materialization_module._materialization_authority_event_id(receipt_id)
    )
    event = (
        "governance.authority_receipt.recorded"
        if identity.startswith("authority_same_event")
        else "unrelated.event"
    )
    records = [
        {
            "event": event,
            "event_id": event_id,
            "payload": {"unrelated": True},
        }
    ]
    if identity in {
        "authority_same_event_conflicting_duplicates",
        "authority_same_event_duplicate",
    }:
        duplicate = json.loads(json.dumps(records[0]))
        if identity == "authority_same_event_conflicting_duplicates":
            duplicate["payload"] = {"unrelated": "different"}
        records.append(duplicate)
    outbox.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    writes = 0

    def count_write(*args: object, **kwargs: object) -> object:
        nonlocal writes
        writes += 1
        raise AssertionError("HKA must not run after a receipt identity conflict")

    monkeypatch.setattr(materialization_module, "write_note_relative", count_write)
    with pytest.raises(MemoryMaterializationError, match="conflicting event"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert writes == 0
    assert not list(vault_root.rglob("*.md"))


def test_blocked_materialization_keeps_promotion_actionable(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(candidate_id="candidate-retry")
    entry = _promoted(candidate, store=store, vault=vault)

    with pytest.raises(MemoryMaterializationError):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_blocked_guard(),
            outbox_path=outbox,
        )

    raw_receipts = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    assert raw_receipts[0]["payload"]["outcome"]["status"] == "failed"
    assert store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    ).terminal is False

    rebuilt = MemoryCandidateReviewQueue(
        decision_store=store,
        vault_context=vault,
        channel="test",
    )
    assert rebuilt.enqueue(candidate).candidate_id == candidate.candidate_id
    assert [item.candidate_id for item in rebuilt.pending()] == [candidate.candidate_id]


def test_materialization_create_race_does_not_append_applied_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(_candidate(candidate_id="candidate-raced"), store=store, vault=vault)
    real_write = materialization_module.write_note_relative

    def interleaved_write(note_rel_path: str, content: str, **kwargs: object):
        target = Path(str(kwargs["vault_root"])) / note_rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("foreign raced materialization\n", encoding="utf-8")
        return real_write(note_rel_path, content, **kwargs)

    monkeypatch.setattr(materialization_module, "write_note_relative", interleaved_write)

    with pytest.raises(MemoryMaterializationError):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    receipts = query_promotion_receipts(vault_root=vault_root, outbox_path=outbox)
    assert [row.outcome_status for row in receipts.rows] == ["failed"]


def test_identical_create_race_cannot_claim_an_unreceipted_hka_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-identical-race"),
        store=store,
        vault=vault,
    )
    real_write = materialization_module.write_note_relative

    def interleaved_write(note_rel_path: str, content: str, **kwargs: object):
        target = Path(str(kwargs["vault_root"])) / note_rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return real_write(note_rel_path, content, **kwargs)

    monkeypatch.setattr(materialization_module, "write_note_relative", interleaved_write)

    with pytest.raises(MemoryMaterializationError, match="failed"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    receipts = query_promotion_receipts(vault_root=vault_root, outbox_path=outbox)
    assert [row.outcome_status for row in receipts.rows] == ["failed"]
    assert _outbox_events(outbox) == ["promotion.transition.applied"]
    persisted = store.get_decision(
        entry.candidate_id,
        vault_context=vault,
        channel="test",
    )
    assert persisted is not None
    assert persisted.terminal is False
    assert persisted.materializing is True


def test_materialized_note_preserves_provenance_and_human_authorship(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    existing = vault_root / "Agent Memory" / "explicit-semantic-memory-candidat.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("Human-authored note stays put.\n", encoding="utf-8")
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    candidate = _candidate(candidate_id="candidate-")
    entry = _promoted(candidate, store=store, vault=vault)

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=tmp_path / "outbox.jsonl",
    )

    assert existing.read_text(encoding="utf-8") == "Human-authored note stays put.\n"
    assert result.artifact_path == "Agent Memory/explicit-semantic-memory-candidat-2.md"
    body = (vault_root / result.artifact_path).read_text(encoding="utf-8")
    assert "agent-promoted-memory" in body
    assert "promoted_from_candidate_id: candidate-" in body
    assert "scope_id: scope:test/materialization" in body
    assert "companion-ui:reviewer" in body
    assert "note:source.md" in body
    assert "The user explicitly prefers design docs before code." in body


def test_non_semantic_promotion_does_not_materialize(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    candidate = _candidate(
        candidate_id="candidate-preference",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        title="Preference memory",
    )
    entry = _promoted(candidate, store=store, vault=vault)

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=tmp_path / "outbox.jsonl",
    )

    assert result.status == "not_semantic"
    assert result.artifact_path is None
    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    ).terminal is True
