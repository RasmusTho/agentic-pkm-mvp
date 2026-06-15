"""Live review-accept path materialization tests (#2014, AC#1).

The companion review-accept endpoint must materialize accepted semantic
candidates into the vault through the governed materialization path and mark the
stored review decision terminal — not merely record a non-terminal promote
decision. This wires ``materialize_promoted_memory`` into
``app/api/routes/companion.py``'s accept branch.

Source authority:
- docs/DURABLE_MEMORY_AND_RECALL/MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md
- docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.agent_memory.materialization as materialization_module
import app.api.routes.companion as companion_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_decision_store import ReviewDecisionStore
from app.agent_memory.review_queue import MemoryCandidateReviewQueue
from app.api.app import app
from app.vault.manager import VaultContext


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _decision_url(candidate_id: str) -> str:
    return f"/api/companion/memory/review-queue/{candidate_id}/decision"


def _semantic_candidate(**overrides: Any) -> MemoryCandidate:
    fields: dict[str, Any] = dict(
        title="Asserted semantic memory",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        # Non-inferred (asserted) so the governed promotion gate admits it as a
        # semantic memory rather than refusing it as inferred single-source.
        inferred=False,
        content="The user keeps design docs ahead of code.",
        source_refs=["note:source.md", "session:2026-06-14T09:00:00Z"],
        derived_from="vault:source.md",
        generated_by="companion_agent",
    )
    fields.update(overrides)
    return MemoryCandidate(**fields)


def test_accept_materializes_and_marks_terminal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    receipts_path = tmp_path / "materialization_receipts.jsonl"
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    queue = MemoryCandidateReviewQueue()
    vault_context = VaultContext(
        status="selected",
        active_vault_id="vault-live",
        active_vault_name="Vault Live",
        active_vault_path=str(vault_root),
    )

    monkeypatch.setattr(companion_module, "_orientation_memory_review_queue", lambda: queue)
    monkeypatch.setattr(companion_module, "_memory_review_decision_store", lambda: store)
    monkeypatch.setattr(companion_module, "_memory_review_vault_context", lambda: vault_context)
    monkeypatch.setattr(companion_module, "_memory_review_channel", lambda: "live")
    monkeypatch.setattr(
        materialization_module,
        "DEFAULT_MATERIALIZATION_RECEIPTS_PATH",
        receipts_path,
    )

    candidate = _semantic_candidate()
    queue.enqueue(candidate)

    resp = client.post(
        _decision_url(candidate.candidate_id),
        json={"action": "accept", "reviewed_by": "reviewer:human", "notes": "Confirmed."},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "accepted"
    # The candidate is no longer pending because the durable write succeeded and
    # the decision was marked terminal.
    assert data["candidate_pending"] is False

    materialization = data["materialization"]
    assert materialization is not None
    assert materialization["status"] == "materialized"
    assert materialization["terminal"] is True
    assert materialization["receipt_id"]
    artifact_rel = materialization["artifact_path"]
    assert artifact_rel

    # The vault artifact was actually written.
    artifact = vault_root / artifact_rel
    assert artifact.exists()
    body = artifact.read_text(encoding="utf-8")
    assert "agent-promoted-memory" in body
    assert "The user keeps design docs ahead of code." in body

    # The stored review decision is terminal.
    record = store.get_decision(
        candidate.candidate_id, vault_context=vault_context, channel="live"
    )
    assert record is not None
    assert record.terminal is True
