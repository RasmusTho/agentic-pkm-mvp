from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent_memory.candidate import MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.materialization import materialize_promoted_memory
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import (
    ActivationReason,
    RecallExplanation,
    RecallUseRight,
    SourceProvenance,
)
from app.agent_memory.review_decision_store import ReviewDecisionStore
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewDecision
from app.agents.ask import graph as ask_graph
from app.agents.ask.graph import run_ask_graph
from app.retrieval.capability import RetrievalHit, RetrievalResponse
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard


def _vault(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-a",
        active_vault_name="Vault A",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _candidate(
    candidate_id: str,
    *,
    title: str = "Recall runtime",
    content: str = "Guarded memory recall remains read-only awareness.",
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title=title,
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=False,
        content=content,
        source_refs=[f"note:{candidate_id}.md", "session:2026-06-13T09:00:00Z"],
        derived_from=f"vault:{candidate_id}.md",
        generated_by="companion_agent",
    )


def _promoted(candidate: MemoryCandidate) -> PromotedMemory:
    return PromotedMemory(
        outcome=ReviewState.ACCEPTED,
        candidate=candidate,
        decided_by="companion-ui:reviewer",
        decided_at=datetime.now(timezone.utc),
    )


def _materialize(
    candidate: MemoryCandidate,
    *,
    vault: VaultContext,
    store: ReviewDecisionStore,
) -> str:
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(candidate)
    entry = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Confirmed.",
    )
    store.record_decision(entry, vault_context=vault, channel="test")
    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
    )
    assert result.artifact_path is not None
    return result.artifact_path


def _retrieval_response(query: str, *, text: str = "ASK source text") -> RetrievalResponse:
    return RetrievalResponse(
        query=query,
        trace_id="trace-ask-recall",
        hits=[
            RetrievalHit(
                object_id="ask-source-1",
                doc_id="ask-source-1",
                text=text,
                score=0.9,
                snippet=text,
                source_ref="vault/source.md",
                payload={"title": "ASK Source", "origin": "vault"},
            )
        ],
    )


def _empty_retrieval_response(query: str) -> RetrievalResponse:
    return RetrievalResponse(query=query, trace_id="trace-ask-recall", hits=[])


def _receipt_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_ask_run_invokes_guarded_recall_with_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("REASONING_ENABLE", "1")
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    artifact_path = _materialize(
        _candidate("candidate-recall-runtime"),
        vault=vault,
        store=store,
    )
    artifact = vault_root / artifact_path
    before = artifact.read_text(encoding="utf-8")

    calls: list[dict[str, Any]] = []
    original_activate = ask_graph.activate_guarded_recall

    def _spy_activate(promoted: PromotedMemory, **kwargs: Any):
        calls.append(kwargs)
        return original_activate(promoted, **kwargs)

    captured_context: dict[str, str] = {}

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _retrieval_response(request.query)

    def _fake_llm_answer(question: str, context: str, ask_settings):  # type: ignore[no-untyped-def]
        captured_context["context"] = context
        return "Answer composed with recall awareness.", {"provider": "test"}

    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)
    monkeypatch.setattr(ask_graph, "activate_guarded_recall", _spy_activate)
    monkeypatch.setattr(ask_graph, "llm_answer", _fake_llm_answer)

    state = run_ask_graph("How does recall runtime stay read-only?", trace_id="trace-recall-ask")

    assert len(calls) == 1
    assert calls[0]["use_right"] is RecallUseRight.ACTIVATABLE
    assert calls[0]["activation_reason"] is ActivationReason.CONTEXTUAL_RELEVANCE
    assert calls[0].get("requested_action_scope") is None
    assert state.recalled
    assert state.recalled[0].title == "Recall runtime"
    assert state.recalled[0].receipt_reference
    assert state.reasoning
    assert any("recall:candidate-recall-runtime" in item for item in state.reasoning)
    assert "RECALLED MEMORY 1" in captured_context["context"]
    assert "Recall runtime" in captured_context["context"]
    assert artifact.read_text(encoding="utf-8") == before

    receipts = _receipt_records(tmp_path / "runtime" / "agent_memory" / "recall_receipts.jsonl")
    assert receipts[0]["event"] == "agent_memory.recall.activated"
    assert receipts[0]["payload"]["memory_id"] == "candidate-recall-runtime"
    assert receipts[0]["payload"]["requested_use_right"] == "activatable"
    assert receipts[0]["payload"]["may_write"] is False


def test_ask_recall_uses_selected_vault_before_env_vault(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    selected_vault_root = tmp_path / "selected-vault"
    env_vault_root = tmp_path / "env-vault"
    selected_vault_root.mkdir()
    env_vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(env_vault_root))
    vault = _vault(selected_vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    _materialize(
        _candidate("candidate-selected-vault"),
        vault=vault,
        store=store,
    )

    class _SelectedVaultManager:
        context = vault

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _retrieval_response(request.query)

    monkeypatch.setattr(ask_graph, "get_vault_manager", lambda: _SelectedVaultManager())
    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)

    state = run_ask_graph("How does recall runtime stay read-only?", trace_id="trace-selected-vault")

    assert state.recalled
    assert state.recalled[0].artifact_id == "candidate-selected-vault"


def test_recall_is_read_only(monkeypatch) -> None:
    candidate = _candidate("candidate-read-only")
    promoted = _promoted(candidate)

    class _GuardedRecallWithoutWritableAccess:
        memory_id = candidate.candidate_id
        may_answer = True
        may_propose = True
        receipt_id = "receipt-read-only"
        explanation = RecallExplanation(
            artifact_id=candidate.candidate_id,
            title=candidate.title,
            artifact_class=candidate.artifact_class,
            artifact_type=candidate.artifact_type,
            memory_type=candidate.memory_type.value,
            use_right=RecallUseRight.ACTIVATABLE,
            lifecycle_state="promoted",
            review_state=ReviewState.ACCEPTED,
            activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
            why_now="content matched recall",
            source_provenance=SourceProvenance(source_refs=list(candidate.source_refs)),
            authority_limits=["memory_is_supporting_input_not_source_of_truth", "does_not_authorize_writeback"],
            receipt_reference="receipt-read-only",
        )

        @property
        def may_write(self) -> bool:
            raise AssertionError("ASK recall wiring must not exercise may_write")

    calls: list[dict[str, Any]] = []

    def _fake_retrieve_relevant_promoted(query: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        return [
            ask_graph.RecallCandidate(
                promoted=promoted,
                score=1.0,
                reason="content matched recall",
            )
        ]

    def _fake_activate(promoted_memory: PromotedMemory, **kwargs: Any):  # type: ignore[no-untyped-def]
        calls.append(kwargs)
        return _GuardedRecallWithoutWritableAccess()

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _retrieval_response(request.query)

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _fake_retrieve_relevant_promoted)
    monkeypatch.setattr(ask_graph, "activate_guarded_recall", _fake_activate)
    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)

    state = run_ask_graph("recall read only", trace_id="trace-read-only")

    assert state.recalled[0].receipt_reference == "receipt-read-only"
    assert calls[0]["use_right"] is RecallUseRight.ACTIVATABLE
    assert calls[0].get("requested_action_scope") is None


def test_ask_answers_from_recall_when_retrieval_is_empty(tmp_path: Path, monkeypatch) -> None:
    """Recall-only path: zero retrieval hits but a usable may_answer memory must still answer.

    Regression for #1990: the ASK answer node short-circuited with "No results found."
    whenever retrieval returned zero hits, ignoring guarded recall even when recall produced
    an activatable memory.
    """
    monkeypatch.chdir(tmp_path)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setenv("REASONING_ENABLE", "1")
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    _materialize(
        _candidate("candidate-recall-only"),
        vault=vault,
        store=store,
    )

    captured_context: dict[str, str] = {}
    llm_calls: list[str] = []

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _empty_retrieval_response(request.query)

    def _fake_llm_answer(question: str, context: str, ask_settings):  # type: ignore[no-untyped-def]
        captured_context["context"] = context
        llm_calls.append(question)
        return "Answer composed from recalled memory only.", {"provider": "test"}

    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)
    monkeypatch.setattr(ask_graph, "llm_answer", _fake_llm_answer)

    state = run_ask_graph("How does recall runtime stay read-only?", trace_id="trace-recall-only")

    assert state.hits == []
    assert state.recalled
    assert state.recalled[0].title == "Recall runtime"
    # The answer node must NOT short-circuit; LLM composition runs over recalled memory.
    assert llm_calls == ["How does recall runtime stay read-only?"]
    assert "RECALLED MEMORY 1" in captured_context["context"]
    assert state.answer.startswith("Answer composed from recalled memory only.")
    # Treatment A (#1972): recall fired, so the answer carries the attribution footer.
    assert "Recalled from: Recall runtime" in state.answer
    assert state.answer != "No results found."


def test_ask_recall_only_fallback_uses_content_not_match_reason(tmp_path: Path, monkeypatch) -> None:
    """Non-reasoning recall-only fallback surfaces the recalled fact, not match metadata (#1990).

    Regression for the Codex review note: when REASONING is disabled and retrieval is empty,
    the fallback must answer from the recalled memory body, not from the lexical match reason
    (e.g. "content matched ...").
    """
    monkeypatch.chdir(tmp_path)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.delenv("REASONING_ENABLE", raising=False)
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    _materialize(
        _candidate(
            "candidate-recall-content",
            title="Recall runtime",
            content="Guarded memory recall remains read-only awareness.",
        ),
        vault=vault,
        store=store,
    )

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _empty_retrieval_response(request.query)

    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)

    state = run_ask_graph("How does recall runtime stay read-only?", trace_id="trace-recall-content")

    assert state.hits == []
    assert state.recalled
    assert state.answer != "No results found."
    # The actual recalled fact must appear; match-reason metadata must not be the answer.
    assert "Guarded memory recall remains read-only awareness." in state.answer
    assert "matched" not in state.answer
    assert state.recalled_content[state.recalled[0].artifact_id] == (
        "Guarded memory recall remains read-only awareness."
    )


def test_no_recall_when_no_relevant_memory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    _materialize(
        _candidate(
            "candidate-garden",
            title="Garden planning",
            content="Tomatoes need water in July.",
        ),
        vault=vault,
        store=store,
    )

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _retrieval_response(request.query, text="Vault fallback snippet should remain normal.")

    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)

    state = run_ask_graph("fallback snippet", trace_id="trace-no-recall")

    assert state.answer == "Vault fallback snippet should remain normal."
    assert state.recalled == []
    assert not (tmp_path / "runtime" / "agent_memory" / "recall_receipts.jsonl").exists()
