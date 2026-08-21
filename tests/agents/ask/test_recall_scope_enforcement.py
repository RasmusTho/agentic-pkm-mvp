"""Production ASK wiring for scope-bound promoted-memory recall (#5019)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.agent_memory.candidate import MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_retrieval import RecallCandidate
from app.agent_memory.provisional_recall import ProvisionalRecallSearch
from app.agents.ask import graph as ask_graph
from app.agents.ask.state import AgentState
from app.settings.models import AskSettings


def _candidate(*, applied_scope_id: str | None = None) -> RecallCandidate:
    promoted = PromotedMemory(
        outcome=ReviewState.ACCEPTED,
        candidate=MemoryCandidate(
            candidate_id="memory-work",
            title="Work deployment posture",
            memory_type=MemoryType.SEMANTIC_MEMORY,
            review_state=ReviewState.ACCEPTED,
            inferred=False,
            content="Deploy through the work release checklist.",
            source_refs=["note:work.md"],
        ),
        decided_by="companion-ui:reviewer",
        decided_at=datetime.now(timezone.utc),
    )
    return RecallCandidate(
        promoted=promoted,
        score=1.0,
        reason="content matched deployment",
        artifact_path="Agent Memory/memory-work.md",
        memory_scope_id="scope-work",
        applied_scope_id=applied_scope_id,
    )


def _prepare_recall_node(tmp_path: Path, monkeypatch, captured: dict[str, object]) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setattr(ask_graph, "_active_recall_vault_root", lambda: vault_root)
    monkeypatch.setattr(
        ask_graph,
        "retrieve_relevant_provisional",
        lambda *args, **kwargs: ProvisionalRecallSearch(candidates=(), excluded=()),
    )
    receipt_path = tmp_path / "runtime" / "recall.jsonl"
    monkeypatch.setattr(ask_graph, "_recall_receipt_path", lambda: receipt_path)

    def fake_retrieve(query: str, **kwargs):
        captured["query"] = query
        captured["active_scope_id"] = kwargs.get("active_scope_id")
        return [_candidate(applied_scope_id=kwargs.get("active_scope_id"))]

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", fake_retrieve)
    return receipt_path


def test_ask_graph_enforces_scope_on_promoted_recall(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    receipt_path = _prepare_recall_node(tmp_path, monkeypatch, captured)

    state = ask_graph._recall_node(
        AgentState(query="deployment", active_scope="scope-work"),
        ask_settings=AskSettings(),
    )

    assert captured["active_scope_id"] == "scope-work"
    assert [item.artifact_id for item in state.recalled] == ["memory-work"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["payload"]["applied_scope_id"] == "scope-work"


def test_unbound_ask_preserves_default_promoted_recall(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}
    receipt_path = _prepare_recall_node(tmp_path, monkeypatch, captured)
    monkeypatch.setattr(ask_graph, "_resolve_domain_scope", lambda: None)

    state = ask_graph._recall_node(
        AgentState(query="deployment"),
        ask_settings=AskSettings(),
    )

    assert captured["active_scope_id"] is None
    assert [item.artifact_id for item in state.recalled] == ["memory-work"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["payload"]["applied_scope_id"] is None
