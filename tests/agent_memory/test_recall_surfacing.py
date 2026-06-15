"""#1972: recalled memory is attributed in ASK answers (treatment A — footer).

When guarded recall fires in the ASK path, the answer carries an attribution
footer keyed to the recall receipt; when recall did not fire, no footer is shown.
"""

from __future__ import annotations

from pathlib import Path

from app.agent_memory.candidate import MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.materialization import materialize_promoted_memory
from app.agent_memory.recall_explanation import (
    ActivationReason,
    MemoryLifecycleState,
    RecallExplanation,
    RecallUseRight,
    SourceProvenance,
    render_recall_footer,
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


def _candidate(candidate_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title="Recall runtime",
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=False,
        content="Guarded memory recall remains read-only awareness.",
        source_refs=[f"note:{candidate_id}.md", "session:2026-06-13T09:00:00Z"],
        derived_from=f"vault:{candidate_id}.md",
        generated_by="companion_agent",
    )


def _materialize(candidate: MemoryCandidate, *, vault: VaultContext, store: ReviewDecisionStore) -> str:
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


def test_render_recall_footer_unit() -> None:
    assert render_recall_footer([]) == ""
    explanation = RecallExplanation(
        artifact_id="m1",
        title="Deadline habit",
        artifact_class="agentic_memory",
        memory_type="semantic_memory",
        use_right=RecallUseRight.ACTIVATABLE,
        lifecycle_state=MemoryLifecycleState.PROMOTED,
        review_state=ReviewState.ACCEPTED,
        activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
        why_now="relevant now",
        source_provenance=SourceProvenance(),
        receipt_reference="rcpt-123",
    )
    assert render_recall_footer([explanation]) == "Recalled from: Deadline habit · receipt rcpt-123"
    # No receipt -> no attribution invented.
    assert render_recall_footer([explanation.model_copy(update={"receipt_reference": None})]) == ""


def test_response_surfaces_recall_with_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    _materialize(_candidate("candidate-footer"), vault=vault, store=store)

    monkeypatch.setattr(ask_graph, "retrieve", lambda request: _retrieval_response(request.query))

    state = run_ask_graph("How does recall runtime stay read-only?", trace_id="trace-footer")

    assert state.recalled, "guarded recall should have fired"
    receipt = state.recalled[0].receipt_reference
    assert receipt, "the recall explanation must carry a receipt reference"
    # Treatment A: the answer exposes the recalled memory, keyed to its receipt.
    assert "Recalled from:" in state.answer
    assert state.recalled[0].title in state.answer
    assert receipt in state.answer


def test_no_footer_when_recall_did_not_fire(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))

    monkeypatch.setattr(
        ask_graph, "retrieve", lambda request: _retrieval_response(request.query, text="Plain answer.")
    )

    state = run_ask_graph("an unrelated question with no promoted memory", trace_id="trace-no-footer")

    assert state.recalled == [], "no memory should have been recalled"
    assert "Recalled from:" not in (state.answer or "")
