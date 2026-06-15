"""Default-outbox parity tests for memory materialization (#2014, AC#2).

When no explicit ``outbox_path`` is supplied, the receipt-append path and the
post-write queryability check must resolve to the same outbox. Otherwise a
successful durable write fails the queryability assertion and never marks the
decision terminal (the receipt is appended to the materialization default while
the query reads the configured index/watcher outbox).

Source authority:
- docs/DURABLE_MEMORY_AND_RECALL/MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.agent_memory.materialization as materialization_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.materialization import materialize_promoted_memory
from app.agent_memory.review_decision_store import ReviewDecisionStore
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewDecision
from app.receipts.promotion_receipts import query_promotion_receipts
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard


def _vault(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-default",
        active_vault_name="Vault Default",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _promoted_entry(store: ReviewDecisionStore, vault: VaultContext):
    queue = MemoryCandidateReviewQueue()
    candidate = MemoryCandidate(
        candidate_id="candidate-default-outbox",
        title="Default outbox semantic memory",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=False,
        content="The user prefers durable receipts.",
        source_refs=["note:source.md", "session:2026-06-14T10:00:00Z"],
        derived_from="vault:source.md",
        generated_by="companion_agent",
    )
    queue.enqueue(candidate)
    entry = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
    )
    store.record_decision(entry, vault_context=vault, channel="test")
    return entry


def test_default_outbox_append_and_query_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    default_outbox = tmp_path / "materialization_receipts.jsonl"
    # Point both the module default and any configured index outbox somewhere
    # else, so a divergence between append and query would surface as a
    # queryability failure (no silent fallback to the same file).
    monkeypatch.setattr(
        materialization_module,
        "DEFAULT_MATERIALIZATION_RECEIPTS_PATH",
        default_outbox,
    )
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "other_index_outbox.jsonl"))

    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    entry = _promoted_entry(store, vault)

    # No explicit outbox_path: append and verification must share the default.
    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
    )

    assert result.status == "materialized"
    assert result.terminal is True
    assert result.receipt_id

    # The receipt landed in the materialization default outbox.
    assert default_outbox.exists()

    # Querying the same default outbox finds the appended receipt.
    receipts = query_promotion_receipts(vault_root=vault_root, outbox_path=default_outbox)
    assert [row.receipt_id for row in receipts.rows] == [result.receipt_id]

    # The decision was marked terminal (the queryability check passed).
    record = store.get_decision(entry.candidate_id, vault_context=vault, channel="test")
    assert record is not None
    assert record.terminal is True
